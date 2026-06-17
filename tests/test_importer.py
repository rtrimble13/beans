from datetime import date

import pytest

from beans.importer import import_csv
from beans.utils import BeansError
from tests.conftest import post


def write_csv(tmp_path, body):
    file = tmp_path / "bank.csv"
    file.write_text("date,description,amount,category\n" + body)
    return str(file)


def test_dedupe_skips_existing(led, tmp_path):
    checking = led.find_account("Assets:Checking")
    post(led, date(2026, 3, 1), "Pay",
         ("Assets:Checking", 100000), ("Income:Salary", -100000))
    path = write_csv(tmp_path,
                     "2026-03-01,Pay,1000.00,Salary\n"
                     "2026-03-02,Food,-50.00,Groceries\n")
    result = import_csv(led, path, checking,
                        default_category=led.find_account("Expenses:Other"))
    assert len(result["imported"]) == 1
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["description"] == "Pay"
    # Re-importing the whole file is now a no-op.
    again = import_csv(led, path, checking,
                       default_category=led.find_account("Expenses:Other"))
    assert again["imported"] == []
    assert len(again["skipped"]) == 2


def test_distinct_same_day_same_amount_rows_both_import(led, tmp_path):
    # Two genuinely distinct rows that share a date and amount must not
    # collapse into one: count-aware dedupe keeps both.
    checking = led.find_account("Assets:Checking")
    path = write_csv(tmp_path,
                     "2026-03-01,Coffee,-4.50,Groceries\n"
                     "2026-03-01,Coffee,-4.50,Groceries\n")
    result = import_csv(led, path, checking,
                        default_category=led.find_account("Expenses:Other"))
    assert len(result["imported"]) == 2
    assert result["skipped"] == []
    assert len(led.transactions()) == 2
    # Re-importing the same file is still a no-op (both now look like dupes).
    again = import_csv(led, path, checking,
                       default_category=led.find_account("Expenses:Other"))
    assert again["imported"] == []
    assert len(again["skipped"]) == 2


def test_dry_run_matches_real_run(led, tmp_path):
    # The preview must agree with the real run, including for intra-file
    # duplicates that a per-row "exists?" check would mis-count.
    checking = led.find_account("Assets:Checking")
    post(led, date(2026, 3, 1), "Pay",
         ("Assets:Checking", 100000), ("Income:Salary", -100000))
    path = write_csv(tmp_path,
                     "2026-03-01,Pay,1000.00,Salary\n"
                     "2026-03-02,Coffee,-4.50,Groceries\n"
                     "2026-03-02,Coffee,-4.50,Groceries\n")
    kw = dict(default_category=led.find_account("Expenses:Other"))
    dry = import_csv(led, path, checking, dry_run=True, **kw)
    real = import_csv(led, path, checking, **kw)
    assert len(dry["imported"]) == len(real["imported"]) == 2
    assert len(dry["skipped"]) == len(real["skipped"]) == 1


def test_no_dedupe_flag(led, tmp_path):
    checking = led.find_account("Assets:Checking")
    path = write_csv(tmp_path, "2026-03-01,Pay,1000.00,Salary\n")
    import_csv(led, path, checking)
    result = import_csv(led, path, checking, dedupe=False)
    assert len(result["imported"]) == 1
    assert len(led.transactions()) == 2


def test_import_rules_categorize(led, tmp_path):
    checking = led.find_account("Assets:Checking")
    led.add_import_rule("WHOLE FOODS", led.find_account("Groceries"))
    led.add_import_rule("shell", led.find_account("Transportation"))
    path = write_csv(tmp_path,
                     "2026-03-01,WHOLE FOODS #123,-50.00,\n"
                     "2026-03-02,Shell Gas Station,-30.00,\n"
                     "2026-03-03,Explicit,-10.00,Dining\n")
    result = import_csv(led, path, checking)
    counters = [r["counter"] for r in result["imported"]]
    assert counters == ["Expenses:Food:Groceries",
                        "Expenses:Transportation",
                        "Expenses:Food:Dining"]


def test_unmatched_without_fallback_fails(led, tmp_path):
    checking = led.find_account("Assets:Checking")
    path = write_csv(tmp_path, "2026-03-01,Mystery,-5.00,\n")
    with pytest.raises(BeansError, match="no import rule matches"):
        import_csv(led, path, checking)


def test_rule_crud(led):
    groceries = led.find_account("Groceries")
    led.add_import_rule("WHOLE FOODS", groceries)
    with pytest.raises(BeansError, match="already exists"):
        led.add_import_rule("whole foods", groceries)
    assert led.match_import_rule("WHOLE FOODS MKT #10").name == groceries.name
    assert led.match_import_rule("no match") is None
    [(rule_id, pattern, account)] = led.import_rules()
    assert pattern == "WHOLE FOODS"
    led.remove_import_rule("WHOLE FOODS")
    assert led.import_rules() == []
    with pytest.raises(BeansError, match="no import rule"):
        led.remove_import_rule("WHOLE FOODS")
