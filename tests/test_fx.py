from datetime import date
from decimal import Decimal

import pytest

from beans import fx
from beans.models import AccountType, Posting
from beans.utils import BeansError, base_from_foreign, foreign_from_base
from tests.conftest import post


def eur_account(led, name="Assets:EUR Savings"):
    return led.add_account(name, AccountType.ASSET, currency="EUR")


def seed_cash(led):
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Checking", 1000000), ("Equity:Opening Balances", -1000000))


def transfer(led, when, base_minor, eur, foreign_minor=None):
    checking = led.find_account("Assets:Checking")
    return led.add_transaction(when, "to EUR", [
        Posting(account_id=eur.id, amount=base_minor,
                foreign_amount=foreign_minor),
        Posting(account_id=checking.id, amount=-base_minor),
    ])


def test_fx_math_helpers():
    assert foreign_from_base(11000, Decimal("1.10"), 2, 2) == 10000
    assert base_from_foreign(10000, Decimal("1.10"), 2, 2) == 11000
    # JPY has zero decimal places: 100.00 USD -> 14,925 yen.
    assert foreign_from_base(10000, Decimal("0.0067"), 2, 0) == 14925
    assert base_from_foreign(14925, Decimal("0.0067"), 2, 0) == 10000


def test_account_currency_validation(led):
    with pytest.raises(BeansError, match="invalid currency code"):
        led.add_account("Assets:Bad", AccountType.ASSET, currency="EURO")
    with pytest.raises(BeansError, match="asset and liability"):
        led.add_account("Income:EUR Salary", AccountType.INCOME,
                        currency="EUR")
    # The base currency is not a foreign denomination.
    usd = led.add_account("Assets:More USD", AccountType.ASSET,
                          currency="usd")
    assert usd.currency is None
    eur = eur_account(led)
    assert eur.currency == "EUR"


def test_explicit_foreign_amount(led):
    seed_cash(led)
    eur = eur_account(led)
    transfer(led, date(2026, 2, 1), 110000, eur, foreign_minor=100000)
    assert led.foreign_balances()[eur.id] == 100000
    assert led.balances()[eur.id] == 110000
    txn = led.transactions()[-1]
    by_account = {p.account_id: p for p in txn.postings}
    assert by_account[eur.id].foreign_amount == 100000
    checking = led.find_account("Assets:Checking")
    assert by_account[checking.id].foreign_amount is None


def test_derived_foreign_amount_from_rate(led):
    seed_cash(led)
    eur = eur_account(led)
    led.set_fx_rate("EUR", date(2026, 1, 15), Decimal("1.10"))
    transfer(led, date(2026, 2, 1), 110000, eur)
    assert led.foreign_balances()[eur.id] == 100000


def test_missing_rate_errors(led):
    seed_cash(led)
    eur = eur_account(led)
    with pytest.raises(BeansError, match="no exchange rate for EUR"):
        transfer(led, date(2026, 2, 1), 110000, eur)


def test_rate_as_of_transaction_date(led):
    seed_cash(led)
    eur = eur_account(led)
    led.set_fx_rate("EUR", date(2026, 1, 1), Decimal("1.10"))
    led.set_fx_rate("EUR", date(2026, 3, 1), Decimal("1.25"))
    # A February transaction uses the January rate, not March's.
    transfer(led, date(2026, 2, 1), 110000, eur)
    assert led.foreign_balances()[eur.id] == 100000


def test_set_rate_rejects_base_currency(led):
    with pytest.raises(BeansError, match="base currency"):
        led.set_fx_rate("USD", date(2026, 1, 1), Decimal("1"))


def test_set_rate_validates_inputs(led):
    with pytest.raises(BeansError, match="invalid currency code"):
        led.set_fx_rate("EURO", date(2026, 1, 1), Decimal("1.1"))
    with pytest.raises(BeansError, match="must be positive"):
        led.set_fx_rate("EUR", date(2026, 1, 1), Decimal("0"))
    with pytest.raises(BeansError, match="must be positive"):
        led.set_fx_rate("EUR", date(2026, 1, 1), Decimal("-1.1"))


def test_revalue_books_fx_gain_and_balances(led):
    from beans.reports import balance_sheet

    seed_cash(led)
    eur = eur_account(led)
    led.set_fx_rate("EUR", date(2026, 1, 15), Decimal("1.10"))
    transfer(led, date(2026, 2, 1), 110000, eur)
    led.set_fx_rate("EUR", date(2026, 3, 1), Decimal("1.20"))

    data = fx.revalue(led, date(2026, 3, 15))
    [adj] = data["adjustments"]
    assert adj["adjustment"] == 10000  # 1000 EUR * (1.20 - 1.10)
    assert led.balances()[eur.id] == 120000
    # The foreign balance is unchanged by revaluation.
    assert led.foreign_balances()[eur.id] == 100000
    gains = led.find_account("Income:FX Gains")
    assert led.balances()[gains.id] == -10000
    # Idempotent, and the books still balance.
    assert fx.revalue(led, date(2026, 3, 16))["adjustments"] == []
    sheet = balance_sheet(led, date(2026, 3, 31))
    assert sheet["balanced"]
    assert sheet["retained_earnings"] == 10000


def test_revalue_requires_rate(led):
    seed_cash(led)
    eur = eur_account(led)
    led.set_fx_rate("EUR", date(2026, 1, 15), Decimal("1.10"))
    transfer(led, date(2026, 2, 1), 110000, eur)
    led.db.execute("DELETE FROM fx_rates")
    led.db.commit()
    with pytest.raises(BeansError, match="no exchange rate"):
        fx.revalue(led, date(2026, 3, 1))


def test_currencies_report(led):
    seed_cash(led)
    eur = eur_account(led)
    led.set_fx_rate("EUR", date(2026, 1, 15), Decimal("1.10"))
    transfer(led, date(2026, 2, 1), 110000, eur)
    led.set_fx_rate("EUR", date(2026, 3, 1), Decimal("1.20"))
    data = fx.currencies_report(led, as_of=date(2026, 3, 15))
    [row] = data["rows"]
    assert row["currency"] == "EUR"
    assert row["foreign_balance"] == 100000
    assert row["book"] == 110000
    assert row["market"] == 120000
    assert row["unrealized"] == 10000
