"""Forecasting: project income, expenses, cash, and net worth forward.

Two projection methods over per-account monthly history:
  average — mean monthly flow over the lookback window
  trend   — least-squares linear trend extrapolated forward

With --use-budget, accounts that have budgets use the budgeted monthly
amount instead of history, letting plans drive the projection.
"""

from __future__ import annotations

from datetime import date, timedelta

from beans.budget import budget_accounts
from beans.ledger import Ledger
from beans.models import AccountType
from beans.recurring import pending_occurrences
from beans.render import Table, bold, money
from beans.utils import add_months, month_bounds


def _month_keys(start: date, count: int) -> list[str]:
    return [f"{add_months(start, i):%Y-%m}" for i in range(count)]


def _project(history: list[int], method: str, steps: int) -> list[int]:
    if not history:
        return [0] * steps
    if method == "average" or len(history) < 2:
        avg = round(sum(history) / len(history))
        return [avg] * steps
    # Least-squares fit of flow against month index, extrapolated. The
    # fitted line is y = mean_y + slope * (x - mean_x); future month x is
    # (n - 1 + step), so the offset from the mean must subtract mean_x.
    n = len(history)
    xs = range(n)
    mean_x = (n - 1) / 2
    mean_y = sum(history) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y)
                for x, y in zip(xs, history)) / denom
    return [round(mean_y + slope * (n - 1 + step - mean_x))
            for step in range(1, steps + 1)]


def _recurring_projections(
    led: Ledger, future_keys: list[str], horizon_end: date,
) -> dict[int, list[int]]:
    """Per-account monthly amounts from active recurring rules over the
    horizon. Accounts covered here are projected from their schedule
    exactly, instead of from history or budgets."""
    key_index = {key: i for i, key in enumerate(future_keys)}
    out: dict[int, list[int]] = {}
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    for rec in led.recurrings():
        if not rec.active:
            continue
        # pending_occurrences carries the MAX_RUN_PER_RULE runaway guard.
        for due in pending_occurrences(rec, horizon_end):
            idx = key_index.get(f"{due:%Y-%m}")
            if idx is None:
                continue
            for p in rec.postings:
                account = accounts.get(p.account_id)
                if account and account.type in (AccountType.INCOME,
                                                AccountType.EXPENSE):
                    series = out.setdefault(
                        account.id, [0] * len(future_keys))
                    series[idx] += p.amount * account.type.natural_sign
    return out


def forecast(led: Ledger, months: int = 6, method: str = "average",
             lookback: int = 6, use_budget: bool = False,
             use_recurring: bool = False) -> dict:
    if method not in ("average", "trend"):
        raise ValueError(f"unknown forecast method: {method}")
    today = date.today()
    accounts = [a for a in led.accounts()
                if a.type in (AccountType.INCOME, AccountType.EXPENSE)]
    # History from the last `lookback` complete months.
    this_month_start = month_bounds(today.year, today.month)[0]
    hist_start = add_months(this_month_start, -lookback)
    hist_end = this_month_start - timedelta(days=1)
    hist_keys = _month_keys(hist_start, lookback)
    flows = led.monthly_flows([a.id for a in accounts], hist_start, hist_end)
    budgets = budget_accounts(led) if use_budget else {}

    future_keys = _month_keys(this_month_start, months + 1)[1:]
    horizon_end = add_months(this_month_start, months + 1) - timedelta(days=1)
    recurring = (_recurring_projections(led, future_keys, horizon_end)
                 if use_recurring else {})

    # Source priority per account: recurring schedule > budget > history.
    projections: dict[int, list[int]] = {}
    for account in accounts:
        if account.id in recurring:
            projections[account.id] = recurring[account.id]
            continue
        if account.id in budgets:
            projections[account.id] = [budgets[account.id]] * months
            continue
        history = [
            flows.get((account.id, key), 0) * account.type.natural_sign
            for key in hist_keys
        ]
        projections[account.id] = _project(history, method, months)
    by_type: dict[str, list[int]] = {"income": [], "expense": []}
    rows = []
    for i, key in enumerate(future_keys):
        income = sum(projections[a.id][i] for a in accounts
                     if a.type is AccountType.INCOME)
        expenses = sum(projections[a.id][i] for a in accounts
                       if a.type is AccountType.EXPENSE)
        by_type["income"].append(income)
        by_type["expense"].append(expenses)
        rows.append({"month": key, "income": income, "expenses": expenses,
                     "net": income - expenses})

    position = led.position(as_of=today)
    cash_now = position["cash"]
    net_worth_now = position["net_worth"]

    cumulative = 0
    for row in rows:
        cumulative += row["net"]
        row["projected_cash"] = cash_now + cumulative
        row["projected_net_worth"] = net_worth_now + cumulative

    # Per-account detail (top expense drivers) for the summary.
    detail = []
    for account in accounts:
        total = sum(projections[account.id])
        if total:
            if account.id in recurring:
                source = "recurring"
            elif account.id in budgets:
                source = "budget"
            else:
                source = method
            detail.append({
                "account": account.name,
                "type": account.type.value,
                "monthly_avg": round(total / months),
                "total": total,
                "source": source,
            })
    detail.sort(key=lambda d: (d["type"], -abs(d["total"])))

    return {
        "report": "forecast",
        "method": method,
        "lookback_months": lookback,
        "horizon_months": months,
        "use_budget": use_budget,
        "use_recurring": use_recurring,
        "current_cash": cash_now,
        "current_net_worth": net_worth_now,
        "months": rows,
        "accounts": detail,
        "total_projected_net": cumulative,
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
        "",
    ]
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
