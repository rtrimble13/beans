"""Financial statements: income statement, balance sheet, statement of
cash flows, trial balance, account register, and balance listings.

Each report builds a plain dict of data (amounts in integer minor units)
and has a renderer that turns it into aligned text. `jsonify` converts a
report dict to JSON-ready form with major-unit decimal strings.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from beans.ledger import Ledger
from beans.models import AccountType
from beans.render import Table, bold, money, rollup, strip_shared_root
from beans.utils import add_months, month_bounds, prior_period


def to_major(minor: int, decimals: int) -> str:
    return str(Decimal(minor).scaleb(-decimals).quantize(
        Decimal(1).scaleb(-decimals) if decimals else Decimal(1)))


# Report-dict keys whose integer values are counts, not money.
NON_MONEY_KEYS = {"id", "months", "horizon_months", "lookback_months",
                  "posted_count"}


def jsonify(value, decimals: int):
    """Convert a report dict for JSON output: every int is money in minor
    units and becomes a major-unit decimal string (except known counts)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return to_major(value, decimals)
    if isinstance(value, dict):
        return {
            k: v if k in NON_MONEY_KEYS and isinstance(v, (bool, int))
            else jsonify(v, decimals)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [jsonify(v, decimals) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _natural_by_name(led: Ledger, raw: dict[int, int],
                     type_: AccountType) -> dict[str, int]:
    """Map account name -> natural-sign amount for one account type."""
    out = {}
    for account in led.accounts(type_=type_, include_closed=True):
        amount = raw.get(account.id, 0)
        if amount:
            out[account.name] = amount * type_.natural_sign
    return out


def _tree_rows(table: Table, amounts: dict[str, int], decimals: int,
               indent: str = "  ", extra=None) -> None:
    tree = strip_shared_root(rollup(amounts), amounts)
    for name, depth, amount, is_leaf in tree:
        label = indent + "  " * depth + name
        if is_leaf:
            cols = [label, money(amount, decimals)]
            if extra:
                cols.append(extra(name, amount))
            table.add(*cols)
        else:
            table.add(label, "")


# -- income statement -------------------------------------------------------


def income_statement(led: Ledger, start: date | None, end: date,
                     label: str, compare: bool = False) -> dict:
    flows = led.flows(start, end)
    data = {
        "report": "income_statement",
        "period": label,
        "start": start,
        "end": end,
        "income": _natural_by_name(led, flows, AccountType.INCOME),
        "expenses": _natural_by_name(led, flows, AccountType.EXPENSE),
    }
    data["total_income"] = sum(data["income"].values())
    data["total_expenses"] = sum(data["expenses"].values())
    data["net_income"] = data["total_income"] - data["total_expenses"]
    if compare:
        p_start, p_end, p_label = prior_period(start, end)
        data["compare"] = income_statement(led, p_start, p_end, p_label)
    return data


def render_income_statement(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("INCOME STATEMENT"), f"For the period: {data['period']}", ""]
    total_income = data["total_income"]

    def pct(_name: str, amount: int) -> str:
        if not total_income:
            return ""
        return f"{100 * amount / total_income:5.1f}%"

    table = Table(align="lrr")
    table.add(bold("Income"), "", "")
    _tree_rows(table, data["income"], decimals, extra=pct)
    table.rule()
    table.add(bold("Total Income"),
              money(total_income, decimals, symbol), pct("", total_income))
    table.add("", "", "")
    table.add(bold("Expenses"), "", "")
    _tree_rows(table, data["expenses"], decimals, extra=pct)
    table.rule()
    table.add(bold("Total Expenses"),
              money(data["total_expenses"], decimals, symbol),
              pct("", data["total_expenses"]))
    table.rule()
    table.add(bold("Net Income"),
              money(data["net_income"], decimals, symbol),
              pct("", data["net_income"]))
    lines.append(table.render())

    if "compare" in data:
        prior = data["compare"]
        lines += ["", bold(f"Comparison with prior period ({prior['period']})")]
        cmp_table = Table(
            headers=["", "Current", "Prior", "Change"], align="lrrr"
        )
        for key, name in (("total_income", "Total Income"),
                          ("total_expenses", "Total Expenses"),
                          ("net_income", "Net Income")):
            cur, prev = data[key], prior[key]
            cmp_table.add(name, money(cur, decimals, symbol),
                          money(prev, decimals, symbol),
                          money(cur - prev, decimals, symbol))
        lines.append(cmp_table.render())
    return "\n".join(lines)


# -- balance sheet -----------------------------------------------------------


def balance_sheet(led: Ledger, as_of: date) -> dict:
    raw = led.balances(as_of=as_of)
    assets = _natural_by_name(led, raw, AccountType.ASSET)
    liabilities = _natural_by_name(led, raw, AccountType.LIABILITY)
    equity = _natural_by_name(led, raw, AccountType.EQUITY)
    # Retained earnings: cumulative net income never formally "closed" to
    # equity, computed on the fly as corporate systems do at close.
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    retained = -sum(
        amount for acct_id, amount in raw.items()
        if acct_id in accounts
        and accounts[acct_id].type in (AccountType.INCOME, AccountType.EXPENSE)
    )
    total_assets = sum(assets.values())
    total_liabilities = sum(liabilities.values())
    total_equity = sum(equity.values()) + retained
    return {
        "report": "balance_sheet",
        "as_of": as_of,
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "retained_earnings": retained,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "net_worth": total_assets - total_liabilities,
        "balanced": total_assets == total_liabilities + total_equity,
    }


def render_balance_sheet(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("BALANCE SHEET"), f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(align="lr")

    def block(title: str, amounts: dict[str, int], total: int) -> None:
        table.add(bold(title), "")
        _tree_rows(table, amounts, decimals)
        table.rule()
        table.add(bold(f"Total {title}"), money(total, decimals, symbol))
        table.add("", "")

    block("Assets", data["assets"], data["total_assets"])
    block("Liabilities", data["liabilities"], data["total_liabilities"])
    table.add(bold("Equity"), "")
    _tree_rows(table, data["equity"], decimals)
    table.add("  Retained Earnings",
              money(data["retained_earnings"], decimals))
    table.rule()
    table.add(bold("Total Equity"),
              money(data["total_equity"], decimals, symbol))
    table.rule()
    table.add(bold("Liabilities + Equity"),
              money(data["total_liabilities"] + data["total_equity"],
                    decimals, symbol))
    table.add(bold("Net Worth"),
              money(data["net_worth"], decimals, symbol))
    lines.append(table.render())
    if not data["balanced"]:
        lines.append("WARNING: balance sheet does not balance — "
                     "the ledger may be corrupted")
    return "\n".join(lines)


# -- statement of cash flows -------------------------------------------------


def cash_flow_statement(led: Ledger, start: date | None, end: date,
                        label: str) -> dict:
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    cash_ids = {a.id for a in accounts.values() if a.is_cash}
    sections: dict[str, dict[str, int]] = {
        "operating": {}, "investing": {}, "financing": {}
    }
    for txn in led.transactions(start=start, end=end):
        cash_delta = sum(
            p.amount for p in txn.postings if p.account_id in cash_ids
        )
        if cash_delta == 0:
            continue
        # The cash legs sum to the negation of the non-cash legs, so each
        # non-cash posting (negated) is that account's exact cash effect.
        for p in txn.postings:
            if p.account_id in cash_ids:
                continue
            account = accounts[p.account_id]
            bucket = sections[account.cashflow]
            bucket[account.name] = bucket.get(account.name, 0) - p.amount

    begin = (start - timedelta(days=1)) if start else None
    raw_begin = led.balances(as_of=begin) if begin else {}
    raw_end = led.balances(as_of=end)
    cash_begin = sum(raw_begin.get(i, 0) for i in cash_ids) if begin else 0
    cash_end = sum(raw_end.get(i, 0) for i in cash_ids)
    data = {
        "report": "cash_flow_statement",
        "period": label,
        "start": start,
        "end": end,
        "operating": sections["operating"],
        "investing": sections["investing"],
        "financing": sections["financing"],
        "net_operating": sum(sections["operating"].values()),
        "net_investing": sum(sections["investing"].values()),
        "net_financing": sum(sections["financing"].values()),
        "cash_beginning": cash_begin,
        "cash_ending": cash_end,
    }
    data["net_change"] = (data["net_operating"] + data["net_investing"]
                          + data["net_financing"])
    return data


def render_cash_flow_statement(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("STATEMENT OF CASH FLOWS"),
             f"For the period: {data['period']}", ""]
    table = Table(align="lr")
    for key, title in (("operating", "Operating Activities"),
                       ("investing", "Investing Activities"),
                       ("financing", "Financing Activities")):
        table.add(bold(f"Cash Flows from {title}"), "")
        amounts = data[key]
        for name in sorted(amounts, key=str.lower):
            table.add("  " + name, money(amounts[name], decimals))
        table.rule()
        table.add(bold(f"Net Cash from {title}"),
                  money(data[f"net_{key}"], decimals, symbol))
        table.add("", "")
    table.rule()
    table.add(bold("Net Change in Cash"),
              money(data["net_change"], decimals, symbol))
    table.add("Cash at Beginning of Period",
              money(data["cash_beginning"], decimals, symbol))
    table.add(bold("Cash at End of Period"),
              money(data["cash_ending"], decimals, symbol))
    lines.append(table.render())
    return "\n".join(lines)


# -- trial balance and balances ----------------------------------------------


def trial_balance(led: Ledger, as_of: date) -> dict:
    raw = led.balances(as_of=as_of)
    rows = []
    for account in led.accounts(include_closed=True):
        amount = raw.get(account.id, 0)
        if amount == 0:
            continue
        rows.append({
            "account": account.name,
            "debit": amount if amount > 0 else 0,
            "credit": -amount if amount < 0 else 0,
        })
    return {
        "report": "trial_balance",
        "as_of": as_of,
        "rows": rows,
        "total_debits": sum(r["debit"] for r in rows),
        "total_credits": sum(r["credit"] for r in rows),
    }


def render_trial_balance(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("TRIAL BALANCE"), f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(headers=["Account", "Debit", "Credit"], align="lrr")
    for row in data["rows"]:
        table.add(row["account"],
                  money(row["debit"], decimals) if row["debit"] else "",
                  money(row["credit"], decimals) if row["credit"] else "")
    table.rule()
    table.add(bold("Totals"),
              money(data["total_debits"], decimals, symbol),
              money(data["total_credits"], decimals, symbol))
    lines.append(table.render())
    if data["total_debits"] != data["total_credits"]:
        lines.append("WARNING: debits do not equal credits")
    return "\n".join(lines)


def balances_report(led: Ledger, as_of: date) -> dict:
    raw = led.balances(as_of=as_of)
    sections = {}
    for type_ in AccountType:
        amounts = _natural_by_name(led, raw, type_)
        if amounts:
            sections[type_.value] = amounts
    return {"report": "balances", "as_of": as_of, "sections": sections}


def render_balances(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("ACCOUNT BALANCES"),
             f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(align="lr")
    for type_ in AccountType:
        amounts = data["sections"].get(type_.value)
        if not amounts:
            continue
        table.add(bold(type_.label), "")
        _tree_rows(table, amounts, decimals)
        table.rule()
        table.add(bold(f"Total {type_.label}"),
                  money(sum(amounts.values()), decimals, symbol))
        table.add("", "")
    lines.append(table.render())
    return "\n".join(lines)


# -- net worth trend ---------------------------------------------------------


def net_worth_trend(led: Ledger, months: int, end: date | None = None) -> dict:
    """Month-end assets, liabilities, and net worth for the last `months`
    months — the household equivalent of a book-value trend.

    Computed from one grouped scan of the ledger (monthly deltas by
    account type) accumulated into running balances, instead of a full
    balances() aggregation per month."""
    end = end or date.today()
    deltas = led.monthly_type_totals(end)
    this_month_start = month_bounds(end.year, end.month)[0]
    first_shown = add_months(this_month_start, -(months - 1))

    assets = liabilities = 0
    # Seed running totals with everything before the displayed window.
    for ym in sorted(deltas):
        if ym >= f"{first_shown:%Y-%m}":
            break
        assets += deltas[ym].get("asset", 0)
        liabilities -= deltas[ym].get("liability", 0)

    rows = []
    prev_net = None
    for i in range(months):
        m_start = add_months(first_shown, i)
        ym = f"{m_start:%Y-%m}"
        assets += deltas.get(ym, {}).get("asset", 0)
        liabilities -= deltas.get(ym, {}).get("liability", 0)
        net = assets - liabilities
        rows.append({
            "month": ym,
            "as_of": min(month_bounds(m_start.year, m_start.month)[1], end),
            "assets": assets,
            "liabilities": liabilities,
            "net_worth": net,
            "change": (net - prev_net) if prev_net is not None else 0,
        })
        prev_net = net
    return {"report": "net_worth_trend", "months": months, "rows": rows}


def render_net_worth_trend(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("NET WORTH TREND"),
             f"Last {data['months']} months (month-end balances)", ""]
    table = Table(headers=["Month", "Assets", "Liabilities", "Net Worth",
                           "Change"], align="lrrrr")
    for row in data["rows"]:
        table.add(row["month"],
                  money(row["assets"], decimals),
                  money(row["liabilities"], decimals),
                  money(row["net_worth"], decimals),
                  money(row["change"], decimals))
    lines.append(table.render())
    if data["rows"]:
        first, last = data["rows"][0], data["rows"][-1]
        total_change = last["net_worth"] - first["net_worth"]
        lines.append("")
        lines.append(f"Change over period: "
                     f"{money(total_change, decimals, symbol)}")
    return "\n".join(lines)


# -- register ----------------------------------------------------------------


def register(led: Ledger, account, start: date | None, end: date) -> dict:
    opening = 0
    if start:
        prior = led.flows(None, start - timedelta(days=1))
        opening = prior.get(account.id, 0)
    rows = []
    running = opening
    for txn in led.transactions(start=start, end=end, account=account):
        delta = sum(
            p.amount for p in txn.postings if p.account_id == account.id
        )
        running += delta
        others = [p.account_name for p in txn.postings
                  if p.account_id != account.id]
        mine = [p for p in txn.postings if p.account_id == account.id]
        rows.append({
            "id": txn.id,
            "date": txn.date,
            "description": txn.description or txn.payee,
            "counter": ", ".join(others),
            "amount": delta * account.type.natural_sign,
            "balance": running * account.type.natural_sign,
            "cleared": all(p.cleared for p in mine),
        })
    return {
        "report": "register",
        "account": account.name,
        "opening_balance": opening * account.type.natural_sign,
        "rows": rows,
    }


def render_register(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold(f"REGISTER — {data['account']}"), ""]
    table = Table(headers=["ID", "Date", "C", "Description",
                           "Counter-account", "Amount", "Balance"],
                  align="rllllrr")
    for row in data["rows"]:
        table.add(row["id"], row["date"].isoformat(),
                  "*" if row["cleared"] else "",
                  row["description"][:40], row["counter"][:40],
                  money(row["amount"], decimals),
                  money(row["balance"], decimals))
    lines.append(table.render())
    if not data["rows"]:
        lines.append("(no transactions in period)")
    return "\n".join(lines)
