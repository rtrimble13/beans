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


def test_add_transaction_rejects_closed_account(led):
    # Closing requires a zero balance; drain Entertainment to zero, close
    # it, then prove the ledger itself blocks any posting to it.
    ent = led.find_account("Expenses:Entertainment")
    post(led, date(2026, 1, 1), "movie",
         ("Expenses:Entertainment", 2000), ("Assets:Checking", -2000))
    post(led, date(2026, 1, 2), "refund",
         ("Assets:Checking", 2000), ("Expenses:Entertainment", -2000))
    led.close_account(ent)
    checking = led.find_account("Assets:Checking")
    with pytest.raises(BeansError, match="Expenses:Entertainment is closed"):
        led.add_transaction(date(2026, 3, 1), "movie", [
            Posting(account_id=ent.id, amount=2000),
            Posting(account_id=checking.id, amount=-2000),
        ])


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


def test_liquidity_default_and_starter_chart(led):
    # Everything defaults to current; the starter chart pre-marks the obvious
    # long-term accounts.
    assert led.find_account("Assets:Checking").liquidity == "current"
    assert led.find_account("Assets:Checking").is_current
    assert led.find_account("Assets:Investments:Retirement").liquidity == \
        "noncurrent"
    assert led.find_account("Liabilities:Loans").liquidity == "noncurrent"


def test_liquidity_validation_and_update(led):
    # Non-current is only meaningful for assets and liabilities.
    with pytest.raises(BeansError, match="only asset and liability"):
        led.add_account("Income:Weird", AccountType.INCOME,
                        liquidity="noncurrent")
    with pytest.raises(BeansError, match="invalid liquidity"):
        led.add_account("Assets:Odd", AccountType.ASSET, liquidity="soon")
    savings = led.find_account("Assets:Savings")
    led.update_account(savings, liquidity="noncurrent")
    assert led.find_account("Assets:Savings").liquidity == "noncurrent"
    salary = led.find_account("Income:Salary")
    with pytest.raises(BeansError, match="only asset and liability"):
        led.update_account(salary, liquidity="noncurrent")


def test_liquidity_migration_backfills_current(tmp_path):
    import sqlite3

    from beans.ledger import Ledger

    # An old ledger whose accounts table predates the liquidity column.
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "CREATE TABLE accounts (id INTEGER PRIMARY KEY, "
        "name TEXT NOT NULL UNIQUE, type TEXT NOT NULL, "
        "is_cash INTEGER NOT NULL DEFAULT 0, cf_category TEXT, "
        "closed INTEGER NOT NULL DEFAULT 0, "
        "description TEXT NOT NULL DEFAULT '');"
        "INSERT INTO accounts (name, type) VALUES ('Assets:Old', 'asset');"
    )
    con.commit()
    con.close()

    led = Ledger(path)  # opening runs the migration
    assert led.find_account("Assets:Old").liquidity == "current"
    led.close()


def test_loan_crud(led):
    from decimal import Decimal

    account = led.find_account("Liabilities:Loans")
    loan = led.add_loan(account, 3000000, Decimal("0.0625"), 60, 58348,
                        date(2026, 1, 1))
    assert loan.account_name == "Liabilities:Loans"
    assert led.loan_for(account).payment == 58348
    assert [ln.account_name for ln in led.loans()] == ["Liabilities:Loans"]
    # One loan per account.
    with pytest.raises(BeansError, match="already has a loan"):
        led.add_loan(account, 100, Decimal("0.05"), 12, 10, date(2026, 1, 1))
    # Loans only attach to liabilities.
    with pytest.raises(BeansError, match="liability accounts"):
        led.add_loan(led.find_account("Assets:Checking"), 100,
                     Decimal("0.05"), 12, 10, date(2026, 1, 1))
    led.remove_loan(account)
    assert led.loan_for(account) is None


def test_closing_account_drops_its_loan(led):
    from decimal import Decimal

    account = led.find_account("Liabilities:Loans")
    # Draw then repay so the balance is zero and the account can close.
    led.add_transaction(date(2026, 1, 1), "draw", [
        Posting(account_id=led.find_account("Assets:Checking").id,
                amount=100000),
        Posting(account_id=account.id, amount=-100000)])
    led.add_loan(account, 100000, Decimal("0.05"), 12, 8561, date(2026, 1, 1))
    led.add_transaction(date(2026, 2, 1), "payoff", [
        Posting(account_id=account.id, amount=100000),
        Posting(account_id=led.find_account("Assets:Checking").id,
                amount=-100000)])
    led.close_account(account)
    assert led.loan_for(account) is None
    assert led.loans() == []


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
