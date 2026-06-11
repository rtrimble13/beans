from datetime import date

import pytest

from beans.models import AccountType, Posting
from beans.utils import BeansError
from tests.conftest import post


def test_default_chart_created(led):
    names = {a.name for a in led.accounts()}
    assert "Assets:Checking" in names
    assert "Equity:Opening Balances" in names
    assert led.find_account("Assets:Checking").is_cash


def test_unbalanced_transaction_rejected(led):
    with pytest.raises(BeansError, match="does not balance"):
        post(led, date(2026, 1, 1), "bad",
             ("Assets:Checking", 100), ("Income:Salary", -50))


def test_single_posting_rejected(led):
    with pytest.raises(BeansError, match="at least two"):
        led.add_transaction(date(2026, 1, 1), "bad", [
            Posting(account_id=led.find_account("Assets:Checking").id,
                    amount=0)
        ])


def test_balances_and_natural_signs(led):
    post(led, date(2026, 1, 15), "paycheck",
         ("Assets:Checking", 500000), ("Income:Salary", -500000))
    post(led, date(2026, 1, 20), "rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    raw = led.balances()
    checking = led.find_account("Assets:Checking")
    salary = led.find_account("Income:Salary")
    assert raw[checking.id] == 320000
    assert raw[salary.id] == -500000  # credit-normal stored negative
    assert raw[salary.id] * salary.type.natural_sign == 500000


def test_balances_respect_as_of_date(led):
    post(led, date(2026, 1, 1), "early",
         ("Assets:Checking", 1000), ("Income:Salary", -1000))
    post(led, date(2026, 3, 1), "late",
         ("Assets:Checking", 2000), ("Income:Salary", -2000))
    checking = led.find_account("Assets:Checking").id
    assert led.balances(as_of=date(2026, 1, 31))[checking] == 1000
    assert led.balances(as_of=date(2026, 3, 31))[checking] == 3000


def test_void_excludes_transaction(led):
    txn = post(led, date(2026, 1, 1), "oops",
               ("Assets:Checking", 1000), ("Income:Salary", -1000))
    led.void_transaction(txn.id)
    assert led.balances() == {}
    with pytest.raises(BeansError, match="already void"):
        led.void_transaction(txn.id)


def test_fuzzy_account_matching(led):
    assert led.find_account("checking").name == "Assets:Checking"
    assert led.find_account("rent").name == "Expenses:Housing:Rent"
    with pytest.raises(BeansError, match="ambiguous"):
        led.find_account("Food")
    with pytest.raises(BeansError, match="no account matches"):
        led.find_account("zzz")


def test_close_account_requires_zero_balance(led):
    checking = led.find_account("Assets:Checking")
    post(led, date(2026, 1, 1), "x",
         ("Assets:Checking", 1000), ("Income:Salary", -1000))
    with pytest.raises(BeansError, match="balance is not zero"):
        led.close_account(checking)
    post(led, date(2026, 1, 2), "drain",
         ("Assets:Savings", 1000), ("Assets:Checking", -1000))
    led.close_account(checking)
    assert led.find_account("Assets:Checking").closed


def test_duplicate_account_rejected(led):
    with pytest.raises(BeansError, match="already exists"):
        led.add_account("Assets:Checking", AccountType.ASSET)


def test_update_account_validation(led):
    checking = led.find_account("Assets:Checking")
    with pytest.raises(BeansError, match="invalid cash-flow category"):
        led.update_account(checking, cf_category="bogus")
    with pytest.raises(BeansError, match="invalid account name"):
        led.update_account(checking, name=":bad")
    with pytest.raises(BeansError, match="already exists"):
        led.update_account(checking, name="Assets:Savings")


def test_cash_flag_only_on_assets(led):
    with pytest.raises(BeansError, match="only asset accounts"):
        led.add_account("Income:Weird", AccountType.INCOME, is_cash=True)


def test_budget_crud(led):
    groceries = led.find_account("Groceries")
    led.set_budget(groceries, 50000, "monthly")
    led.set_budget(groceries, 60000, "monthly")  # upsert
    [(account, amount, period)] = led.budgets()
    assert account.id == groceries.id
    assert (amount, period) == (60000, "monthly")
    led.remove_budget(groceries)
    assert led.budgets() == []
    with pytest.raises(BeansError, match="no budget"):
        led.remove_budget(groceries)


def test_budget_only_income_expense(led):
    with pytest.raises(BeansError, match="income or expense"):
        led.set_budget(led.find_account("Assets:Checking"), 100, "monthly")


def test_transactions_filtering(led):
    post(led, date(2026, 1, 1), "a",
         ("Assets:Checking", 100), ("Income:Salary", -100))
    post(led, date(2026, 2, 1), "b",
         ("Assets:Savings", 200), ("Income:Salary", -200))
    checking = led.find_account("Assets:Checking")
    assert [t.description for t in led.transactions(account=checking)] == ["a"]
    assert len(led.transactions(start=date(2026, 1, 15))) == 1
    assert len(led.transactions(end=date(2026, 1, 15))) == 1
