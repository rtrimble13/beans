from datetime import date

import pytest

from beans import matching, reconcile
from beans.importer import import_csv
from beans.matching import (
    DEFAULT_WINDOW,
    match_statement,
    normalize,
    read_statement,
    similarity,
    write_unmatched_csv,
)
from beans.utils import BeansError
from tests.conftest import post


def write_csv(tmp_path, rows, name="stmt.csv",
              header="date,description,amount"):
    path = tmp_path / name
    path.write_text(header + "\n" + "\n".join(rows) + "\n")
    return str(path)


def checking(led):
    return led.find_account("Assets:Checking")


def seed(led):
    """A month of activity, with rent booked to the 1st the way a
    recurring rule posts it."""
    post(led, date(2026, 5, 1), "Rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    post(led, date(2026, 5, 2), "PAYROLL DEPOSIT ACME",
         ("Assets:Checking", 320000), ("Income:Salary", -320000))
    post(led, date(2026, 5, 3), "Whole Foods",
         ("Expenses:Food:Groceries", 8640), ("Assets:Checking", -8640))


# -- normalization -----------------------------------------------------------


def test_normalize_strips_punctuation_and_reference_numbers():
    assert normalize("WHOLE FOODS MARKET #412") == "whole foods market"
    assert normalize("Shell Oil 57422") == "shell oil"
    assert normalize("") == ""


def test_similarity_containment_and_ratio():
    assert similarity("WHOLE FOODS MARKET #412", "Whole Foods") == 1.0
    assert similarity("Rent", "RENT ACH SUNRISE PROPERTIES") == 1.0
    assert similarity("Rent", "PAYROLL DEPOSIT") < 0.4
    assert similarity("anything", "") == 0.0


# -- reading the statement ---------------------------------------------------


def test_read_statement_parses_and_skips_blanks(tmp_path):
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL,3200.00",
                                ",,",
                                "2026-05-03,GROCERIES,-86.40",
                                "2026-05-04,ZERO ROW,0.00"])
    rows = read_statement(path, 2)
    assert [r.amount for r in rows] == [320000, -8640]
    assert [r.line for r in rows] == [2, 4]


def test_read_statement_inverts_for_card_exports(tmp_path):
    path = write_csv(tmp_path, ["2026-05-02,COFFEE,12.50"])
    assert read_statement(path, 2)[0].amount == 1250
    assert read_statement(path, 2, invert=True)[0].amount == -1250


def test_read_statement_remaps_columns(tmp_path):
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL,3200.00"],
                     header="when,memo,value")
    with pytest.raises(BeansError, match="column 'date' not found"):
        read_statement(path, 2)
    rows = read_statement(path, 2, date_col="when", desc_col="memo",
                          amount_col="value")
    assert [(r.date, r.description, r.amount) for r in rows] == [
        (date(2026, 5, 2), "PAYROLL", 320000)]


def test_read_statement_rejects_empty_and_missing(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("")
    with pytest.raises(BeansError, match="no header row"):
        read_statement(str(empty), 2)
    header_only = write_csv(tmp_path, [], name="head.csv")
    with pytest.raises(BeansError, match="no data rows"):
        read_statement(header_only, 2)
    with pytest.raises(BeansError, match="file not found"):
        read_statement(str(tmp_path / "nope.csv"), 2)


def test_read_statement_reports_the_offending_line(tmp_path):
    path = write_csv(tmp_path, ["2026-05-02,OK,1.00",
                                "not-a-date,BAD,2.00"])
    with pytest.raises(BeansError, match=r"stmt\.csv:3: invalid date"):
        read_statement(path, 2)


# -- matching ----------------------------------------------------------------


def test_exact_matches(led, tmp_path):
    seed(led)
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00",
                                "2026-05-03,WHOLE FOODS MARKET #412,-86.40"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    assert [m.tier for m in result.matched] == ["exact", "exact"]
    assert result.drifted == []
    assert result.bank_only == []


def test_recurring_entry_on_the_first_matches_a_later_posting(led, tmp_path):
    """The case that would otherwise flag constantly: rent booked to the
    1st, settled by the bank on the 4th."""
    seed(led)
    path = write_csv(tmp_path, ["2026-05-04,RENT ACH SUNRISE,-1800.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    assert len(result.drifted) == 1
    match = result.drifted[0]
    assert match.ledger.date == date(2026, 5, 1)
    assert match.date_drift == 3
    assert result.bank_only == []
    # the drifted pair is a match, so rent is not on the discrepancy side;
    # the month's other entries simply aren't on this one-line statement
    assert 1 not in [r.txn_id for r in result.ledger_only]
    assert {r.description for r in result.ledger_only} == {
        "PAYROLL DEPOSIT ACME", "Whole Foods"}


def test_month_boundary_recurring_matches_across_the_month(led, tmp_path):
    """June's rent, booked to 1 June, settled 29 May — it belongs to the
    May statement and must not show up as a discrepancy on either side."""
    post(led, date(2026, 6, 1), "Rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    path = write_csv(tmp_path, ["2026-05-29,RENT ACH SUNRISE,-1800.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    assert len(result.drifted) == 1
    assert result.drifted[0].date_drift == -3
    assert not result.bank_only and not result.ledger_only


def test_nearest_date_wins_when_several_could_match(led, tmp_path):
    """Two same-amount rent entries and two statement lines: each must
    pair with the nearer one, not the first one scanned."""
    post(led, date(2026, 5, 1), "Rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    post(led, date(2026, 6, 1), "Rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    path = write_csv(tmp_path, ["2026-05-03,RENT ACH,-1800.00",
                                "2026-05-30,RENT ACH,-1800.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    pairs = {m.statement.date: m.ledger.date for m in result.matched}
    assert pairs == {date(2026, 5, 3): date(2026, 5, 1),
                     date(2026, 5, 30): date(2026, 6, 1)}


def test_window_zero_requires_an_exact_date(led, tmp_path):
    seed(led)
    path = write_csv(tmp_path, ["2026-05-04,RENT ACH,-1800.00"])
    rows = read_statement(path, 2)
    assert match_statement(led, checking(led), rows, window=0).bank_only
    assert not match_statement(led, checking(led), rows, window=5).bank_only


def test_amount_difference_is_never_absorbed_by_fuzz(led, tmp_path):
    """A cent difference on the same merchant is a finding, not a match."""
    seed(led)
    path = write_csv(tmp_path, ["2026-05-03,WHOLE FOODS MARKET #412,-86.75"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    assert result.matched == []
    assert len(result.mismatched) == 1
    mismatch = result.mismatched[0]
    assert mismatch.tier == "mismatch"
    assert mismatch.amount_delta == -35
    assert mismatch.ledger.amount == -8640


def test_unrelated_descriptions_do_not_pair_as_mismatches(led, tmp_path):
    seed(led)
    path = write_csv(tmp_path, ["2026-05-03,CITY POWER AND LIGHT,-120.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    assert result.mismatched == []
    assert len(result.bank_only) == 1


def test_bank_only_and_outstanding(led, tmp_path):
    seed(led)
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00",
                                "2026-05-14,CITY POWER,-120.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    assert [r.description for r in result.bank_only] == ["CITY POWER"]
    # rent and groceries are in the ledger but not on this statement
    assert {r.description for r in result.outstanding} == {"Rent",
                                                           "Whole Foods"}
    assert result.cleared_missing == []


def test_cleared_but_absent_from_the_statement_is_its_own_class(led,
                                                               tmp_path):
    seed(led)
    led.set_cleared(checking(led), txn_ids=[1])  # rent, ticked off already
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    assert [r.txn_id for r in result.cleared_missing] == [1]
    assert 1 not in [r.txn_id for r in result.outstanding]


def test_matching_is_deterministic_regardless_of_row_order(led, tmp_path):
    seed(led)
    rows = ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00",
            "2026-05-03,WHOLE FOODS MARKET #412,-86.40",
            "2026-05-04,RENT ACH SUNRISE,-1800.00"]
    forward = match_statement(led, checking(led),
                              read_statement(write_csv(tmp_path, rows), 2))
    backward = match_statement(
        led, checking(led),
        read_statement(write_csv(tmp_path, list(reversed(rows)),
                                 name="rev.csv"), 2))

    def shape(result):
        return sorted((m.ledger.txn_id, m.statement.date, m.tier)
                      for m in result.matched)

    assert shape(forward) == shape(backward)


def test_matching_never_writes_to_the_ledger(led, tmp_path):
    seed(led)
    account = checking(led)
    before = led.cleared_balance(account)
    rows_before = len(led.postings_in_range(account, date(2026, 1, 1),
                                            date(2026, 12, 31)))
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00",
                                "2026-05-14,CITY POWER,-120.00"])
    match_statement(led, account, read_statement(path, 2))
    assert led.cleared_balance(account) == before == 0
    assert len(led.postings_in_range(account, date(2026, 1, 1),
                                     date(2026, 12, 31))) == rows_before


def test_foreign_accounts_are_refused_rather_than_silently_wrong(led,
                                                                tmp_path):
    led.add_account("Assets:Euro", led.find_account(
        "Assets:Checking").type, currency="EUR")
    path = write_csv(tmp_path, ["2026-05-02,SOMETHING,10.00"])
    with pytest.raises(BeansError, match="base-currency only"):
        match_statement(led, led.find_account("Assets:Euro"),
                        read_statement(path, 2))


def test_negative_window_is_rejected(led, tmp_path):
    seed(led)
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00"])
    with pytest.raises(BeansError, match="cannot be negative"):
        match_statement(led, checking(led), read_statement(path, 2),
                        window=-1)


# -- the editable hand-off file ----------------------------------------------


def test_unmatched_csv_round_trips_through_import(led, tmp_path):
    seed(led)
    led.add_import_rule("CITY POWER", led.find_account(
        "Expenses:Housing:Utilities"))
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00",
                                "2026-05-14,CITY POWER & LIGHT,-120.00"])
    account = checking(led)
    result = match_statement(led, account, read_statement(path, 2))
    out = str(tmp_path / "new.csv")
    assert write_unmatched_csv(led, result, out) == 1

    text = open(out).read()
    assert text.splitlines()[0] == "date,description,amount,category"
    # the rule pre-fills the category; no editing needed for this row
    assert "Expenses:Housing:Utilities" in text

    # and the file imports as-is, with no column flags and no fallback
    imported = import_csv(led, out, account)
    assert len(imported["imported"]) == 1
    # re-running the reconciliation now finds nothing missing
    again = match_statement(led, account, read_statement(path, 2))
    assert again.bank_only == []


def test_unmatched_csv_leaves_unknown_categories_blank(led, tmp_path):
    seed(led)
    path = write_csv(tmp_path, ["2026-05-14,MYSTERY CHARGE,-120.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    out = str(tmp_path / "new.csv")
    write_unmatched_csv(led, result, out)
    assert open(out).read().splitlines()[1] == \
        "2026-05-14,MYSTERY CHARGE,-120.00,"


def test_unmatched_csv_is_written_in_import_convention(led, tmp_path):
    """A card export read with --invert must be written back out
    un-inverted, so the file imports without the flag."""
    card = led.find_account("Liabilities:Credit Card")
    path = write_csv(tmp_path, ["2026-05-11,ANNUAL FEE,95.00"])
    rows = read_statement(path, 2, invert=True)
    result = match_statement(led, card, rows)
    out = str(tmp_path / "card.csv")
    write_unmatched_csv(led, result, out)
    assert "-95.00" in open(out).read()
    import_csv(led, out, card, default_category=led.find_account(
        "Expenses:Other"))
    # a purchase increases what is owed on the card
    assert led.balances()[card.id] == -9500


def test_unmatched_csv_writes_a_header_even_with_no_rows(led, tmp_path):
    seed(led)
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    out = str(tmp_path / "empty.csv")
    assert write_unmatched_csv(led, result, out) == 0
    assert open(out).read().strip() == "date,description,amount,category"


# -- the report --------------------------------------------------------------


def test_statement_report_folds_in_the_balance_tie_out(led, tmp_path):
    seed(led)
    account = checking(led)
    led.set_cleared(account, through=date(2026, 5, 31))
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00"])
    result = match_statement(led, account, read_statement(path, 2))
    data = reconcile.statement_report(led, account, result, path, 131360,
                                      date(2026, 5, 31))
    assert data["cleared_balance"] == 131360
    assert data["difference"] == 0
    assert data["summary"]["matched"] == 1
    text = reconcile.render_statement_reconcile(data, 2, "$")
    assert "Nothing was written to the ledger" in text


def test_statement_report_without_a_balance(led, tmp_path):
    seed(led)
    account = checking(led)
    path = write_csv(tmp_path, ["2026-05-02,PAYROLL DEPOSIT ACME,3200.00"])
    result = match_statement(led, account, read_statement(path, 2))
    data = reconcile.statement_report(led, account, result, path, None,
                                      date(2026, 5, 31))
    assert data["statement_balance"] is None and data["difference"] is None
    text = reconcile.render_statement_reconcile(data, 2, "$")
    assert "Statement balance" not in text
    assert "Matched" in text


def test_report_amounts_read_naturally_for_a_credit_card(led, tmp_path):
    card = led.find_account("Liabilities:Credit Card")
    post(led, date(2026, 5, 6), "Gas",
         ("Expenses:Transportation", 4810), ("Liabilities:Credit Card",
                                             -4810))
    path = write_csv(tmp_path, ["2026-05-06,SHELL OIL 57422,48.10",
                                "2026-05-11,ANNUAL FEE,95.00"])
    result = match_statement(led, card, read_statement(path, 2, invert=True))
    data = reconcile.statement_report(led, card, result, path, None,
                                      date(2026, 5, 31))
    # a purchase reads positive on a liability, as elsewhere in beans
    assert data["bank_only"][0]["amount"] == 9500


def test_render_flags_a_probable_split_or_combine(led, tmp_path):
    post(led, date(2026, 5, 10), "Utilities",
         ("Expenses:Housing:Utilities", 12000), ("Assets:Checking", -12000))
    account = checking(led)
    path = write_csv(tmp_path, ["2026-05-10,POWER CO,-70.00",
                                "2026-05-10,WATER CO,-50.00"])
    result = match_statement(led, account, read_statement(path, 2))
    data = reconcile.statement_report(led, account, result, path, None,
                                      date(2026, 5, 31))
    text = reconcile.render_statement_reconcile(data, 2, "$")
    assert "splits or combines" in text


def test_unmatched_csv_refuses_to_clobber_an_edited_file(led, tmp_path):
    """The file exists to be edited between being written and being
    imported — overwriting one silently would throw that work away."""
    seed(led)
    path = write_csv(tmp_path, ["2026-05-14,MYSTERY CHARGE,-120.00"])
    result = match_statement(led, checking(led), read_statement(path, 2))
    out = tmp_path / "new.csv"
    write_unmatched_csv(led, result, str(out))
    out.write_text("date,description,amount,category\n"
                   "2026-05-14,MYSTERY CHARGE,-120.00,Expenses:Other\n")
    with pytest.raises(BeansError, match="already exists"):
        write_unmatched_csv(led, result, str(out))
    assert "Expenses:Other" in out.read_text()  # the edit survived
    write_unmatched_csv(led, result, str(out), force=True)
    assert "Expenses:Other" not in out.read_text()
