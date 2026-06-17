import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from beans import export
from beans.ledger import Ledger
from beans.models import AccountType
from beans.utils import BeansError
from tests.conftest import post


def seed(led):
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Checking", 500000), ("Equity:Opening Balances", -500000))
    post(led, date(2026, 1, 10), "rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    led.set_budget(led.find_account("Rent"), 180000, "monthly")
    led.add_import_rule("WHOLE FOODS", led.find_account("Groceries"))
    led.set_fx_rate("EUR", date(2026, 1, 1), Decimal("1.10"))


def test_export_json_complete(led):
    seed(led)
    data = export.export_json(led)
    assert data["format"] == "beans-export"
    assert data["meta"]["currency"] == "USD"
    names = {a["name"] for a in data["accounts"]}
    assert "Assets:Checking" in names
    assert len(data["transactions"]) == 2
    txn = data["transactions"][0]
    amounts = {p["account"]: p["amount"] for p in txn["postings"]}
    assert amounts["Assets:Checking"] == "5000.00"
    [budget] = data["budgets"]
    assert budget == {"account": "Expenses:Housing:Rent",
                      "amount": "1800.00", "period": "monthly"}
    [rule] = data["import_rules"]
    assert rule["pattern"] == "WHOLE FOODS"
    [rate] = data["fx_rates"]
    assert rate == {"currency": "EUR", "date": "2026-01-01", "rate": "1.10"}


def test_export_json_includes_voids_and_foreign(led):
    seed(led)
    eur = led.add_account("Assets:EUR", AccountType.ASSET, currency="EUR")
    from beans.models import Posting
    led.add_transaction(date(2026, 2, 1), "to EUR", [
        Posting(account_id=eur.id, amount=110000, foreign_amount=100000),
        Posting(account_id=led.find_account("Assets:Checking").id,
                amount=-110000),
    ])
    led.void_transaction(1)
    data = export.export_json(led)
    assert len(data["transactions"]) == 3
    assert data["transactions"][0]["void"] is True
    eur_posting = [p for t in data["transactions"]
                   for p in t["postings"] if p["account"] == "Assets:EUR"]
    assert eur_posting[0]["foreign_amount"] == "1000.00"
    assert eur_posting[0]["currency"] == "EUR"


def test_export_csv(led):
    seed(led)
    text = export.export_csv(led)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 4  # two transactions x two postings
    assert rows[0]["account"] == "Assets:Checking"
    assert rows[0]["amount"] == "5000.00"
    assert rows[2]["txn_id"] == "2"


def test_export_csv_includes_voids(led):
    # A voided transaction must survive the CSV export, flagged, just as it
    # does in JSON — the two formats must agree on what "whole" means.
    seed(led)
    led.void_transaction(2)  # the rent transaction
    text = export.export_csv(led)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert "void" in rows[0]
    by_txn = {}
    for r in rows:
        by_txn.setdefault(r["txn_id"], set()).add(r["void"])
    assert by_txn["1"] == {"0"}  # opening, not void
    assert by_txn["2"] == {"1"}  # rent, voided — present and flagged
    # And JSON agrees: the voided transaction is present with void=True.
    data = export.export_json(led)
    voided = [t for t in data["transactions"] if t["id"] == 2]
    assert len(voided) == 1 and voided[0]["void"] is True


def test_backup_roundtrip(led, tmp_path):
    seed(led)
    dest = tmp_path / "snapshot.db"
    path = export.backup(led, str(dest))
    assert path == dest
    with Ledger(path) as copy:
        assert copy.balances() == led.balances()
        assert copy.currency == led.currency


def test_backup_default_name_and_guards(led, tmp_path):
    seed(led)
    path = export.backup(led, str(tmp_path))
    assert path.parent == tmp_path
    assert "backup" in path.name
    with pytest.raises(BeansError, match="already exists"):
        export.backup(led, str(path))
    with pytest.raises(BeansError, match="ledger itself"):
        export.backup(led, str(led.path))
