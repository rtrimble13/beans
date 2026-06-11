"""Investment tracking: lots, prices, and mark-to-market.

Holdings are tracked as FIFO lots (symbol, quantity, total cost) attached
to an asset account, alongside a price history. Buys and sells are real
double-entry transactions; `mark` posts an adjustment against
Income:Unrealized Gains so the balance sheet carries market value while
staying balanced — the household version of mark-to-market accounting.

Quantities are exact decimal strings; costs and prices are integer minor
units (price = minor units per share/unit).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from beans.ledger import Ledger
from beans.models import Account, AccountType, Posting
from beans.render import Table, bold, money
from beans.utils import BeansError

UNREALIZED_ACCOUNT = "Income:Unrealized Gains"
REALIZED_ACCOUNT = "Income:Realized Gains"


def parse_quantity(text: str) -> Decimal:
    try:
        qty = Decimal(str(text).strip())
    except InvalidOperation:
        raise BeansError(f"invalid quantity: {text!r}")
    if qty <= 0:
        raise BeansError("quantity must be positive")
    return qty


def _format_quantity(qty: Decimal) -> str:
    text = format(qty.normalize(), "f")
    return text


def _income_account(led: Ledger, name: str) -> Account:
    try:
        return led.find_account(name)
    except BeansError:
        return led.add_account(name, AccountType.INCOME,
                               description="created by beans invest")


def buy(led: Ledger, symbol: str, quantity: Decimal, price: int,
        account: Account, cash: Account, when: date) -> dict:
    """Buy quantity at price: cash out, investment in, lot recorded."""
    cost = int((quantity * price).to_integral_value())
    if cost <= 0:
        raise BeansError("purchase cost must be positive")
    txn = led.add_transaction(
        when,
        f"Buy {_format_quantity(quantity)} {symbol.upper()}",
        [Posting(account_id=account.id, amount=cost),
         Posting(account_id=cash.id, amount=-cost)],
        tags=["invest"],
    )
    led.add_lot(account, symbol, str(quantity), cost, when)
    led.set_price(symbol, when, price)
    return {"txn_id": txn.id, "cost": cost}


def sell(led: Ledger, symbol: str, quantity: Decimal, price: int,
         account: Account, cash: Account, when: date) -> dict:
    """Sell FIFO: cash in, lot cost relieved, gain/loss to income."""
    lots = led.lots(account=account, symbol=symbol)
    held = sum(Decimal(lot["quantity"]) for lot in lots)
    if quantity > held:
        raise BeansError(
            f"cannot sell {_format_quantity(quantity)} {symbol.upper()}: "
            f"only {_format_quantity(held)} held in {account.name}"
        )
    proceeds = int((quantity * price).to_integral_value())
    remaining = quantity
    cost_relieved = 0
    for lot in lots:
        if remaining <= 0:
            break
        lot_qty = Decimal(lot["quantity"])
        if remaining >= lot_qty:
            cost_relieved += lot["cost"]
            remaining -= lot_qty
            led.delete_lot(lot["id"])
        else:
            portion = int((Decimal(lot["cost"]) * remaining
                           / lot_qty).to_integral_value())
            cost_relieved += portion
            led.update_lot(lot["id"], str(lot_qty - remaining),
                           lot["cost"] - portion)
            remaining = Decimal(0)
    gain = proceeds - cost_relieved
    realized = _income_account(led, REALIZED_ACCOUNT)
    postings = [
        Posting(account_id=cash.id, amount=proceeds),
        Posting(account_id=account.id, amount=-cost_relieved),
    ]
    if gain:
        postings.append(Posting(account_id=realized.id, amount=-gain))
    txn = led.add_transaction(
        when,
        f"Sell {_format_quantity(quantity)} {symbol.upper()}",
        postings,
        tags=["invest"],
    )
    led.set_price(symbol, when, price)
    return {"txn_id": txn.id, "proceeds": proceeds,
            "cost_relieved": cost_relieved, "gain": gain}


def portfolio(led: Ledger, as_of: date | None = None) -> dict:
    """Holdings by account and symbol, valued at the latest known price."""
    as_of = as_of or date.today()
    by_key: dict[tuple[int, str], dict] = {}
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    for lot in led.lots():
        key = (lot["account_id"], lot["symbol"])
        entry = by_key.setdefault(key, {
            "account": accounts[lot["account_id"]].name,
            "symbol": lot["symbol"],
            "quantity": Decimal(0),
            "cost_basis": 0,
        })
        entry["quantity"] += Decimal(lot["quantity"])
        entry["cost_basis"] += lot["cost"]
    rows = []
    for entry in sorted(by_key.values(),
                        key=lambda e: (e["account"].lower(), e["symbol"])):
        latest = led.latest_price(entry["symbol"], as_of)
        market = (int((entry["quantity"] * latest[1]).to_integral_value())
                  if latest else None)
        rows.append({
            "account": entry["account"],
            "symbol": entry["symbol"],
            "quantity": _format_quantity(entry["quantity"]),
            "cost_basis": entry["cost_basis"],
            "price": latest[1] if latest else None,
            "price_date": latest[0] if latest else None,
            "market_value": market,
            "unrealized": (market - entry["cost_basis"]
                           if market is not None else None),
        })
    valued = [r for r in rows if r["market_value"] is not None]
    return {
        "report": "portfolio",
        "as_of": as_of,
        "rows": rows,
        "total_cost_basis": sum(r["cost_basis"] for r in rows),
        "total_market_value": sum(r["market_value"] for r in valued),
        "total_unrealized": sum(r["unrealized"] for r in valued),
    }


def render_portfolio(data: dict, decimals: int, symbol: str) -> str:
    if not data["rows"]:
        return ("No holdings. Record one with: beans invest buy SYMBOL QTY "
                "--price P --account <investment account> --from <cash>")
    lines = [bold("PORTFOLIO"), f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(headers=["Account", "Symbol", "Qty", "Cost Basis",
                           "Price", "Market Value", "Unrealized"],
                  align="llrrrrr")
    for row in data["rows"]:
        table.add(row["account"], row["symbol"], row["quantity"],
                  money(row["cost_basis"], decimals),
                  money(row["price"], decimals) if row["price"] is not None
                  else "?",
                  money(row["market_value"], decimals)
                  if row["market_value"] is not None else "?",
                  money(row["unrealized"], decimals)
                  if row["unrealized"] is not None else "?")
    table.rule()
    table.add(bold("Total"), "", "",
              money(data["total_cost_basis"], decimals, symbol), "",
              money(data["total_market_value"], decimals, symbol),
              money(data["total_unrealized"], decimals, symbol))
    lines.append(table.render())
    if any(r["price"] is None for r in data["rows"]):
        lines.append("")
        lines.append("Some symbols have no price — set one with "
                     "`beans price set SYMBOL PRICE`.")
    return "\n".join(lines)


def mark_to_market(led: Ledger, when: date, dry_run: bool = False) -> dict:
    """Post adjustments so each investment account's book balance equals
    the market value of its holdings, against Income:Unrealized Gains."""
    data = portfolio(led, as_of=when)
    raw = led.balances(as_of=when)
    by_account: dict[str, dict] = {}
    for row in data["rows"]:
        if row["market_value"] is None:
            raise BeansError(
                f"no price for {row['symbol']} — set one with "
                f"`beans price set {row['symbol']} PRICE` before marking"
            )
        entry = by_account.setdefault(row["account"], {"market": 0})
        entry["market"] += row["market_value"]
    adjustments = []
    unrealized = _income_account(led, UNREALIZED_ACCOUNT)
    for account_name, entry in sorted(by_account.items()):
        account = led.find_account(account_name)
        book = raw.get(account.id, 0)
        delta = entry["market"] - book
        if delta == 0:
            continue
        txn_id = None
        if not dry_run:
            txn = led.add_transaction(
                when,
                f"Mark to market: {account.name}",
                [Posting(account_id=account.id, amount=delta),
                 Posting(account_id=unrealized.id, amount=-delta)],
                tags=["invest", "mark"],
            )
            txn_id = txn.id
        adjustments.append({
            "id": txn_id,
            "account": account.name,
            "book": book,
            "market": entry["market"],
            "adjustment": delta,
        })
    return {
        "report": "mark_to_market",
        "as_of": when,
        "dry_run": dry_run,
        "adjustments": adjustments,
    }


def render_mark(data: dict, decimals: int, symbol: str) -> str:
    verb = "Would post" if data["dry_run"] else "Posted"
    if not data["adjustments"]:
        return ("All investment accounts already carry market value — "
                "nothing to adjust.")
    lines = [f"{verb} {len(data['adjustments'])} mark-to-market "
             f"adjustment(s) as of {data['as_of'].isoformat()}"]
    table = Table(headers=["Account", "Book", "Market", "Adjustment"],
                  align="lrrr")
    for row in data["adjustments"]:
        table.add(row["account"], money(row["book"], decimals),
                  money(row["market"], decimals),
                  money(row["adjustment"], decimals))
    lines.append(table.render())
    return "\n".join(lines)
