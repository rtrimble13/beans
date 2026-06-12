"""Multi-currency support: exchange rates and FX revaluation.

beans keeps its books in one base currency (the "functional currency",
as a company would). Asset and liability accounts may be denominated in
a foreign currency: their postings carry both the base amount — so every
transaction still balances to zero in base — and the foreign amount,
tracked in parallel.

`beans currency revalue` is the FX twin of `beans invest mark`: it posts
an adjustment so each foreign account's base balance equals its foreign
balance at the latest rate, against Income:FX Gains. Statements stay in
base currency throughout.
"""

from __future__ import annotations

from datetime import date

from beans.ledger import Ledger
from beans.models import AccountType, Posting
from beans.render import Table, bold, money
from beans.utils import (
    BeansError,
    base_from_foreign,
    currency_decimals,
    currency_symbol,
    format_amount,
)

FX_ACCOUNT = "Income:FX Gains"


def _fx_income_account(led: Ledger):
    try:
        return led.find_account(FX_ACCOUNT)
    except BeansError:
        return led.add_account(FX_ACCOUNT, AccountType.INCOME,
                               description="created by beans currency")


def currencies_report(led: Ledger, as_of: date | None = None) -> dict:
    """Foreign accounts with their foreign balance, latest rate, and the
    base value implied by that rate vs. the booked base balance."""
    as_of = as_of or date.today()
    raw = led.balances(as_of=as_of)
    foreign = led.foreign_balances(as_of=as_of)
    rows = []
    for account in led.accounts(include_closed=True):
        if not account.currency:
            continue
        f_bal = foreign.get(account.id, 0)
        book = raw.get(account.id, 0)
        latest = led.latest_fx_rate(account.currency, as_of=as_of)
        market = (base_from_foreign(f_bal, latest[1], led.decimals,
                                    currency_decimals(account.currency))
                  if latest else None)
        rows.append({
            "account": account.name,
            "currency": account.currency,
            "foreign_balance": f_bal,
            "book": book,
            "rate": str(latest[1]) if latest else None,
            "rate_date": latest[0] if latest else None,
            "market": market,
            "unrealized": (market - book) if market is not None else None,
        })
    return {"report": "currencies", "as_of": as_of, "rows": rows,
            "base_currency": led.currency}


def render_currencies(data: dict, decimals: int, symbol: str) -> str:
    if not data["rows"]:
        return ("No foreign-currency accounts. Add one with: beans account "
                "add NAME --type asset --currency EUR (and set rates with "
                "`beans currency set EUR RATE`)")
    lines = [bold("FOREIGN CURRENCY ACCOUNTS"),
             f"As of: {data['as_of'].isoformat()} | "
             f"Base currency: {data['base_currency']}", ""]
    table = Table(headers=["Account", "Balance", "Rate", "Base Value",
                           "Booked", "Unrealized"], align="lrrrrr")
    for row in data["rows"]:
        fd = currency_decimals(row["currency"])
        table.add(row["account"],
                  format_amount(row["foreign_balance"], fd,
                                currency_symbol(row["currency"])),
                  row["rate"] or "?",
                  money(row["market"], decimals)
                  if row["market"] is not None else "?",
                  money(row["book"], decimals),
                  money(row["unrealized"], decimals)
                  if row["unrealized"] is not None else "?")
    lines.append(table.render())
    if any(r["rate"] is None for r in data["rows"]):
        lines.append("")
        lines.append("Some currencies have no rate — set one with "
                     "`beans currency set CODE RATE`.")
    return "\n".join(lines)


def revalue(led: Ledger, when: date, dry_run: bool = False) -> dict:
    """Post adjustments so each foreign account's base balance equals its
    foreign balance at the latest rate, against Income:FX Gains."""
    data = currencies_report(led, as_of=when)
    fx_income = _fx_income_account(led)
    adjustments = []
    for row in data["rows"]:
        if row["market"] is None:
            raise BeansError(
                f"no exchange rate for {row['currency']} — set one with "
                f"`beans currency set {row['currency']} RATE` before "
                "revaluing"
            )
        delta = row["market"] - row["book"]
        if delta == 0:
            continue
        account = led.find_account(row["account"])
        txn_id = None
        if not dry_run:
            txn = led.add_transaction(
                when,
                f"FX revaluation: {account.name}",
                # foreign_amount=0: revaluation changes the base value
                # only, never the foreign balance.
                [Posting(account_id=account.id, amount=delta,
                         foreign_amount=0),
                 Posting(account_id=fx_income.id, amount=-delta)],
                tags=["fx"],
            )
            txn_id = txn.id
        adjustments.append({
            "id": txn_id,
            "account": account.name,
            "currency": row["currency"],
            "book": row["book"],
            "market": row["market"],
            "adjustment": delta,
        })
    return {
        "report": "fx_revaluation",
        "as_of": when,
        "dry_run": dry_run,
        "adjustments": adjustments,
    }


def render_revalue(data: dict, decimals: int, symbol: str) -> str:
    verb = "Would post" if data["dry_run"] else "Posted"
    if not data["adjustments"]:
        return ("All foreign accounts already carry the current rate — "
                "nothing to adjust.")
    lines = [f"{verb} {len(data['adjustments'])} FX revaluation(s) "
             f"as of {data['as_of'].isoformat()}"]
    table = Table(headers=["Account", "Booked", "At Rate", "Adjustment"],
                  align="lrrr")
    for row in data["adjustments"]:
        table.add(row["account"], money(row["book"], decimals),
                  money(row["market"], decimals),
                  money(row["adjustment"], decimals))
    lines.append(table.render())
    return "\n".join(lines)
