"""The `beans status` dashboard: a one-screen summary of where things
stand — cash, net worth, the current month vs. budget, due recurring
rules, and goal progress. Also what bare `beans` shows once a ledger
exists."""

from __future__ import annotations

from datetime import date, timedelta

from beans import recurring
from beans.budget import budget_accounts
from beans.goals import goals_report
from beans.ledger import Ledger
from beans.models import AccountType
from beans.render import Table, bold, green, money, red
from beans.utils import month_bounds


def status_report(led: Ledger, today: date | None = None) -> dict:
    today = today or date.today()
    raw = led.balances(as_of=today)
    position = led.position(raw=raw)
    position_30d = led.position(as_of=today - timedelta(days=30))

    month_start, _month_end = month_bounds(today.year, today.month)
    flows = led.flows(month_start, today)
    flow_totals = led.type_totals(flows)
    income = flow_totals[AccountType.INCOME]
    expenses = flow_totals[AccountType.EXPENSE]

    monthly_budgets = budget_accounts(led)
    budget_total = budget_used = 0
    over_budget = []
    for account, _amount, _period in led.budgets():
        if account.type is not AccountType.EXPENSE:
            continue
        monthly = monthly_budgets[account.id]
        actual = flows.get(account.id, 0) * account.type.natural_sign
        budget_total += monthly
        budget_used += actual
        if actual > monthly:
            over_budget.append(account.leaf)

    goal_rows = goals_report(led, as_of=today, raw=raw)["rows"]

    return {
        "report": "status",
        "as_of": today,
        "cash": position["cash"],
        "net_worth": position["net_worth"],
        "net_worth_change_30d": (position["net_worth"]
                                 - position_30d["net_worth"]),
        "month": f"{today:%B %Y}",
        "month_income": income,
        "month_expenses": expenses,
        "month_net": income - expenses,
        "budget_total": budget_total,
        "budget_used": budget_used,
        "over_budget": over_budget,
        "due_recurring": recurring.due_names(led, today),
        "goals": [
            {"name": g["name"], "progress_pct": g["progress_pct"],
             "remaining": g["remaining"],
             "required_monthly": g["required_monthly"]}
            for g in goal_rows
        ],
        "closed_through": led.closed_through,
    }


def render_status(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold(f"BEANS STATUS — {data['as_of'].isoformat()}"), ""]
    table = Table(align="lr")
    change = data["net_worth_change_30d"]
    arrow = "+" if change >= 0 else ""
    table.add("Cash & equivalents", money(data["cash"], decimals, symbol))
    table.add("Net worth",
              f"{money(data['net_worth'], decimals, symbol)}  "
              f"({arrow}{money(change, decimals, symbol, color_negative=False)}"
              " over 30 days)")
    table.add("", "")
    table.add(bold(f"This month ({data['month']})"), "")
    table.add("  Income", money(data["month_income"], decimals, symbol))
    table.add("  Expenses", money(data["month_expenses"], decimals, symbol))
    table.add("  Net", money(data["month_net"], decimals, symbol))
    if data["budget_total"]:
        pct = 100 * data["budget_used"] / data["budget_total"]
        pct_text = f"{pct:.0f}%"
        table.add("  Budget used",
                  f"{red(pct_text) if pct > 100 else green(pct_text)} of "
                  f"{money(data['budget_total'], decimals, symbol)}")
        if data["over_budget"]:
            table.add("  Over budget", red(", ".join(data["over_budget"])))
    lines.append(table.render())

    if data["due_recurring"]:
        lines.append("")
        lines.append(bold(f"{len(data['due_recurring'])} recurring rule(s) "
                          f"due ({', '.join(data['due_recurring'][:4])}) — "
                          "run `beans recur run`"))
    if data["goals"]:
        lines.append("")
        lines.append(bold("Goals"))
        for g in data["goals"]:
            if g["progress_pct"] is not None:
                lines.append(f"  {g['name']}: {g['progress_pct']:.0f}% "
                             f"({money(g['remaining'], decimals, symbol)} "
                             "to go)")
            else:
                lines.append(f"  {g['name']}: "
                             f"{money(g['remaining'], decimals, symbol)} "
                             "remaining")
    if data["closed_through"]:
        lines.append("")
        lines.append(f"Books closed through "
                     f"{data['closed_through'].isoformat()}")
    return "\n".join(lines)
