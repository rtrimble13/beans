from datetime import date, timedelta

import pytest

from beans.goals import goals_report
from beans.utils import BeansError
from tests.conftest import post

FUTURE = date.today() + timedelta(days=365)


def test_savings_goal_progress(led):
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Savings", 500000), ("Equity:Opening Balances", -500000))
    savings = led.find_account("Assets:Savings")
    led.add_goal("house", savings, 2000000, FUTURE)
    data = goals_report(led)
    [row] = data["rows"]
    assert row["kind"] == "savings"
    assert row["progress_pct"] == 25.0
    assert row["remaining"] == 1500000
    assert not row["on_track"]
    assert row["required_monthly"] > 0


def test_payoff_goal(led):
    post(led, date(2026, 1, 1), "opening",
         ("Equity:Opening Balances", 120000),
         ("Liabilities:Credit Card", -120000))
    card = led.find_account("Liabilities:Credit Card")
    led.add_goal("debt-free", card, 0, FUTURE)
    data = goals_report(led)
    [row] = data["rows"]
    assert row["kind"] == "payoff"
    assert row["remaining"] == 120000
    assert row["progress_pct"] is None


def test_goal_reached(led):
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Savings", 500000), ("Equity:Opening Balances", -500000))
    savings = led.find_account("Assets:Savings")
    led.add_goal("emergency", savings, 400000, FUTURE)
    [row] = goals_report(led)["rows"]
    assert row["on_track"]
    assert row["remaining"] == 0


def test_goal_validation(led):
    savings = led.find_account("Assets:Savings")
    salary = led.find_account("Income:Salary")
    with pytest.raises(BeansError, match="asset or liability"):
        led.add_goal("bad", salary, 1000, FUTURE)
    with pytest.raises(BeansError, match="future"):
        led.add_goal("bad", savings, 1000, date(2020, 1, 1))
    led.add_goal("house", savings, 1000, FUTURE)
    with pytest.raises(BeansError, match="already exists"):
        led.add_goal("house", savings, 2000, FUTURE)
    led.remove_goal("house")
    with pytest.raises(BeansError, match="no goal"):
        led.remove_goal("house")
