"""Numeric tests for the ratios behind `beans analyze`.

The CLI test only asserts the command runs; these pin each ratio against a
fixture with hand-computed values, including every null-denominator path.
"""

from datetime import date

from beans.analysis import analyze
from tests.conftest import post


def test_analyze_ratios_exact_values(led):
    # Opening (Jan 1): cash 10,000 against a 4,000 loan; the rest to equity.
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Checking", 1_000_000),
         ("Liabilities:Loans", -400_000),
         ("Equity:Opening Balances", -600_000))
    # Income 6,000 and expenses 3,000 over a clean 3-month period.
    post(led, date(2026, 1, 15), "salary",
         ("Assets:Checking", 600_000), ("Income:Salary", -600_000))
    post(led, date(2026, 2, 1), "rent",
         ("Expenses:Housing:Rent", 300_000), ("Assets:Checking", -300_000))

    data = analyze(led, date(2026, 1, 1), date(2026, 3, 31), "2026-Q1")

    # Performance: income 6,000, expenses 3,000, net 3,000 over 3 months.
    assert data["income"] == 600_000
    assert data["expenses"] == 300_000
    assert data["net_income"] == 300_000
    assert data["savings_rate_pct"] == 50.0  # 100 * 300000 / 600000

    # Position at end: checking 13,000 (cash & only asset), loan 4,000.
    assert data["total_assets"] == 1_300_000
    assert data["total_liabilities"] == 400_000
    assert data["cash"] == 1_300_000
    assert data["net_worth"] == 900_000

    # Ratios. monthly_expenses = 3000/3 = 1000; monthly_income = 6000/3 = 2000.
    assert data["liquidity_months"] == 13.0      # 13000 / 1000
    assert data["debt_to_assets_pct"] == 30.8    # 100 * 400000 / 1300000
    # 100 * 400000 / (2000_00 * 12) = 100 * 400000 / 2_400_000 = 16.666… -> 16.7
    assert data["debt_to_annual_income_pct"] == 16.7

    [top] = data["top_expenses"]
    assert top == {"account": "Expenses:Housing:Rent",
                   "amount": 300_000, "pct_of_income": 50.0}


def test_analyze_null_denominator_paths(led):
    # Empty ledger, unbounded period: every denominator is zero or unknown,
    # so each ratio degrades to None rather than dividing by zero.
    data = analyze(led, None, date(2026, 3, 31), "all")
    assert data["income"] == 0
    assert data["savings_rate_pct"] is None          # income == 0
    assert data["liquidity_months"] is None          # months is None
    assert data["debt_to_assets_pct"] is None        # assets == 0
    assert data["debt_to_annual_income_pct"] is None  # monthly_income None
    assert data["top_expenses"] == []
