"""Tests for the skill helper scripts under `.claude/skills/`.

`beans-import`'s scripts are plain CSV transforms over text, so they test
cheaply — and they are worth testing because they run against real statement
exports where a misread sign or an off-by-one date silently corrupts a month
of books.

`beans-report`'s scripts carry the arithmetic behind a trend briefing. The
same argument applies with more force: a classifier that calls one vet bill a
trend, or that quietly includes a four-day-old month in a twelve-month series,
produces a confident and completely wrong story about someone's money. The
numbers below are asserted exactly.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / ".claude" / "skills"
SCRIPTS = SKILLS / "beans-import" / "scripts"
REPORT_SCRIPTS = SKILLS / "beans-report" / "scripts"


def _load(name, scripts=SCRIPTS):
    """Import a script by path — it is not on the package path."""
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inspect_csv = _load("inspect_csv")
normalize_csv = _load("normalize_csv")
triage = _load("triage")

beans_io = _load("beans_io", REPORT_SCRIPTS)
series = _load("series", REPORT_SCRIPTS)
trend = _load("trend", REPORT_SCRIPTS)
preflight = _load("preflight", REPORT_SCRIPTS)


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


# ============================================================================
# beans-report
# ============================================================================

def money(values):
    """A period series as beans would emit it — major-unit decimal strings."""
    return [None if value is None else f"{Decimal(value):.2f}"
            for value in values]


# -- beans_io: the read-only guardrail ---------------------------------------

@pytest.mark.parametrize("argv", [
    ["report", "income", "--period", "2026-08"],
    ["report", "is", "--json"],
    ["analyze"],
    ["networth", "--months", "12"],
    ["budget", "report"],
    ["account", "list", "--type", "expense"],
    ["recur", "list"],
    ["status"],
    ["register", "Assets:Checking"],
    ["tx", "list", "--period", "all"],
])
def test_read_only_commands_are_allowed(argv):
    beans_io.assert_read_only(argv)


@pytest.mark.parametrize("argv", [
    ["import", "statement.csv"],
    ["tx", "add", "--date", "2026-01-01"],
    ["tx", "void", "3"],
    ["spend", "10", "Groceries"],
    ["budget", "set", "Groceries", "500"],
    ["recur", "run"],
    ["period", "close", "2026-08"],
    ["rule", "add", "MARKET", "Expenses:Food:Groceries"],
    ["undo"],
    ["invest", "buy", "VTI", "1", "200"],
])
def test_write_commands_are_refused(argv):
    """The skill is read-only. That is enforced here, not merely promised in
    SKILL.md, because a typo must not be able to post a transaction."""
    with pytest.raises(beans_io.NotReadOnly):
        beans_io.assert_read_only(argv)


def test_a_write_hidden_behind_options_is_still_refused():
    with pytest.raises(beans_io.NotReadOnly):
        beans_io.assert_read_only(["--json", "import", "x.csv"])


def test_build_argv_places_file_before_the_subcommand():
    # `--file` is a global option; after the subcommand argparse rejects it.
    argv = beans_io.build_argv(["report", "income"], ledger="/tmp/l.db")
    assert argv[:4] == ["beans", "--file", "/tmp/l.db", "report"]
    assert argv[-1] == "--json"


def test_build_argv_does_not_duplicate_an_existing_json_flag():
    argv = beans_io.build_argv(["analyze", "--json"])
    assert argv.count("--json") == 1


def test_build_argv_refuses_a_write():
    with pytest.raises(beans_io.NotReadOnly):
        beans_io.build_argv(["import", "x.csv"])


# -- beans_io: the partial-period rule ---------------------------------------

@pytest.mark.parametrize("today,expected", [
    (date(2026, 9, 4), "2026-08"),    # four days in — September is a stub
    (date(2026, 9, 30), "2026-09"),   # the last day: September has elapsed
    (date(2026, 1, 1), "2025-12"),    # new year rolls back a year
    (date(2026, 2, 28), "2026-02"),   # short month, non-leap
    (date(2024, 2, 29), "2024-02"),   # short month, leap
    (date(2024, 2, 28), "2024-01"),   # leap year: the 28th is not month end
])
def test_last_complete_month_excludes_a_period_in_progress(today, expected):
    assert beans_io.last_complete(today, "month") == expected


@pytest.mark.parametrize("today,expected", [
    (date(2026, 9, 4), "2026-Q2"),
    (date(2026, 9, 30), "2026-Q3"),
    (date(2026, 1, 15), "2025-Q4"),
])
def test_last_complete_quarter_excludes_a_period_in_progress(today, expected):
    assert beans_io.last_complete(today, "quarter") == expected


def test_period_keys_run_oldest_first_and_roll_over_the_year():
    assert beans_io.period_keys("2026-02", 4, "month") == [
        "2025-11", "2025-12", "2026-01", "2026-02"]
    assert beans_io.period_keys("2026-Q1", 3, "quarter") == [
        "2025-Q3", "2025-Q4", "2026-Q1"]


def test_dec_treats_a_missing_account_as_a_real_zero():
    assert beans_io.dec(None) == 0
    assert beans_io.dec("") == 0
    assert beans_io.dec("12.34") == Decimal("12.34")


def test_signed_str_always_carries_a_sign():
    assert beans_io.signed_str(Decimal("12")) == "+12.00"
    assert beans_io.signed_str(Decimal("-12")) == "-12.00"
    assert beans_io.money_str(Decimal("12")) == "12.00"


# -- trend: robust statistics ------------------------------------------------

def test_median_of_even_and_odd_series():
    assert trend.median([Decimal(n) for n in (3, 1, 2)]) == 2
    assert trend.median([Decimal(n) for n in (4, 1, 2, 3)]) == Decimal("2.5")
    assert trend.median([]) is None


def test_theil_sen_recovers_an_exact_slope():
    points = [(i, Decimal(100 + 7 * i)) for i in range(8)]
    assert trend.theil_sen(points) == 7


def test_theil_sen_ignores_a_single_wild_outlier():
    """The whole reason for a median-of-slopes fit: one vet bill must not
    become a trend."""
    values = [Decimal(100)] * 8
    values[3] = Decimal(5000)
    points = list(enumerate(values))
    assert abs(trend.theil_sen(points)) == 0


# -- trend: classification ---------------------------------------------------

def test_a_flat_series_is_stable():
    result = trend.classify(money([1800] * 12))
    assert result["classification"] == "stable"
    assert result["change"] == "+0.00"


def test_a_steady_climb_is_drift_with_the_exact_total_change():
    result = trend.classify(money([500 + 22 * i for i in range(12)]))
    assert result["classification"] == "drift"
    assert result["direction"] == "up"
    assert result["change"] == "+242.00"        # 22 × 11 elapsed periods
    assert result["per_period"] == "+22.00"
    assert result["annualized"] == "+264.00"


def test_drift_survives_noise_around_the_line():
    noisy = [500 + 22 * i + (13 if i % 2 else -11) for i in range(12)]
    result = trend.classify(money(noisy))
    assert result["classification"] == "drift"
    assert result["direction"] == "up"


def test_a_falling_series_drifts_down():
    result = trend.classify(money([900 - 30 * i for i in range(12)]))
    assert result["classification"] == "drift"
    assert result["direction"] == "down"
    assert result["change"] == "-330.00"


def test_a_single_spike_is_a_one_off_not_a_trend():
    values = [200, 210, 205, 195, 2200, 208, 199, 203, 207, 201, 198, 206]
    result = trend.classify(money(values))
    assert result["classification"] == "one-off"
    assert result["direction"] == "up"
    assert len(result["outliers"]) == 1


def test_a_clean_step_is_a_step_and_reports_both_levels():
    result = trend.classify(money([1800] * 6 + [1950] * 6))
    assert result["classification"] == "step"
    assert result["before"] == "1800.00"
    assert result["after"] == "1950.00"
    assert result["change"] == "+150.00"
    assert result["break_index"] == 6


def test_a_subscription_that_stopped_is_reported_as_stopped():
    """The finding beans itself cannot make: a standing payment that quietly
    lapsed. Reported as `stopped`, not as a flattering drop in spending."""
    result = trend.classify(money([15] * 8 + [0] * 4))
    assert result["classification"] == "stopped"
    assert result["zero_periods"] == 4
    assert result["prior_typical"] == "15.00"


def test_a_new_recurring_expense_is_reported_as_new():
    result = trend.classify(money([0] * 4 + [45] * 8))
    assert result["classification"] == "new"
    assert result["absent_periods"] == 4
    assert result["change"] == "+45.00"


def test_an_all_zero_series_is_stable_not_stopped():
    assert trend.classify(money([0] * 12))["classification"] == "stable"


def test_too_few_periods_refuses_to_classify():
    result = trend.classify(money([100, 120]))
    assert result["classification"] == "insufficient-data"
    assert "2 usable periods" in result["reason"]


def test_failed_periods_are_gaps_not_zeros():
    """A command that failed must never be read as 'spent nothing'."""
    result = trend.classify(["100.00", None, "140.00", None, "180.00",
                             "200.00"])
    assert result["periods_used"] == 4
    assert result["periods_given"] == 6
    assert result["classification"] == "drift"


# -- trend: materiality ------------------------------------------------------

def _series(accounts, income=("6000",) * 12, decimals=2):
    periods = [f"2026-{month:02d}" for month in range(1, 13)]
    return {
        "report": "beans-report/series",
        "grain": "month", "decimals": decimals, "currency": "USD",
        "periods": periods, "window": {"first": periods[0],
                                       "last": periods[-1]},
        "totals": {"total_income": list(income),
                   "total_expenses": ["1000.00"] * 12,
                   "net_income": ["5000.00"] * 12},
        "accounts": accounts,
    }


def test_a_move_below_the_materiality_floor_is_not_reported():
    """1% of 6000 is 60; a 22.00 total drift is real but not worth a line in
    a briefing. It is counted, not printed."""
    data = _series({"Expenses:Coffee": money([10 + 2 * i for i in range(12)])})
    result = trend.analyze(data, floor_pct=Decimal("1"),
                           floor_abs=Decimal("0"), min_periods=6)
    assert result["materiality"] == "60.00"
    assert [f["name"] for f in result["findings"]] == []
    assert result["immaterial_count"] == 1


def test_a_move_above_the_floor_is_reported_with_its_income_share():
    data = _series({"Expenses:Food:Groceries":
                    money([500 + 22 * i for i in range(12)])})
    result = trend.analyze(data, floor_pct=Decimal("1"),
                           floor_abs=Decimal("0"), min_periods=6)
    names = [f["name"] for f in result["findings"]]
    assert "Expenses:Food:Groceries" in names
    finding = next(f for f in result["findings"]
                   if f["name"] == "Expenses:Food:Groceries")
    assert finding["change"] == "+242.00"
    assert finding["pct_of_typical_income"] == "4.0"     # 242 / 6000


def test_findings_are_ranked_by_magnitude():
    data = _series({
        "Expenses:Small": money([100 + 10 * i for i in range(12)]),
        "Expenses:Large": money([100 + 40 * i for i in range(12)]),
    })
    result = trend.analyze(data, floor_pct=Decimal("1"),
                           floor_abs=Decimal("0"), min_periods=6)
    assert [f["name"] for f in result["findings"]][:2] == [
        "Expenses:Large", "Expenses:Small"]


def test_an_absolute_floor_also_suppresses_findings():
    data = _series({"Expenses:Food:Groceries":
                    money([500 + 22 * i for i in range(12)])})
    result = trend.analyze(data, floor_pct=Decimal("0"),
                           floor_abs=Decimal("500"), min_periods=6)
    assert result["findings"] == []


def test_scope_limits_which_accounts_are_read():
    data = _series({
        "Expenses:Food:Groceries": money([500 + 22 * i for i in range(12)]),
        "Income:Bonus": money([0] * 4 + [900] * 8),
    })
    expenses = trend.analyze(data, scope="expenses", floor_pct=Decimal("1"),
                             floor_abs=Decimal("0"), min_periods=6)
    assert all(not f["name"].startswith("Income:")
               for f in expenses["findings"])
    income = trend.analyze(data, scope="income", floor_pct=Decimal("1"),
                           floor_abs=Decimal("0"), min_periods=6)
    assert [f["name"] for f in income["findings"]] == ["Income:Bonus"]


def test_the_partial_period_exclusion_is_carried_into_the_trend_report():
    data = _series({})
    data["excluded_partial"] = "2027-01"
    result = trend.analyze(data, floor_pct=Decimal("1"),
                           floor_abs=Decimal("0"), min_periods=6)
    assert result["excluded_partial"] == "2027-01"


# -- series: assembling the periods ------------------------------------------

def test_months_between_and_quarter_anchoring():
    assert series.months_between("2025-09", "2026-09") == 12
    assert series.months_between("2026-01", "2026-01") == 0
    assert series.anchor_month("2026-Q2", "quarter") == "2026-06"
    assert series.anchor_month("2026-05", "month") == "2026-05"


def _fake_beans(statements, failures=()):
    """Stand in for an OLDER `beans` CLI — one without `report trend` — so
    these tests exercise the per-period fallback assembly. Returns a canned
    income statement per period, or raises for periods in ``failures``."""
    def run_json(argv, **_kwargs):
        if argv[:2] == ["report", "trend"]:
            raise beans_io.BeansCommandError(
                argv, 2, "argument subcommand: invalid choice: 'trend'")
        if argv[0] == "networth":
            return {"rows": []}
        period = argv[argv.index("--period") + 1]
        if period in failures:
            raise beans_io.BeansCommandError(argv, 1, "boom")
        return statements[period]
    return run_json


def test_gather_treats_an_account_missing_from_a_period_as_zero(monkeypatch):
    pay = {"Income:Salary": "10.00"}
    statements = {
        "2026-07": {"period": "July 2026", "income": pay,
                    "expenses": {"Expenses:Food:Groceries": "5.00"},
                    "total_income": "10.00", "total_expenses": "5.00",
                    "net_income": "5.00"},
        # No groceries at all in August — a real zero, not a gap.
        "2026-08": {"period": "August 2026", "income": pay,
                    "expenses": {}, "total_income": "10.00",
                    "total_expenses": "0.00", "net_income": "10.00"},
    }
    monkeypatch.setattr(series.bio, "run_json", _fake_beans(statements))
    monkeypatch.setattr(series, "read_config",
                        lambda *a, **k: {"currency": "USD", "decimals": 2})
    data = series.gather(count=2, grain="month", end_key="2026-08",
                         beans="beans", ledger=None, want_ratios=False,
                         want_budgets=False, today=date(2026, 9, 4))
    assert data["accounts"]["Expenses:Food:Groceries"] == ["5.00", "0.00"]


def test_gather_records_a_failed_period_as_a_gap_and_an_error(monkeypatch):
    statements = {
        "2026-08": {"period": "August 2026", "income": {},
                    "expenses": {"Expenses:Food:Groceries": "5.00"},
                    "total_income": "0.00", "total_expenses": "5.00",
                    "net_income": "-5.00"},
    }
    monkeypatch.setattr(series.bio, "run_json",
                        _fake_beans(statements, failures={"2026-07"}))
    monkeypatch.setattr(series, "read_config",
                        lambda *a, **k: {"currency": "USD", "decimals": 2})
    data = series.gather(count=2, grain="month", end_key="2026-08",
                         beans="beans", ledger=None, want_ratios=False,
                         want_budgets=False, today=date(2026, 9, 4))
    assert data["accounts"]["Expenses:Food:Groceries"] == [None, "5.00"]
    assert data["totals"]["total_expenses"] == [None, "5.00"]
    assert data["errors"][0]["period"] == "2026-07"


def test_gather_flags_a_structurally_empty_period(monkeypatch):
    blank = {"period": "x", "income": {}, "expenses": {},
             "total_income": "0.00", "total_expenses": "0.00",
             "net_income": "0.00"}
    live = {"period": "y", "income": {"Income:Salary": "10.00"},
            "expenses": {}, "total_income": "10.00",
            "total_expenses": "0.00", "net_income": "10.00"}
    monkeypatch.setattr(series.bio, "run_json",
                        _fake_beans({"2026-07": blank, "2026-08": live}))
    monkeypatch.setattr(series, "read_config",
                        lambda *a, **k: {"currency": "USD", "decimals": 2})
    data = series.gather(count=2, grain="month", end_key="2026-08",
                         beans="beans", ledger=None, want_ratios=False,
                         want_budgets=False, today=date(2026, 9, 4))
    assert data["empty_periods"] == ["2026-07"]


def test_read_config_parses_the_plain_text_config_listing(monkeypatch):
    monkeypatch.setattr(
        series.bio, "run_text",
        lambda *a, **k: "currency = EUR\ndecimals = 0\ncreated = 2026-01-01\n")
    assert series.read_config("beans", None) == {"currency": "EUR",
                                                 "decimals": 0}


# -- preflight ---------------------------------------------------------------

def test_period_day_bounds_for_months_and_quarters():
    assert preflight._first_day("2026-02", "month") == "2026-02-01"
    assert preflight._last_day("2026-02", "month") == "2026-02-28"
    assert preflight._last_day("2024-02", "month") == "2024-02-29"
    assert preflight._first_day("2026-Q2", "quarter") == "2026-04-01"
    assert preflight._last_day("2026-Q2", "quarter") == "2026-06-30"


def test_default_ledger_prefers_the_explicit_path(monkeypatch):
    monkeypatch.setenv("BEANS_LEDGER", "/env/ledger.db")
    assert preflight.default_ledger("/explicit.db") == "/explicit.db"
    assert preflight.default_ledger(None) == "/env/ledger.db"


# -- end to end against a real ledger ----------------------------------------

@pytest.fixture
def trending_ledger(tmp_path):
    """A ledger whose grocery spend climbs by a known amount every month, with
    rent flat and one deliberate one-off."""
    from beans.cli import main
    path = str(tmp_path / "trend.db")
    assert main(["-f", path, "init"]) == 0
    assert main(["-f", path, "tx", "add", "--date", "2025-08-01",
                 "--desc", "Opening", "--post", "Assets:Checking", "20000",
                 "--post", "Equity:Opening Balances"]) == 0
    for index in range(12):
        year, month = (2025, 9 + index) if index < 4 else (2026, index - 3)
        stamp = f"{year}-{month:02d}"
        assert main(["-f", path, "earn", "6000", "Salary",
                     "--date", f"{stamp}-15"]) == 0
        assert main(["-f", path, "spend", "1800", "Rent",
                     "--date", f"{stamp}-02"]) == 0
        assert main(["-f", path, "spend", str(500 + 20 * index), "Groceries",
                     "--date", f"{stamp}-08"]) == 0
    # One genuine one-off, big enough to dominate an average but not a median.
    assert main(["-f", path, "spend", "2400", "Health",
                 "--date", "2026-03-11"]) == 0
    return path


@pytest.mark.skipif(shutil.which("beans") is None,
                    reason="the `beans` console script is not installed")
def test_end_to_end_pipeline_against_a_real_ledger(trending_ledger, tmp_path):
    """The whole point, exercised for real: gather twelve months, classify
    them, and get back the drift that was seeded and the spike that was not a
    trend — with the part-elapsed month left out."""
    out = tmp_path / "series.json"
    assert series.main(["--months", "12", "--as-of", "2026-09-04",
                        "-f", trending_ledger, "-o", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["periods"][0] == "2025-09"
    assert data["periods"][-1] == "2026-08"
    assert data["excluded_partial"] == "2026-09"
    assert "2026-09" not in data["periods"]
    assert data["accounts"]["Expenses:Food:Groceries"][0] == "500.00"
    assert data["accounts"]["Expenses:Food:Groceries"][-1] == "720.00"

    result = trend.analyze(data, floor_pct=Decimal("1"),
                           floor_abs=Decimal("0"), min_periods=6)
    by_name = {f["name"]: f for f in result["findings"]}
    groceries = by_name["Expenses:Food:Groceries"]
    assert groceries["classification"] == "drift"
    assert groceries["change"] == "+220.00"          # 20 × 11 periods
    assert by_name["Expenses:Health"]["classification"] == "one-off"
    # Rent never moved, so it must not appear at all.
    assert "Expenses:Housing:Rent" not in by_name


@pytest.mark.skipif(shutil.which("beans") is None,
                    reason="the `beans` console script is not installed")
def test_preflight_blocks_a_ledger_whose_spending_is_uncategorized(tmp_path):
    from beans.cli import main
    path = str(tmp_path / "messy.db")
    assert main(["-f", path, "init"]) == 0
    assert main(["-f", path, "tx", "add", "--date", "2026-01-01",
                 "--desc", "Opening", "--post", "Assets:Checking", "9000",
                 "--post", "Equity:Opening Balances"]) == 0
    for month in range(1, 9):
        assert main(["-f", path, "earn", "4000", "Salary",
                     "--date", f"2026-{month:02d}-15"]) == 0
        assert main(["-f", path, "spend", "900", "Expenses:Other",
                     "--date", f"2026-{month:02d}-10"]) == 0
        assert main(["-f", path, "spend", "200", "Groceries",
                     "--date", f"2026-{month:02d}-12"]) == 0
    report = preflight.check("beans", path, 8, "month", date(2026, 9, 4),
                             Decimal("25"))
    assert report["ok"] is False
    assert report["uncategorized"]["pct"] == "81.8"
    assert any("Expenses:Other" in blocker for blocker in report["blockers"])


@pytest.mark.skipif(shutil.which("beans") is None,
                    reason="the `beans` console script is not installed")
def test_series_refuses_to_run_a_write_command(tmp_path, monkeypatch):
    """Defence in depth: even if a caller smuggles a write into the argv the
    script builds, beans_io stops it before a subprocess starts."""
    with pytest.raises(beans_io.NotReadOnly):
        beans_io.run_json(["period", "close", "2026-08"], ledger="/tmp/x.db")


def test_a_single_payment_is_a_one_off_not_a_cancelled_subscription():
    """`stopped` claims a standing payment lapsed. One doctor's bill in an
    otherwise empty year is not that, and saying so would invent a story."""
    result = trend.classify(money([0] * 6 + [2400] + [0] * 5))
    assert result["classification"] == "one-off"


def test_a_single_latest_payment_is_not_yet_a_new_recurring_expense():
    result = trend.classify(money([0] * 11 + [45]))
    assert result["classification"] != "new"


# -- series: the native `beans report trend` fast path -----------------------

def test_native_trend_is_used_when_the_command_exists(monkeypatch):
    calls = []

    def run_json(argv, **_kwargs):
        calls.append(argv)
        if argv[:2] == ["report", "trend"]:
            return {"periods": ["2026-07", "2026-08"],
                    "rows": [{"income": "10.00", "expenses": "4.00",
                              "net_income": "6.00"},
                             {"income": "10.00", "expenses": "5.00",
                              "net_income": "5.00"}],
                    "accounts": [{"account": "Expenses:Food:Groceries",
                                  "amounts": ["4.00", "5.00"]}]}
        return {"rows": []}

    monkeypatch.setattr(series.bio, "run_json", run_json)
    monkeypatch.setattr(series, "read_config",
                        lambda *a, **k: {"currency": "USD", "decimals": 2})
    data = series.gather(count=2, grain="month", end_key="2026-08",
                         beans="beans", ledger=None, want_ratios=False,
                         want_budgets=False, today=date(2026, 9, 4))
    assert data["source"] == "beans report trend"
    assert data["accounts"]["Expenses:Food:Groceries"] == ["4.00", "5.00"]
    assert data["totals"]["total_expenses"] == ["4.00", "5.00"]
    # One call for the series, not one per period.
    assert [c for c in calls if c[:2] == ["report", "income"]] == []


def test_series_falls_back_on_an_older_beans(monkeypatch):
    """`report trend` landed in beans 1.1. Against an older one the script
    must still work, producing the same shape the classifier expects."""
    statements = {
        "2026-07": {"period": "July 2026", "income": {"Income:Salary": "10.00"},
                    "expenses": {"Expenses:Food:Groceries": "4.00"},
                    "total_income": "10.00", "total_expenses": "4.00",
                    "net_income": "6.00"},
        "2026-08": {"period": "August 2026",
                    "income": {"Income:Salary": "10.00"},
                    "expenses": {"Expenses:Food:Groceries": "5.00"},
                    "total_income": "10.00", "total_expenses": "5.00",
                    "net_income": "5.00"},
    }

    def run_json(argv, **_kwargs):
        if argv[:2] == ["report", "trend"]:
            raise beans_io.BeansCommandError(
                argv, 2, "argument subcommand: invalid choice: 'trend'")
        if argv[0] == "networth":
            return {"rows": []}
        return statements[argv[argv.index("--period") + 1]]

    monkeypatch.setattr(series.bio, "run_json", run_json)
    monkeypatch.setattr(series, "read_config",
                        lambda *a, **k: {"currency": "USD", "decimals": 2})
    data = series.gather(count=2, grain="month", end_key="2026-08",
                         beans="beans", ledger=None, want_ratios=False,
                         want_budgets=False, today=date(2026, 9, 4))
    assert "older beans" in data["source"]
    assert data["accounts"]["Expenses:Food:Groceries"] == ["4.00", "5.00"]
    assert data["totals"]["net_income"] == ["6.00", "5.00"]
    assert data.get("errors") is None


def test_a_real_trend_failure_is_recorded_not_silently_worked_around():
    """Only 'invalid choice' means the command is missing. Anything else is a
    genuine problem, and quietly taking the slow path would bury it."""
    errors = []
    def run_json(argv, **_kwargs):
        raise beans_io.BeansCommandError(argv, 1, "database is locked")
    import types
    fake = types.SimpleNamespace(run_json=run_json,
                                 BeansCommandError=beans_io.BeansCommandError)
    original = series.bio
    series.bio = fake
    try:
        assert series._native_trend(["2026-08"], "month", "beans", None,
                                    errors) is None
    finally:
        series.bio = original
    assert errors and "database is locked" in errors[0]["error"]


def test_a_trend_answering_a_different_window_is_refused(monkeypatch):
    errors = []
    monkeypatch.setattr(series.bio, "run_json",
                        lambda argv, **k: {"periods": ["2020-01"]})
    assert series._native_trend(["2026-07", "2026-08"], "month", "beans",
                                None, errors) is None
    assert "unexpected window" in errors[0]["error"]


@pytest.mark.skipif(shutil.which("beans") is None,
                    reason="the `beans` console script is not installed")
def test_both_paths_produce_the_same_series(trending_ledger, tmp_path):
    """The fallback is only safe if it is indistinguishable. Run a real
    ledger through both and require identical output."""
    fast = tmp_path / "fast.json"
    slow = tmp_path / "slow.json"
    shim = tmp_path / "beans-old"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "for a in \"$@\"; do\n"
        "  if [ \"$a\" = trend ]; then\n"
        "    echo \"error: argument subcommand: invalid choice: 'trend'\" >&2\n"
        "    exit 2\n"
        "  fi\n"
        "done\n"
        f"exec {shutil.which('beans')} \"$@\"\n")
    shim.chmod(0o755)

    common = ["--months", "12", "--as-of", "2026-09-04", "-f", trending_ledger]
    assert series.main(common + ["-o", str(fast)]) == 0
    assert series.main(common + ["--beans", str(shim), "-o", str(slow)]) == 0
    a, b = json.loads(fast.read_text()), json.loads(slow.read_text())
    assert a["source"] == "beans report trend"
    assert "older beans" in b["source"]
    for key in ("periods", "window", "excluded_partial", "accounts",
                "totals", "empty_periods", "net_worth", "decimals"):
        assert a[key] == b[key], key
