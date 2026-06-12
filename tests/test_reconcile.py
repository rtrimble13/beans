from datetime import date

import pytest

from beans.reconcile import reconcile_report
from beans.utils import BeansError
from tests.conftest import post


def seed(led):
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Checking", 100000), ("Equity:Opening Balances", -100000))
    post(led, date(2026, 1, 10), "rent",
         ("Expenses:Housing:Rent", 30000), ("Assets:Checking", -30000))
    post(led, date(2026, 1, 20), "groceries",
         ("Expenses:Food:Groceries", 5000), ("Assets:Checking", -5000))


def test_clear_by_ids_and_balance(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    count = led.set_cleared(checking, txn_ids=[1, 2])
    assert count == 2
    assert led.cleared_balance(checking) == 70000
    uncleared = led.uncleared_postings(checking)
    assert [r["txn_id"] for r in uncleared] == [3]
    assert uncleared[0]["amount"] == -5000


def test_clear_through_date(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    count = led.set_cleared(checking, through=date(2026, 1, 15))
    assert count == 2
    assert led.cleared_balance(checking) == 70000


def test_unclear(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    led.set_cleared(checking, through=date(2026, 12, 31))
    led.set_cleared(checking, txn_ids=[3], cleared=False)
    assert led.cleared_balance(checking) == 70000


def test_clear_requires_selection(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    with pytest.raises(BeansError, match="ids or --through"):
        led.set_cleared(checking)
    with pytest.raises(BeansError, match="no postings"):
        led.set_cleared(checking, txn_ids=[999])


def test_reconcile_report(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    led.set_cleared(checking, txn_ids=[1, 2])
    data = reconcile_report(led, checking, 70000, date(2026, 1, 31))
    assert data["cleared_balance"] == 70000
    assert data["difference"] == 0
    assert [u["id"] for u in data["uncleared"]] == [3]
    assert data["uncleared_total"] == -5000


def test_reconcile_difference(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    data = reconcile_report(led, checking, 65000, date(2026, 1, 31))
    assert data["cleared_balance"] == 0
    assert data["difference"] == 65000


def test_register_carries_cleared_flag(led):
    from beans.reports import register

    seed(led)
    checking = led.find_account("Assets:Checking")
    led.set_cleared(checking, txn_ids=[1])
    data = register(led, checking, None, date(2026, 12, 31))
    assert [r["cleared"] for r in data["rows"]] == [True, False, False]


def test_period_close_blocks_changes(led):
    seed(led)
    led.close_books(date(2026, 1, 31))
    with pytest.raises(BeansError, match="closed through"):
        post(led, date(2026, 1, 15), "late entry",
             ("Expenses:Food:Dining", 1000), ("Assets:Checking", -1000))
    with pytest.raises(BeansError, match="closed through"):
        led.void_transaction(2)
    # After the close date everything still works.
    post(led, date(2026, 2, 1), "new entry",
         ("Expenses:Food:Dining", 1000), ("Assets:Checking", -1000))


def test_period_close_blocks_recurring(led):
    from beans.models import Posting
    from beans.recurring import run_due

    rent = led.find_account("Expenses:Housing:Rent")
    checking = led.find_account("Assets:Checking")
    led.add_recurring("rent", "monthly", date(2026, 1, 1), [
        Posting(account_id=rent.id, amount=1000),
        Posting(account_id=checking.id, amount=-1000),
    ])
    led.close_books(date(2026, 1, 31))
    with pytest.raises(BeansError, match="closed through"):
        run_due(led, date(2026, 2, 15))


def test_period_reopen(led):
    led.close_books(date(2026, 1, 31))
    assert led.closed_through == date(2026, 1, 31)
    with pytest.raises(BeansError, match="already closed"):
        led.close_books(date(2025, 12, 31))
    led.reopen_books()
    assert led.closed_through is None
    with pytest.raises(BeansError, match="not closed"):
        led.reopen_books()
