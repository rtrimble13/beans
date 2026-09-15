"""Forecasting: project income, expenses, cash, and net worth forward.

Two projection methods over per-account monthly history:
  average — mean monthly flow over the lookback window
  trend   — least-squares linear trend extrapolated forward

With --use-budget, accounts that have budgets use the budgeted monthly
amount instead of history, letting plans drive the projection. With
--use-recurring, scheduled transactions are projected at their exact
amounts and dates.

The projection itself lives in `proforma.py`, which builds balanced
transactions rather than totals. This module reads them two ways: as the
month-by-month summary `beans forecast` has always printed, and — via
`forecast_statement` — as a projected balance sheet, income statement or
statement of cash flows, built by the same `reports.py` code that renders
the historical ones.
"""

from __future__ import annotations

from beans import proforma, reports
from beans.ledger import Ledger
from beans.models import AccountType
from beans.proforma import ProForma
from beans.render import Table, bold, money, red
from beans.utils import BeansError

# `--report` values, and the statement each one builds. The tokens are the
# ones `beans report` already takes, so `forecast --report bs` and
# `report bs` read alike.
STATEMENT_KINDS = {
    "income": "is", "is": "is",
    "balance": "bs", "bs": "bs",
    "cashflow": "cf", "cf": "cf",
}
REPORT_CHOICES = ["summary", *STATEMENT_KINDS, "all"]
STATEMENT_ORDER = ("is", "bs", "cf")


def _basis(pf: ProForma) -> str:
    parts = []
    if pf.use_recurring:
        parts.append("recurring schedule")
    if pf.use_budget:
        parts.append("budgets")
    parts.append(f"{pf.lookback_months}-month history ({pf.method})")
    return " > ".join(parts)


def _month_buckets(pf: ProForma, accounts: dict) -> dict[str, dict[str, int]]:
    """Projected flows per calendar month: income and expenses in natural
    signs, and the raw deltas to cash and to net worth. Rolling these
    forward is what makes `Proj. Cash` a real cash figure rather than an
    assumption that every dollar of net income stays in the bank."""
    out: dict[str, dict[str, int]] = {}
    for txn in pf.txns:
        bucket = out.setdefault(f"{txn.date:%Y-%m}",
                                {"income": 0, "expenses": 0,
                                 "cash": 0, "net_worth": 0})
        for p in txn.postings:
            account = accounts[p.account_id]
            if account.type is AccountType.INCOME:
                bucket["income"] -= p.amount
            elif account.type is AccountType.EXPENSE:
                bucket["expenses"] += p.amount
            elif account.type in (AccountType.ASSET, AccountType.LIABILITY):
                # Net worth is assets minus liabilities; in raw
                # debit-positive terms that is the sum of both.
                bucket["net_worth"] += p.amount
                if account.is_cash:
                    bucket["cash"] += p.amount
    return out


def forecast(led: Ledger, months: int = 6, method: str = "average",
             lookback: int = 6, use_budget: bool = False,
             use_recurring: bool = False) -> dict:
    pf = proforma.project(led, months=months, method=method,
                          lookback=lookback, use_budget=use_budget,
                          use_recurring=use_recurring)
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    buckets = _month_buckets(pf, accounts)
    empty = {"income": 0, "expenses": 0, "cash": 0, "net_worth": 0}

    position = led.position(as_of=pf.base_date)
    cash_now, net_worth_now = position["cash"], position["net_worth"]
    # The part-elapsed current month is projected too, but it is not a
    # month: it lands in the opening position, never in a monthly row.
    stub = buckets.get(f"{pf.base_date:%Y-%m}", empty)
    cash = cash_now + stub["cash"]
    net_worth = net_worth_now + stub["net_worth"]

    rows, cumulative = [], 0
    for key in pf.future_keys:
        bucket = buckets.get(key, empty)
        cash += bucket["cash"]
        net_worth += bucket["net_worth"]
        net = bucket["income"] - bucket["expenses"]
        cumulative += net
        rows.append({"month": key, "income": bucket["income"],
                     "expenses": bucket["expenses"], "net": net,
                     "projected_cash": cash,
                     "projected_net_worth": net_worth})

    # Per-account detail (the projection's drivers) for the summary.
    horizon = set(pf.future_keys)
    totals: dict[int, int] = {}
    for txn in pf.txns:
        if f"{txn.date:%Y-%m}" not in horizon:
            continue
        for p in txn.postings:
            account = accounts[p.account_id]
            if account.type in proforma.FLOW_TYPES:
                totals[account.id] = totals.get(account.id, 0) \
                    + p.amount * account.type.natural_sign
    detail = []
    for driver in pf.drivers:
        total = totals.get(driver.account.id, 0)
        if total:
            detail.append({
                "account": driver.account.name,
                "type": driver.account.type.value,
                "monthly_avg": round(total / months),
                "total": total,
                "source": driver.source,
            })
    detail.sort(key=lambda d: (d["type"], -abs(d["total"])))

    return {
        "report": "forecast",
        "method": method,
        "lookback_months": pf.lookback_months,
        "lookback_requested": pf.lookback_requested,
        "history_begins": pf.history_begins,
        "horizon_months": months,
        "use_budget": use_budget,
        "use_recurring": use_recurring,
        "current_cash": cash_now,
        "current_net_worth": net_worth_now,
        "months": rows,
        "accounts": detail,
        "total_projected_net": cumulative,
        "stub_income": stub["income"],
        "stub_expenses": stub["expenses"],
        "warnings": pf.warnings,
    }


def render_forecast(data: dict, decimals: int, symbol: str) -> str:
    parts = []
    if data.get("use_recurring"):
        parts.append("recurring schedule")
    if data["use_budget"]:
        parts.append("budgets")
    parts.append(f"{data['lookback_months']}-month history "
                 f"({data['method']})")
    src = " > ".join(parts)
    lines = [
        bold("FORECAST"),
        f"Horizon: {data['horizon_months']} months | Basis: {src}",
    ]
    # Say when the basis is thinner than asked for. A projection off two
    # months of history is a different object from one off twelve, and the
    # table alone cannot tell them apart.
    for warning in data.get("warnings", []):
        lines.append(red(warning) if not data["lookback_months"] else warning)
    lines.append("")
    table = Table(headers=["Month", "Income", "Expenses", "Net",
                           "Proj. Cash", "Proj. Net Worth"],
                  align="lrrrrr")
    for row in data["months"]:
        table.add(row["month"],
                  money(row["income"], decimals),
                  money(row["expenses"], decimals),
                  money(row["net"], decimals),
                  money(row["projected_cash"], decimals),
                  money(row["projected_net_worth"], decimals))
    table.rule()
    table.add(bold("Total"), "", "",
              money(data["total_projected_net"], decimals, symbol), "", "")
    lines.append(table.render())

    lines += ["", bold("Projection drivers (monthly)")]
    drivers = Table(headers=["Account", "Type", "Monthly", "Basis"],
                    align="llrl")
    for d in data["accounts"]:
        drivers.add(d["account"], d["type"],
                    money(d["monthly_avg"], decimals), d["source"])
    lines.append(drivers.render())
    if not data["accounts"]:
        lines.append("(no income/expense history or budgets to project from)")
    return "\n".join(lines)


# -- projected financial statements ------------------------------------------


def _market_caveat(led: Ledger) -> str | None:
    """A forecast projects the household's own behaviour, not the market's.
    Say so wherever there is something to mark."""
    has_lots = bool(led.lots())
    has_foreign = any(a.currency for a in led.accounts(include_closed=True))
    if not (has_lots or has_foreign):
        return None
    what = []
    if has_lots:
        what.append("investments are carried at their last mark plus "
                    "projected contributions (no market return)")
    if has_foreign:
        what.append("foreign balances at the last known rate (no FX "
                    "revaluation)")
    return "Assumptions: " + "; ".join(what) + "."


def forecast_statement(led: Ledger, kind: str, months: int = 6,
                       method: str = "average", lookback: int = 6,
                       use_budget: bool = False, use_recurring: bool = False,
                       classified: bool = True,
                       pf: ProForma | None = None) -> dict:
    """A projected income statement, balance sheet or statement of cash
    flows, built by the ordinary `reports.py` builders over a pro-forma
    ledger. Pass `pf` to reuse one projection across several statements."""
    kind = STATEMENT_KINDS.get(kind, kind)
    if kind not in STATEMENT_ORDER:
        raise BeansError(f"unknown statement: {kind!r}")
    if pf is None:
        pf = proforma.project(led, months=months, method=method,
                              lookback=lookback, use_budget=use_budget,
                              use_recurring=use_recurring)
    label = (f"{pf.window_start.isoformat()} to "
             f"{pf.window_end.isoformat()} (projected)")
    if kind == "is":
        data = reports.income_statement(pf, pf.window_start, pf.window_end,
                                        label)
        data["title"] = "PROJECTED INCOME STATEMENT"
    elif kind == "bs":
        data = reports.balance_sheet(pf, pf.window_end, classified=classified)
        data["title"] = "PROJECTED BALANCE SHEET"
    else:
        data = reports.cash_flow_statement(pf, pf.window_start,
                                           pf.window_end, label)
        data["title"] = "PROJECTED STATEMENT OF CASH FLOWS"

    notes = [f"Horizon: {pf.horizon_months} months from "
             f"{pf.base_date.isoformat()} | Basis: {_basis(pf)}"]
    notes += list(pf.warnings)
    caveat = _market_caveat(led)
    if caveat:
        notes.append(caveat)
    data["notes"] = notes
    data["forecast"] = {
        "projected": True,
        "statement": kind,
        "basis": _basis(pf),
        "method": pf.method,
        "horizon_months": pf.horizon_months,
        "lookback_months": pf.lookback_months,
        "lookback_requested": pf.lookback_requested,
        "use_budget": pf.use_budget,
        "use_recurring": pf.use_recurring,
        "base_date": pf.base_date,
        "window_start": pf.window_start,
        "window_end": pf.window_end,
        "warnings": list(pf.warnings),
    }
    return data


RENDERERS = {
    "income_statement": reports.render_income_statement,
    "balance_sheet": reports.render_balance_sheet,
    "cash_flow_statement": reports.render_cash_flow_statement,
}


def render_forecast_statement(data: dict, decimals: int, symbol: str) -> str:
    return RENDERERS[data["report"]](data, decimals, symbol)


def forecast_statements(led: Ledger, months: int = 6,
                        method: str = "average", lookback: int = 6,
                        use_budget: bool = False, use_recurring: bool = False,
                        classified: bool = True) -> dict:
    """All three statements off one projection."""
    pf = proforma.project(led, months=months, method=method,
                          lookback=lookback, use_budget=use_budget,
                          use_recurring=use_recurring)
    return {
        "report": "forecast_statements",
        "horizon_months": months,
        "statements": [
            forecast_statement(led, kind, classified=classified, pf=pf)
            for kind in STATEMENT_ORDER
        ],
    }


def render_forecast_statements(data: dict, decimals: int, symbol: str) -> str:
    return "\n\n".join(
        render_forecast_statement(s, decimals, symbol)
        for s in data["statements"])
