from datetime import date
from decimal import Decimal

import pytest

from beans import loans
from beans.models import AccountType, Loan
from beans.utils import BeansError
from tests.conftest import post


def make_loan(principal=3000000, rate="0.0625", term=60, payment=58348,
              start=date(2026, 1, 1)):
    return Loan(id=1, account_id=1, principal=principal,
                annual_rate=Decimal(rate), term_months=term, payment=payment,
                start_date=start)


def test_payment_for_known_amortization():
    # $30,000 at 6.25% over 60 months amortizes to $583.48/month.
    rate = loans.periodic_rate(Decimal("0.0625"))
    assert loans.payment_for(3000000, rate, 60) == 58348


def test_payment_for_zero_rate_is_straight_line():
    assert loans.payment_for(120000, Decimal(0), 12) == 10000


def test_schedule_fully_amortizes():
    sched = loans.schedule(make_loan())
    assert len(sched) == 60
    assert sched[-1]["balance"] == 0
    # Every dollar of principal is repaid exactly once.
    assert sum(r["principal"] for r in sched) == 3000000
    # Each payment is interest + principal.
    for r in sched:
        assert r["payment"] == r["interest"] + r["principal"]


def test_term_for_inverts_payment_for():
    rate = loans.periodic_rate(Decimal("0.0625"))
    assert loans.term_for(3000000, rate, 58348) == 60


def test_term_for_rejects_payment_below_interest():
    rate = loans.periodic_rate(Decimal("0.0625"))
    with pytest.raises(BeansError):
        loans.term_for(3000000, rate, 100)  # nowhere near the interest


def test_current_portion_is_next_year_principal_capped():
    loan = make_loan()
    # As of the day before the loan starts, the current portion is the first
    # twelve payments' principal (payments dated 2026-01..2026-12).
    sched = loans.schedule(loan)
    first_year = sum(r["principal"] for r in sched
                     if r["date"] <= date(2026, 12, 31))
    current = loans.current_portion(loan, date(2025, 12, 31), 3000000)
    assert current == first_year
    assert 0 < current < 3000000
    # Capped at the actual outstanding balance.
    assert loans.current_portion(loan, date(2025, 12, 31), 100000) == 100000


def test_current_portion_all_current_when_schedule_exhausted():
    loan = make_loan()
    # After the last scheduled payment, any residual balance is current.
    assert loans.current_portion(loan, date(2032, 1, 1), 5000) == 5000


def test_classified_split_uses_loan_then_tag(led):
    # A tagged non-current liability with no loan falls back to its tag.
    led.add_account("Liabilities:Alimony", AccountType.LIABILITY,
                    liquidity="noncurrent")
    post(led, date(2026, 1, 1), "open",
         ("Liabilities:Loans", -3000000),
         ("Liabilities:Alimony", -1000000),
         ("Equity:Opening Balances", 4000000))
    account = led.find_account("Liabilities:Loans")
    led.add_loan(account, 3000000, Decimal("0.0625"), 60, 58348,
                 date(2026, 1, 1))
    raw = led.balances()
    split = loans.classified_liability_split(led, date(2026, 6, 30), raw)

    loans_acct = led.find_account("Liabilities:Loans")
    alimony = led.find_account("Liabilities:Alimony")
    cur, non = split[loans_acct.id]
    assert cur + non == 3000000            # ties to the ledger balance
    assert 0 < cur < 3000000               # genuinely split by the schedule
    # The untagged loan split, and the tagged alimony went wholly non-current.
    assert split[alimony.id] == (0, 1000000)


def test_pay_splits_interest_and_principal(led):
    post(led, date(2026, 1, 1), "open",
         ("Liabilities:Loans", -3000000),
         ("Equity:Opening Balances", 3000000))
    account = led.find_account("Liabilities:Loans")
    led.add_loan(account, 3000000, Decimal("0.0625"), 60, 58348,
                 date(2026, 1, 1))
    cash = led.find_account("Assets:Checking")
    result = loans.pay(led, account, cash, date(2026, 2, 1))
    # Interest on the full balance: 3,000,000 * 0.0625/12 = 15,625.
    assert result["interest"] == 15625
    assert result["principal"] == 58348 - 15625
    assert result["payment"] == 58348
    assert result["balance_after"] == 3000000 - result["principal"]
    # The books still balance and interest hit Expenses:Interest.
    interest_acct = led.find_account("Expenses:Interest")
    assert led.balances()[interest_acct.id] == 15625
