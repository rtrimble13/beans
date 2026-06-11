"""Budget vs. actual reporting.

Budgets are stored per income/expense account with a cadence (weekly,
monthly, quarterly, yearly). Reports normalize each budget to the length
of the requested period, so a $600/month grocery budget shows as $1,800
for a quarter and is pro-rated for partial periods.
"""

from __future__ import annotations

from datetime import date

from beans.ledger import BUDGET_PERIOD_MONTHS, Ledger
from beans.models import AccountType
from beans.render import Table, bold, green, money, red
from beans.utils import months_in_range


def budget_report(led: Ledger, start: date, end: date, label: str) -> dict:
    months = months_in_range(start, end)
    flows = led.flows(start, end)
    rows = []
    for account, amount, period in led.budgets():
        monthly = amount / BUDGET_PERIOD_MONTHS[period]
        budgeted = round(monthly * months)
        actual = flows.get(account.id, 0) * account.type.natural_sign
        rows.append({
            "account": account.name,
            "type": account.type.value,
            "period": period,
            "budget": budgeted,
            "actual": actual,
            # For expenses, positive remaining means money left to spend;
            # for income, positive remaining means a shortfall vs. target.
            "remaining": budgeted - actual,
            "pct_used": (100 * actual / budgeted) if budgeted else None,
        })
    expense_rows = [r for r in rows if r["type"] == "expense"]
    income_rows = [r for r in rows if r["type"] == "income"]
    return {
        "report": "budget",
        "period": label,
        "start": start,
        "end": end,
        "months": round(months, 2),
        "rows": rows,
        "total_expense_budget": sum(r["budget"] for r in expense_rows),
        "total_expense_actual": sum(r["actual"] for r in expense_rows),
        "total_income_budget": sum(r["budget"] for r in income_rows),
        "total_income_actual": sum(r["actual"] for r in income_rows),
    }


def render_budget_report(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("BUDGET REPORT"), f"For the period: {data['period']}", ""]
    if not data["rows"]:
        lines.append("No budgets set. Add one with: "
                     "beans budget set <account> <amount> --period monthly")
        return "\n".join(lines)

    table = Table(headers=["Account", "Budget", "Actual", "Remaining",
                           "Used"], align="lrrrr")
    for kind, rows in (("expense", [r for r in data["rows"]
                                    if r["type"] == "expense"]),
                       ("income", [r for r in data["rows"]
                                   if r["type"] == "income"])):
        if not rows:
            continue
        table.add(bold("Expenses" if kind == "expense" else "Income"),
                  "", "", "", "")
        for r in rows:
            pct = f"{r['pct_used']:.0f}%" if r["pct_used"] is not None else ""
            if kind == "expense" and r["pct_used"] is not None:
                pct = red(pct) if r["pct_used"] > 100 else green(pct)
            table.add("  " + r["account"],
                      money(r["budget"], decimals),
                      money(r["actual"], decimals),
                      money(r["remaining"], decimals),
                      pct)
        table.rule()
        prefix = "expense" if kind == "expense" else "income"
        budget = data[f"total_{prefix}_budget"]
        actual = data[f"total_{prefix}_actual"]
        pct = f"{100 * actual / budget:.0f}%" if budget else ""
        table.add(bold("Total"),
                  money(budget, decimals, symbol),
                  money(actual, decimals, symbol),
                  money(budget - actual, decimals, symbol),
                  pct)
        table.add("", "", "", "", "")
    lines.append(table.render())
    return "\n".join(lines)


def budget_accounts(led: Ledger) -> dict[int, int]:
    """Map of account id -> normalized monthly budget in minor units."""
    return {
        account.id: round(amount / BUDGET_PERIOD_MONTHS[period])
        for account, amount, period in led.budgets()
        if account.type in (AccountType.INCOME, AccountType.EXPENSE)
    }
