"""Financial analysis: the ratios an analyst would compute for a company,
adapted to a household — savings rate, liquidity runway, leverage,
debt-to-income, and expense composition."""

from __future__ import annotations

from datetime import date

from beans.ledger import Ledger
from beans.models import AccountType
from beans.render import Table, bold, money
from beans.utils import months_in_range


def analyze(led: Ledger, start: date | None, end: date, label: str) -> dict:
    flows = led.flows(start, end)
    accounts = {a.id: a for a in led.accounts(include_closed=True)}

    flow_totals = led.type_totals(flows)
    income = flow_totals[AccountType.INCOME]
    expenses = flow_totals[AccountType.EXPENSE]
    net = income - expenses

    position = led.position(as_of=end)
    assets = position["assets"]
    liabilities = position["liabilities"]
    cash = position["cash"]

    months = months_in_range(start, end) if start else None
    monthly_expenses = expenses / months if months else None
    monthly_income = income / months if months else None

    top_expenses = sorted(
        (
            (accounts[k].name, v * AccountType.EXPENSE.natural_sign)
            for k, v in flows.items()
            if k in accounts and accounts[k].type is AccountType.EXPENSE and v
        ),
        key=lambda item: -item[1],
    )[:5]

    return {
        "report": "analysis",
        "period": label,
        "start": start,
        "end": end,
        "income": income,
        "expenses": expenses,
        "net_income": net,
        "savings_rate_pct": round(100 * net / income, 1) if income else None,
        "total_assets": assets,
        "total_liabilities": liabilities,
        "net_worth": assets - liabilities,
        "cash": cash,
        "liquidity_months": (
            round(cash / monthly_expenses, 1) if monthly_expenses else None
        ),
        "debt_to_assets_pct": (
            round(100 * liabilities / assets, 1) if assets else None
        ),
        "debt_to_annual_income_pct": (
            round(100 * liabilities / (monthly_income * 12), 1)
            if monthly_income else None
        ),
        "top_expenses": [
            {"account": name, "amount": amount,
             "pct_of_income": round(100 * amount / income, 1) if income else None}
            for name, amount in top_expenses
        ],
    }


def render_analysis(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("FINANCIAL ANALYSIS"),
             f"For the period: {data['period']}", ""]

    def pct(value) -> str:
        return f"{value:.1f}%" if value is not None else "n/a"

    table = Table(align="lr")
    table.add(bold("Performance"), "")
    table.add("  Income", money(data["income"], decimals, symbol))
    table.add("  Expenses", money(data["expenses"], decimals, symbol))
    table.add("  Net Income (savings)", money(data["net_income"], decimals,
                                              symbol))
    table.add("  Savings Rate", pct(data["savings_rate_pct"]))
    table.add("", "")
    table.add(bold("Position"), "")
    table.add("  Total Assets", money(data["total_assets"], decimals, symbol))
    table.add("  Total Liabilities",
              money(data["total_liabilities"], decimals, symbol))
    table.add("  Net Worth", money(data["net_worth"], decimals, symbol))
    table.add("  Cash & Equivalents", money(data["cash"], decimals, symbol))
    table.add("", "")
    table.add(bold("Ratios"), "")
    months = data["liquidity_months"]
    table.add("  Liquidity Runway",
              f"{months:.1f} months of expenses" if months is not None
              else "n/a")
    table.add("  Debt / Assets", pct(data["debt_to_assets_pct"]))
    table.add("  Debt / Annual Income",
              pct(data["debt_to_annual_income_pct"]))
    lines.append(table.render())

    if data["top_expenses"]:
        lines += ["", bold("Top expense categories")]
        top = Table(headers=["Account", "Amount", "% of Income"], align="lrr")
        for row in data["top_expenses"]:
            top.add(row["account"], money(row["amount"], decimals),
                    pct(row["pct_of_income"]))
        lines.append(top.render())
    return "\n".join(lines)
