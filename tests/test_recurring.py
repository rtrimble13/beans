from datetime import date

import pytest

from beans.models import Posting
from beans.recurring import (
    add_months_clamped,
    list_rules,
    next_due,
    nth_occurrence,
    run_due,
)
from beans.utils import BeansError


def make_rule(led, name="rent", freq="monthly", start=date(2026, 1, 1),
              end=None, amount=180000):
    rent = led.find_account("Expenses:Housing:Rent")
    checking = led.find_account("Assets:Checking")
    return led.add_recurring(
        name, freq, start,
        [Posting(account_id=rent.id, amount=amount),
         Posting(account_id=checking.id, amount=-amount)],
        end=end, description="Monthly rent",
    )


def test_add_months_clamped():
    assert add_months_clamped(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months_clamped(date(2026, 1, 31), 2) == date(2026, 3, 31)
    assert add_months_clamped(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months_clamped(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_nth_occurrence():
    start = date(2026, 1, 31)
    assert nth_occurrence(start, "monthly", 0) == start
    assert nth_occurrence(start, "monthly", 1) == date(2026, 2, 28)
    assert nth_occurrence(start, "monthly", 2) == date(2026, 3, 31)
    assert nth_occurrence(start, "weekly", 2) == date(2026, 2, 14)
    assert nth_occurrence(start, "biweekly", 1) == date(2026, 2, 14)
    assert nth_occurrence(start, "daily", 3) == date(2026, 2, 3)
    assert nth_occurrence(start, "quarterly", 1) == date(2026, 4, 30)
    assert nth_occurrence(start, "yearly", 1) == date(2027, 1, 31)


def test_add_recurring_validates(led):
    with pytest.raises(BeansError, match="invalid frequency"):
        make_rule(led, freq="fortnightly")
    with pytest.raises(BeansError, match="end date is before"):
        make_rule(led, end=date(2025, 1, 1))
    rent = led.find_account("Expenses:Housing:Rent")
    checking = led.find_account("Assets:Checking")
    with pytest.raises(BeansError, match="does not balance"):
        led.add_recurring("bad", "monthly", date(2026, 1, 1), [
            Posting(account_id=rent.id, amount=100),
            Posting(account_id=checking.id, amount=-50),
        ])
    make_rule(led)
    with pytest.raises(BeansError, match="already exists"):
        make_rule(led)


def test_run_due_posts_all_occurrences(led):
    make_rule(led, start=date(2026, 1, 1))
    data = run_due(led, date(2026, 3, 15))
    assert [r["date"] for r in data["posted"]] == [
        date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    txns = led.transactions()
    assert len(txns) == 3
    assert txns[0].description == "Monthly rent"
    assert "recurring" in txns[0].tags
    rent = led.find_account("Expenses:Housing:Rent")
    assert led.balances()[rent.id] == 3 * 180000


def test_run_due_is_idempotent(led):
    make_rule(led, start=date(2026, 1, 1))
    run_due(led, date(2026, 3, 15))
    again = run_due(led, date(2026, 3, 15))
    assert again["posted"] == []
    assert len(led.transactions()) == 3


def test_run_due_respects_end_date(led):
    make_rule(led, start=date(2026, 1, 1), end=date(2026, 2, 28))
    data = run_due(led, date(2026, 12, 31))
    assert len(data["posted"]) == 2
    rec = led.find_recurring("rent")
    assert next_due(rec) is None


def test_run_due_dry_run_writes_nothing(led):
    make_rule(led, start=date(2026, 1, 1))
    data = run_due(led, date(2026, 3, 15), dry_run=True)
    assert len(data["posted"]) == 3
    assert all(r["id"] is None for r in data["posted"])
    assert led.transactions() == []
    assert led.find_recurring("rent").occurrences == 0


def test_paused_rule_skipped(led):
    rec = make_rule(led, start=date(2026, 1, 1))
    led.set_recurring_active(rec, False)
    data = run_due(led, date(2026, 3, 15))
    assert data["posted"] == []


def test_list_rules_status(led):
    make_rule(led, name="overdue", start=date(2026, 1, 1))
    make_rule(led, name="future", start=date(2099, 1, 1))
    ended = make_rule(led, name="done", start=date(2026, 1, 1),
                      end=date(2026, 1, 31))
    run_due(led, date(2026, 2, 15))
    paused = make_rule(led, name="paused", start=date(2026, 1, 1))
    led.set_recurring_active(paused, False)
    by_name = {r["name"]: r for r in
               list_rules(led, date(2026, 6, 1))["rules"]}
    assert by_name["overdue"]["status"] == "due"
    assert by_name["future"]["status"] == "scheduled"
    assert by_name["done"]["status"] == "ended"
    assert by_name["done"]["next_due"] is None
    assert by_name["paused"]["status"] == "paused"
    assert ended.name == "done"


def test_find_recurring(led):
    make_rule(led, name="rent")
    make_rule(led, name="netflix", amount=1500)
    assert led.find_recurring("RENT").name == "rent"
    assert led.find_recurring("net").name == "netflix"
    with pytest.raises(BeansError, match="no recurring rule"):
        led.find_recurring("zzz")


def test_remove_recurring_keeps_history(led):
    rec = make_rule(led, start=date(2026, 1, 1))
    run_due(led, date(2026, 1, 15))
    led.remove_recurring(rec)
    assert led.recurrings() == []
    assert len(led.transactions()) == 1
