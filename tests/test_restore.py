from datetime import date
from decimal import Decimal

import pytest

from beans import export, reports
from beans.ledger import Ledger
from beans.models import AccountType, Posting
from beans.restore import restore_ledger
from beans.utils import BeansError


def by_name(led, foreign=False):
    names = {a.id: a.name for a in led.accounts(include_closed=True)}
    raw = led.foreign_balances() if foreign else led.balances()
    return {names[k]: v for k, v in raw.items()}


def seed_rich(led):
    """A ledger exercising the corners: foreign postings, a void, a cleared
    posting, a closed account, a closed period, and every side entity."""
    eur = led.add_account("Assets:EUR Savings", AccountType.ASSET,
                          currency="EUR")
    led.set_fx_rate("EUR", date(2026, 1, 1), Decimal("1.10"))
    checking = led.find_account("Assets:Checking")
    led.add_transaction(date(2026, 1, 1), "opening", [
        Posting(account_id=checking.id, amount=500000),
        Posting(account_id=led.find_account("Equity:Opening Balances").id,
                amount=-500000)])
    led.add_transaction(date(2026, 1, 15), "pay", [
        Posting(account_id=checking.id, amount=400000),
        Posting(account_id=led.find_account("Income:Salary").id,
                amount=-400000)])
    rent = led.add_transaction(date(2026, 2, 1), "rent", [
        Posting(account_id=led.find_account("Expenses:Housing:Rent").id,
                amount=180000),
        Posting(account_id=checking.id, amount=-180000)])
    oops = led.add_transaction(date(2026, 2, 2), "oops", [
        Posting(account_id=checking.id, amount=1000),
        Posting(account_id=led.find_account("Income:Other").id,
                amount=-1000)])
    led.void_transaction(oops.id)
    led.add_transaction(date(2026, 2, 3), "to EUR", [
        Posting(account_id=eur.id, amount=110000, foreign_amount=100000),
        Posting(account_id=checking.id, amount=-110000)])
    led.set_cleared(checking, txn_ids=[rent.id])  # confirmed vs statement
    led.set_budget(led.find_account("Groceries"), 60000, "monthly")
    led.add_import_rule("WHOLE FOODS", led.find_account("Groceries"))
    led.add_goal("house", led.find_account("Assets:Savings"),
                 2000000, date(2030, 1, 1))
    led.add_lot(led.find_account("Assets:Investments:Brokerage"),
                "VTI", "10", 280000, date(2026, 1, 5))
    led.set_price("VTI", date(2026, 1, 6), 295000)
    led.add_recurring("monthly rent", "monthly", date(2026, 3, 1), [
        Posting(account_id=led.find_account("Expenses:Housing:Rent").id,
                amount=180000),
        Posting(account_id=checking.id, amount=-180000)])
    led.close_account(led.find_account("Expenses:Entertainment"))
    led.close_books(date(2026, 1, 31))


def test_restore_round_trip(led, tmp_path):
    seed_rich(led)
    data = export.export_json(led)

    dst = Ledger(tmp_path / "restored.db", create=True)
    summary = restore_ledger(dst, data)

    # The books tie before and after, by account name (internal ids may
    # differ; what must hold is balances, not row ids).
    assert by_name(dst) == by_name(led)
    assert by_name(dst, foreign=True) == by_name(led, foreign=True)

    end = date(2026, 12, 31)
    assert (reports.trial_balance(dst, end)["total_debits"]
            == reports.trial_balance(led, end)["total_debits"])
    assert reports.balance_sheet(dst, end)["balanced"]

    # Meta and provenance.
    assert dst.currency == led.currency
    assert dst.decimals == led.decimals
    assert dst.closed_through == date(2026, 1, 31)

    # Void state: same transaction ids present, same one voided.
    src_ids = [(t.id, t.void) for t in led.transactions(include_void=True)]
    dst_ids = [(t.id, t.void) for t in dst.transactions(include_void=True)]
    assert dst_ids == src_ids

    # Cleared state survives.
    checking = dst.find_account("Assets:Checking")
    assert dst.cleared_balance(checking) == led.cleared_balance(
        led.find_account("Assets:Checking"))

    # Closed account stays closed; side entities all came across.
    assert dst.find_account("Expenses:Entertainment").closed
    assert summary == {"accounts": 24, "transactions": 5, "budgets": 1,
                       "recurring": 1, "goals": 1, "import_rules": 1,
                       "lots": 1, "prices": 1, "fx_rates": 1}
    assert [r.name for r in dst.recurrings()] == ["monthly rent"]


def test_restore_preserves_default_cashflow_state(led, tmp_path):
    # An explicit override survives; an account on its type default stays on
    # the default (not silently pinned to an explicit value).
    led.update_account(led.find_account("Assets:Savings"),
                       cf_category="operating")  # override (default: investing)
    data = export.export_json(led)
    dst = Ledger(tmp_path / "r.db", create=True)
    restore_ledger(dst, data)
    assert dst.find_account("Assets:Savings").cf_category == "operating"
    # Checking was never overridden -> still implicit default.
    assert dst.find_account("Assets:Checking").cf_category is None


def test_restore_rejects_non_beans_json(tmp_path):
    dst = Ledger(tmp_path / "r.db", create=True)
    with pytest.raises(BeansError, match="not a beans export"):
        restore_ledger(dst, {"some": "other json"})


def test_restore_rejects_initialized_ledger(led, tmp_path):
    data = export.export_json(led)
    with pytest.raises(BeansError, match="already initialized"):
        restore_ledger(led, data)  # led is the seeded, initialized ledger
