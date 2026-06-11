from datetime import date

import pytest

from beans.ledger import Ledger
from beans.models import Posting


@pytest.fixture
def led(tmp_path):
    ledger = Ledger(tmp_path / "test.db", create=True)
    ledger.initialize(currency="USD")
    yield ledger
    ledger.close()


def post(led: Ledger, when: date, desc: str, *legs: tuple[str, int]):
    """Record a transaction from (account-name, minor-amount) pairs."""
    postings = [
        Posting(account_id=led.find_account(name).id, amount=amount)
        for name, amount in legs
    ]
    return led.add_transaction(when, desc, postings)
