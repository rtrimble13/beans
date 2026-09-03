"""Tests for the beans-import skill's helper scripts.

They are plain CSV transforms over text, so they test cheaply — and they are
worth testing because they run against real statement exports where a
misread sign or an off-by-one date silently corrupts a month of books.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = (Path(__file__).resolve().parent.parent
           / ".claude" / "skills" / "beans-import" / "scripts")


def _load(name):
    """Import a script by path — it is not on the package path."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inspect_csv = _load("inspect_csv")
normalize_csv = _load("normalize_csv")
triage = _load("triage")


def write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body)
    return path


# -- inspect_csv -------------------------------------------------------------


def test_inspect_clean_file_needs_nothing(tmp_path):
    path = write(tmp_path, "bank.csv",
                 "date,description,amount\n"
                 "2026-10-02,PAYROLL,3200.00\n"
                 "2026-10-03,GROCER,-86.40\n")
    data = inspect_csv.inspect(path)
    assert data["needs_rewrite"] == []
    assert data["beans_flags"] == []
    assert data["date_format"] == "YYYY-MM-DD (ISO)"
    assert data["amount_style"] == "single signed column"


def test_inspect_finds_header_below_preamble(tmp_path):
    path = write(tmp_path, "bank.csv",
                 "Account: **** 4412 Statement Period 10/01 - 10/31\n"
                 "Posting Date,Description,Debit,Credit,Balance\n"
                 "10/02/2026,PAYROLL,,3200.00,8412.55\n"
                 "10/03/2026,GROCER,86.40,,8326.15\n")
    data = inspect_csv.inspect(path)
    assert data["header_line"] == 2
    assert data["roles"]["date"] == "Posting Date"
    assert data["amount_style"] == "split debit/credit"
    assert any("preamble" in r for r in data["needs_rewrite"])
    assert any("debit/credit are split" in r for r in data["needs_rewrite"])
    # The running balance is what `reconcile --balance` wants.
    assert any("8326.15" in f for f in data["findings"])


def test_inspect_flags_non_iso_dates_as_structural(tmp_path):
    path = write(tmp_path, "bank.csv",
                 "date,description,amount\n"
                 "10/02/2026,PAYROLL,3200.00\n"
                 "10/13/2026,GROCER,-86.40\n")
    data = inspect_csv.inspect(path)
    assert data["date_format"] == "MM/DD/YYYY"     # the 13th settles it
    assert any("YYYY-MM-DD" in r for r in data["needs_rewrite"])


def test_inspect_reports_ambiguous_dates_as_ambiguous(tmp_path):
    path = write(tmp_path, "bank.csv",
                 "date,description,amount\n"
                 "05/06/2026,A,-1.00\n"
                 "07/08/2026,B,-2.00\n")
    assert "ambiguous" in inspect_csv.inspect(path)["date_format"]


def test_inspect_suggests_invert_for_a_card_export(tmp_path):
    path = write(tmp_path, "card.csv",
                 "Transaction Date,Description,Category,Amount\n"
                 "2026-10-04,DENTAL,Health,210.00\n"
                 "2026-10-09,AMAZON,Shopping,31.00\n"
                 "2026-10-11,COFFEE,Dining,6.25\n"
                 "2026-10-14,BOOKSTORE,Shopping,22.00\n"
                 "2026-10-22,PAYMENT THANK YOU,,-450.00\n")
    data = inspect_csv.inspect(path)
    assert "--invert" in data["beans_flags"]
    assert '--date-col "Transaction Date"' in data["beans_flags"]
    # The issuer's category column is a trap worth naming, not a convenience.
    assert any("second-guess" in f for f in data["findings"])


def test_inspect_flags_parenthesised_negatives(tmp_path):
    path = write(tmp_path, "card.csv",
                 "date,description,amount\n"
                 "2026-10-22,PAYMENT,(450.00)\n"
                 "2026-10-23,SHOP,31.00\n")
    data = inspect_csv.inspect(path)
    assert any("(45.00)" in r for r in data["needs_rewrite"])


# -- normalize_csv -----------------------------------------------------------


def test_normalize_splits_debit_credit_and_fixes_dates(tmp_path):
    path = write(tmp_path, "bank.csv",
                 "Account blurb\n"
                 "Posting Date,Description,Debit,Credit\n"
                 "10/02/2026,PAYROLL,,3200.00\n"
                 "10/03/2026,GROCER,86.40,\n"
                 "10/22/2026,XFER TO SAVINGS,500.00,\n")
    out = tmp_path / "work" / "norm.csv"
    result = normalize_csv.normalize(path, out)
    assert result["rows"] == 3
    assert result["date_format"] == "MM/DD/YYYY"
    lines = out.read_text().strip().splitlines()
    assert lines[0] == "date,description,amount"
    assert lines[1] == "2026-10-02,PAYROLL,3200.00"
    assert lines[2] == "2026-10-03,GROCER,-86.40"     # a debit is money out
    assert lines[3] == "2026-10-22,XFER TO SAVINGS,-500.00"


def test_normalize_respects_already_negative_debits(tmp_path):
    """Some banks write the debit column pre-signed; flipping it twice would
    turn a month of spending into a month of income."""
    path = write(tmp_path, "bank.csv",
                 "date,description,Debit,Credit\n"
                 "2026-10-03,GROCER,-86.40,\n")
    out = tmp_path / "norm.csv"
    normalize_csv.normalize(path, out)
    assert out.read_text().strip().splitlines()[1] == \
        "2026-10-03,GROCER,-86.40"


def test_normalize_inverts_a_card_export_and_drops_issuer_category(tmp_path):
    path = write(tmp_path, "card.csv",
                 "Transaction Date,Description,Category,Amount\n"
                 "10/04/2026,DENTAL,Health,210.00\n"
                 "10/22/2026,PAYMENT THANK YOU,,(450.00)\n")
    out = tmp_path / "norm.csv"
    result = normalize_csv.normalize(path, out, invert=True,
                                     drop_category=True)
    assert result["category"] == "dropped"
    lines = out.read_text().strip().splitlines()
    assert lines[0] == "date,description,amount"
    # A purchase leaves the card account; the payment arrives into it.
    assert lines[1] == "2026-10-04,DENTAL,-210.00"
    assert lines[2] == "2026-10-22,PAYMENT THANK YOU,450.00"


def test_normalize_keeps_a_category_column_when_asked(tmp_path):
    path = write(tmp_path, "card.csv",
                 "date,description,category,amount\n"
                 "2026-10-04,DENTAL,Expenses:Health,-210.00\n")
    out = tmp_path / "norm.csv"
    result = normalize_csv.normalize(path, out)
    assert result["category"] == "kept"
    assert out.read_text().splitlines()[0] == \
        "date,description,amount,category"


def test_normalize_handles_cr_dr_suffixes(tmp_path):
    path = write(tmp_path, "bank.csv",
                 "date,description,amount\n"
                 "2026-10-02,PAYROLL,3200.00 CR\n"
                 "2026-10-03,GROCER,86.40 DR\n")
    out = tmp_path / "norm.csv"
    normalize_csv.normalize(path, out)
    lines = out.read_text().strip().splitlines()
    assert lines[1].endswith("3200.00")
    assert lines[2].endswith("-86.40")


def test_normalize_drops_trailing_total_rows(tmp_path):
    """A summary row is not a transaction, and must not defeat date
    detection for the rows that are."""
    path = write(tmp_path, "bank.csv",
                 "date,description,amount\n"
                 "10/02/2026,PAYROLL,3200.00\n"
                 "10/03/2026,GROCER,-86.40\n"
                 "10/13/2026,FUEL,-48.10\n"
                 "TOTAL,,3065.50\n")
    out = tmp_path / "norm.csv"
    result = normalize_csv.normalize(path, out)
    assert result["rows"] == 3 and result["dropped"] == 1
    assert result["date_format"] == "MM/DD/YYYY"
    assert "TOTAL" not in out.read_text()


def test_normalize_refuses_a_file_of_mixed_date_formats(tmp_path):
    """No single format reads it, so there is nothing safe to choose."""
    body = "".join(f"10/{day:02d}/2026,ROW{day},-1.00\n" for day in range(1, 7))
    body += "".join(f"{day} Nov 2026,ROW{day},-1.00\n" for day in range(1, 7))
    path = write(tmp_path, "bank.csv", "date,description,amount\n" + body)
    with pytest.raises(normalize_csv.Unreadable, match="no known date format"):
        normalize_csv.normalize(path, tmp_path / "norm.csv")


def test_normalize_refuses_when_it_would_silently_lose_rows(tmp_path):
    """Format detection only samples the head of the file. If the tail turns
    out to be unreadable, writing the readable part and calling it done would
    drop transactions the user would never think to look for."""
    body = "".join(f"10/{day:02d}/2026,HEAD{day},-1.00\n" for day in range(1, 32))
    body += "".join(f"11/{day:02d}/2026,HEAD{day},-1.00\n" for day in range(1, 10))
    body += "".join(f"{day} Dec 2026,TAIL{day},-1.00\n" for day in range(1, 16))
    path = write(tmp_path, "bank.csv", "date,description,amount\n" + body)
    with pytest.raises(normalize_csv.Unreadable, match="could not be read"):
        normalize_csv.normalize(path, tmp_path / "norm.csv")
    # A refusal must leave nothing behind: a half-written file is exactly
    # what someone would import by mistake.
    assert not (tmp_path / "norm.csv").exists()


def test_normalize_refuses_ambiguous_dates_rather_than_guessing(tmp_path):
    """A guess here silently mis-dates the whole statement, so it must be a
    refusal the caller has to resolve, not a default."""
    path = write(tmp_path, "bank.csv",
                 "date,description,amount\n"
                 "05/06/2026,A,-1.00\n"
                 "07/08/2026,B,-2.00\n")
    with pytest.raises(normalize_csv.Unreadable, match="ambiguous"):
        normalize_csv.normalize(path, tmp_path / "norm.csv")
    # ...and a stated format resolves it.
    result = normalize_csv.normalize(path, tmp_path / "norm.csv",
                                     date_format="DD/MM/YYYY")
    assert result["rows"] == 2
    assert (tmp_path / "norm.csv").read_text().splitlines()[1] == \
        "2026-06-05,A,-1.00"


def test_normalize_will_not_clobber_an_existing_file(tmp_path):
    path = write(tmp_path, "bank.csv",
                 "date,description,amount\n2026-10-02,A,1.00\n")
    out = write(tmp_path, "norm.csv", "edited by hand\n")
    with pytest.raises(normalize_csv.Unreadable, match="already exists"):
        normalize_csv.normalize(path, out)
    assert out.read_text() == "edited by hand\n"


# -- triage ------------------------------------------------------------------


def prepared(tmp_path, body):
    return write(tmp_path, "prepared.csv",
                 "date,description,amount,category,confidence,basis\n" + body)


def test_triage_groups_one_merchant_across_store_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "chart_accounts", lambda: None)
    path = prepared(tmp_path,
                    "2026-10-18,STARBUCKS STORE 118,-6.25,,0.00,no match\n"
                    "2026-10-19,STARBUCKS STORE 992,-5.10,,0.00,no match\n"
                    "2026-10-21,STARBUCKS STORE 118,-7.40,,0.00,no match\n")
    data = triage.triage(path, 0.75)
    assert data["summary"]["merchants"] == 1
    group = data["merchants"][0]
    assert group["rows"] == 3
    assert group["rule_candidate"] is True          # recurring, unambiguous
    assert group["total"] == -18.75


def test_triage_separates_thin_from_conflicting_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "chart_accounts", lambda: None)
    path = prepared(
        tmp_path,
        "2026-10-05,AMAZON MKTPLACE 442,-31.00,Expenses:Shopping,0.64,"
        "20 prior: 14 Shopping / 6 Cloud\n"
        "2026-10-11,UNITED AIRLINES 900,-260.00,Expenses:Travel,0.60,3 prior\n")
    by_merchant = {g["example"]: g for g in triage.triage(path, 0.75)["merchants"]}
    # Same score, opposite meaning — and a rule is only right for one of them.
    assert by_merchant["AMAZON MKTPLACE 442"]["evidence"] == "conflicting"
    assert by_merchant["AMAZON MKTPLACE 442"]["rule_candidate"] is False
    assert by_merchant["UNITED AIRLINES 900"]["evidence"] == "thin"


def test_triage_flags_transfers_even_at_high_confidence(tmp_path, monkeypatch):
    """The trap confidence cannot catch: a well-evidenced wrong answer."""
    monkeypatch.setattr(triage, "chart_accounts", lambda: None)
    path = prepared(tmp_path,
                    "2026-10-12,ONLINE XFER TO SAVINGS,-500.00,"
                    "Expenses:Other,0.95,12 prior\n")
    group = triage.triage(path, 0.75)["merchants"][0]
    assert any("TRANSFER" in f for f in group["flags"])
    assert group["rule_candidate"] is False


def test_triage_flags_refunds(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "chart_accounts", lambda: None)
    path = prepared(tmp_path,
                    "2026-10-16,WHOLE FOODS REFUND,42.10,,0.00,no match\n")
    group = triage.triage(path, 0.75)["merchants"][0]
    assert any("REFUND" in f for f in group["flags"])


def test_triage_catches_accounts_absent_from_the_chart(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "chart_accounts",
                        lambda: {"Expenses:Food:Groceries", "Income:Salary"})
    path = prepared(tmp_path,
                    "2026-10-18,COFFEE,-6.25,Expenses:Coffee:Fancy,0.90,9 prior\n"
                    "2026-10-02,PAYROLL,3200.00,Income:Salary,1.00,"
                    '"rule ""PAYROLL"""\n')
    data = triage.triage(path, 0.75)
    assert data["unknown_accounts"] == ["Expenses:Coffee:Fancy"]
    assert data["chart_checked"] is True
    # A typo'd account surfaces here rather than as an import-time error.
    assert data["merchants"][0]["example"] == "COFFEE"


def test_triage_says_so_when_it_could_not_check_the_chart(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "chart_accounts", lambda: None)
    path = prepared(tmp_path,
                    "2026-10-02,PAYROLL,3200.00,Income:Salary,1.00,"
                    '"rule ""PAYROLL"""\n')
    data = triage.triage(path, 0.75)
    assert data["chart_checked"] is False
    assert "NOT validated" in triage.render(data)


def test_triage_leaves_settled_rows_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(triage, "chart_accounts", lambda: {"Income:Salary"})
    path = prepared(tmp_path,
                    "2026-10-02,PAYROLL,3200.00,Income:Salary,1.00,"
                    '"rule ""PAYROLL"""\n')
    data = triage.triage(path, 0.75)
    assert data["merchants"] == []
    assert data["summary"]["settled_rows"] == 1
    assert "Nothing needs review" in triage.render(data)


def test_triage_rejects_a_file_that_is_not_a_prepared_csv(tmp_path):
    path = write(tmp_path, "other.csv", "foo,bar\n1,2\n")
    with pytest.raises(SystemExit, match="prepared CSV"):
        triage.triage(path, 0.75)
