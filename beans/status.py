"""The `beans status` dashboard: a one-screen summary of where things
stand — cash, net worth, the current month vs. budget, due recurring
rules, and goal progress. Also what bare `beans` shows once a ledger
exists."""

from __future__ import annotations

from datetime import date, timedelta

from beans import recurring
from beans.goals import goals_report
from beans.ledger import BUDGET_PERIOD_MONTHS, Ledger
from beans.models import AccountType
from beans.render import Table, bold, green, money, red
from beans.utils import month_bounds


def status_report(led: Ledger, today: date | None = None) -> dict:
    today = today or date.today()
    raw = led.balances(as_of=today)
    raw_30d = led.balances(as_of=today - timedelta(days=30))
    accounts = {a.id: a for a in led.accounts(include_closed=True)}

    def totals(balances: dict[int, int]) -> tuple[int, int, int]:
        assets = sum(v for k, v in balances.items()
                     if k in accounts
                     and accounts[k].type is AccountType.ASSET)
        liabilities = -sum(v for k, v in balances.items()
                           if k in accounts
                           and accounts[k].type is AccountType.LIABILITY)
        cash = sum(v for k, v in balances.items()
                   if k in accounts and accounts[k].is_cash)
        return assets, liabilities, cash

    assets, liabilities, cash = totals(raw)
    assets_30d, liabilities_30d, _ = totals(raw_30d)
    net_worth = assets - liabilities

    month_start, month_end = month_bounds(today.year, today.month)
    flows = led.flows(month_start, today)
    income = sum(v * AccountType.INCOME.natural_sign
                 for k, v in flows.items()
                 if k in accounts
                 and accounts[k].type is AccountType.INCOME)
    expenses = sum(v * AccountType.EXPENSE.natural_sign
                   for k, v in flows.items()
                   if k in accounts
                   and accounts[k].type is AccountType.EXPENSE)

    budget_total = budget_used = 0
    over_budget = []
    for account, amount, period in led.budgets():
        if account.type is not AccountType.EXPENSE:
            continue
        monthly = round(amount / BUDGET_PERIOD_MONTHS[period])
        actual = flows.get(account.id, 0) * account.type.natural_sign
        budget_total += monthly
        budget_used += actual
        if actual > monthly:
            over_budget.append(account.leaf)

    due_rules = [
        row["name"]
        for row in recurring.list_rules(led, today)["rules"]
        if row["status"] == "due"
    ]

    goal_rows = goals_report(led, as_of=today)["rows"]

    return {
        "report": "status",
        "as_of": today,
        "cash": cash,
        "net_worth": net_worth,
        "net_worth_change_30d": net_worth - (assets_30d - liabilities_30d),
        "month": f"{today:%B %Y}",
        "month_income": income,
        "month_expenses": expenses,
        "month_net": income - expenses,
        "budget_total": budget_total,
        "budget_used": budget_used,
        "over_budget": over_budget,
        "due_recurring": due_rules,
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
