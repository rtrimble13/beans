from datetime import date, timedelta

from beans.forecast import forecast
from beans.models import Posting
from beans.status import status_report
from beans.utils import add_months
from tests.conftest import post

TODAY = date.today()
FUTURE = TODAY + timedelta(days=365)


def test_status_report(led):
    post(led, TODAY - timedelta(days=60), "opening",
         ("Assets:Checking", 500000), ("Equity:Opening Balances", -500000))
    post(led, TODAY, "salary",
         ("Assets:Checking", 300000), ("Income:Salary", -300000))
    post(led, TODAY, "rent",
         ("Expenses:Housing:Rent", 100000), ("Assets:Checking", -100000))
    led.set_budget(led.find_account("Rent"), 80000, "monthly")
    led.add_goal("house", led.find_account("Assets:Savings"), 100000, FUTURE)
    rent = led.find_account("Expenses:Housing:Rent")
    checking = led.find_account("Assets:Checking")
    led.add_recurring("rent", "monthly", TODAY - timedelta(days=40), [
        Posting(account_id=rent.id, amount=100000),
        Posting(account_id=checking.id, amount=-100000),
    ])

    data = status_report(led)
    assert data["cash"] == 700000
    assert data["net_worth"] == 700000
    assert data["net_worth_change_30d"] == 200000
    assert data["month_income"] == 300000
    assert data["month_expenses"] == 100000
    assert data["budget_total"] == 80000
    assert data["budget_used"] == 100000
    assert data["over_budget"] == ["Rent"]
    assert data["due_recurring"] == ["rent"]
    assert data["goals"][0]["name"] == "house"


def test_forecast_use_recurring(led):
    rent = led.find_account("Expenses:Housing:Rent")
    salary = led.find_account("Income:Salary")
    checking = led.find_account("Assets:Checking")
    next_month = add_months(TODAY, 1)
    led.add_recurring("rent", "monthly", next_month, [
        Posting(account_id=rent.id, amount=150000),
        Posting(account_id=checking.id, amount=-150000),
    ])
    led.add_recurring("paycheck", "monthly", next_month, [
        Posting(account_id=checking.id, amount=400000),
        Posting(account_id=salary.id, amount=-400000),
    ])
    # A budget on rent would normally drive it, but recurring wins.
    led.set_budget(rent, 999900, "monthly")

    data = forecast(led, months=3, use_recurring=True, use_budget=True)
    for row in data["months"]:
        assert row["income"] == 400000
        assert row["expenses"] == 150000
    sources = {d["account"]: d["source"] for d in data["accounts"]}
    assert sources["Expenses:Housing:Rent"] == "recurring"
    assert sources["Income:Salary"] == "recurring"


def test_forecast_recurring_respects_end_date(led):
    rent = led.find_account("Expenses:Housing:Rent")
    checking = led.find_account("Assets:Checking")
    next_month = add_months(TODAY, 1)
    led.add_recurring("short", "monthly", next_month, [
        Posting(account_id=rent.id, amount=100000),
        Posting(account_id=checking.id, amount=-100000),
    ], end=next_month)
    data = forecast(led, months=3, use_recurring=True)
    assert data["months"][0]["expenses"] == 100000
    assert data["months"][1]["expenses"] == 0
    assert data["months"][2]["expenses"] == 0
