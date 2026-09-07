from datetime import date, timedelta

import pytest

from beans import analysis, archive, forecast, reports, status
from beans.cli import main
from beans.ledger import Ledger
from beans.models import AccountType, Posting
from beans.utils import BeansError

# The cutover used throughout: far enough back that `plan` accepts it and
# the archived span is several whole months.
CUT = date(2025, 12, 31)


def post(led, when, desc, *legs, payee="", tags=None):
    postings = [
        Posting(account_id=led.find_account(name).id, amount=amount)
        for name, amount in legs
    ]
    return led.add_transaction(when, desc, postings, payee=payee,
                               tags=tags or [])


def seed(led, months=18, start=date(2025, 1, 1)):
    """A household with a salary, rent, groceries and a savings sweep,
    running from `start` for `months` months — enough that a cutover part
    way through leaves real months on both sides."""
    post(led, start, "Opening balances",
         ("Assets:Checking", 500_00),
         ("Assets:Savings", 1_000_00),
         ("Equity:Opening Balances", -1_500_00))
    when = start
    for i in range(months):
        post(led, when, "Salary", ("Assets:Checking", 4_000_00),
             ("Income:Salary", -4_000_00), payee="EMPLOYER")
        post(led, when + timedelta(days=3), "Rent",
             ("Expenses:Housing:Rent", 1_200_00),
             ("Assets:Checking", -1_200_00), payee="LANDLORD LLC")
        post(led, when + timedelta(days=10), "Groceries",
             ("Expenses:Food:Groceries", 300_00 + i * 5_00),
             ("Assets:Checking", -(300_00 + i * 5_00)),
             payee="WHOLE FOODS")
        post(led, when + timedelta(days=15), "Sweep",
             ("Assets:Savings", 500_00), ("Assets:Checking", -500_00))
        when = date(when.year + (when.month == 12),
                    when.month % 12 + 1, 1)
    return led


@pytest.fixture
def seeded(led):
    return seed(led)


def archived(led, tmp_path, name="out.db", **kwargs):
    """Archive `led` into tmp_path/name and return the new open ledger."""
    archive.archive(led, kwargs.pop("through", CUT), tmp_path / name,
                    **kwargs)
    return Ledger(tmp_path / name)


# -- what compaction must preserve -------------------------------------------


def test_balances_identical_at_every_month_end(seeded, tmp_path):
    """The invariant the whole feature rests on: a sum of monthly sums is
    the monthly sum, so every month-end balance is unchanged."""
    new = archived(seeded, tmp_path)
    when = date(2025, 1, 31)
    checked = 0
    while when < date(2026, 7, 1):
        assert new.balances(as_of=when) == seeded.balances(as_of=when), when
        checked += 1
        when = reports.month_bounds(
            when.year + (when.month == 12), when.month % 12 + 1)[1]
    assert checked >= 12


def test_reports_identical_across_the_cutover(seeded, tmp_path):
    new = archived(seeded, tmp_path)
    as_of = date(2026, 6, 30)
    assert (reports.balance_sheet(new, as_of)
            == reports.balance_sheet(seeded, as_of))
    assert (reports.income_statement(new, date(2025, 1, 1), as_of, "all")
            == reports.income_statement(seeded, date(2025, 1, 1), as_of,
                                        "all"))
    assert (reports.cash_flow_statement(new, date(2025, 1, 1), as_of, "all")
            == reports.cash_flow_statement(seeded, date(2025, 1, 1), as_of,
                                           "all"))
    assert (reports.trial_balance(new, as_of)
            == reports.trial_balance(seeded, as_of))


def test_retained_earnings_survives_compaction(seeded, tmp_path):
    """Compaction keeps the flows, so cumulative net income is still
    cumulative net income — the line that `--drop-detail` destroys."""
    new = archived(seeded, tmp_path)
    before = reports.balance_sheet(seeded, date(2026, 6, 30))
    after = reports.balance_sheet(new, date(2026, 6, 30))
    assert after["retained_earnings"] == before["retained_earnings"]
    assert after["retained_earnings"] != 0
    assert after["equity"] == before["equity"]


def test_monthly_series_reports_identical(seeded, tmp_path):
    new = archived(seeded, tmp_path)
    for report in (
        lambda led: reports.net_worth_trend(led, 12, end=date(2026, 6, 30)),
        lambda led: reports.trend(led, count=12, end_key="2026-05",
                                  today=date(2026, 6, 30)),
    ):
        assert report(new) == report(seeded)


def test_analysis_ratios_identical(seeded, tmp_path):
    new = archived(seeded, tmp_path)
    before = analysis.analyze(seeded, date(2025, 1, 1), date(2025, 12, 31),
                              "2025")
    after = analysis.analyze(new, date(2025, 1, 1), date(2025, 12, 31),
                             "2025")
    assert after["savings_rate_pct"] == before["savings_rate_pct"]
    assert after["liquidity_months"] == before["liquidity_months"]
    assert after["liquidity_months"] is not None


def test_register_running_balance_ties_after_the_cutover(seeded, tmp_path):
    """The opening balance a register shows is the sum of everything
    prior, so it is a direct check that the summaries carry the weight."""
    new = archived(seeded, tmp_path)
    account = "Assets:Checking"
    before = reports.register(seeded, seeded.find_account(account),
                              date(2026, 1, 1), date(2026, 3, 31))
    after = reports.register(new, new.find_account(account),
                             date(2026, 1, 1), date(2026, 3, 31))
    assert after["opening_balance"] == before["opening_balance"]
    assert [r["balance"] for r in after["rows"]] == [
        r["balance"] for r in before["rows"]]


def test_the_file_actually_shrinks(led, tmp_path):
    # Enough rows that the saving clears SQLite's page granularity — the
    # point of the feature is only visible at scale.
    seed(led, months=36, start=date(2023, 1, 1))
    result = archive.archive(led, CUT, tmp_path / "out.db")
    assert result["summary_transactions"] < result["archived_transactions"]
    assert result["out_bytes"] < result["source_bytes"]


# -- what compaction changes, deliberately -----------------------------------


def test_detail_is_gone_and_the_summary_says_so(seeded, tmp_path):
    new = archived(seeded, tmp_path)
    archived_txns = new.transactions(end=CUT)
    assert archived_txns
    assert all(t.tags == [archive.ARCHIVE_TAG] for t in archived_txns)
    assert all("summary" in t.description.lower() for t in archived_txns)
    # One per month, dated inside the month they summarize.
    assert len({f"{t.date:%Y-%m}" for t in archived_txns}) == len(
        archived_txns)
    assert not [t for t in archived_txns if t.payee]


def test_post_cutover_detail_is_untouched(seeded, tmp_path):
    new = archived(seeded, tmp_path)
    before = seeded.transactions(start=date(2026, 1, 1))
    after = new.transactions(start=date(2026, 1, 1))
    assert [(t.id, t.date, t.description, t.payee) for t in after] == [
        (t.id, t.date, t.description, t.payee) for t in before]


def test_source_ledger_is_never_modified(seeded, tmp_path):
    before = seeded.balances(), len(seeded.transactions())
    archive.archive(seeded, CUT, tmp_path / "out.db")
    assert (seeded.balances(), len(seeded.transactions())) == before


def test_side_tables_come_along(seeded, tmp_path):
    seeded.set_budget(seeded.find_account("Expenses:Food:Groceries"),
                      400_00, "monthly")
    seeded.add_import_rule(
        "WHOLE FOODS", seeded.find_account("Expenses:Food:Groceries"))
    seeded.add_goal("emergency", seeded.find_account("Assets:Savings"),
                    10_000_00, date(2027, 1, 1))
    new = archived(seeded, tmp_path)
    assert [(a.name, a.type) for a in new.accounts(include_closed=True)] == [
        (a.name, a.type) for a in seeded.accounts(include_closed=True)]
    assert len(new.budgets()) == len(seeded.budgets())
    assert [r[1] for r in new.import_rules()] == ["WHOLE FOODS"]
    assert [g["name"] for g in new.goals()] == ["emergency"]


def test_archived_period_is_closed(seeded, tmp_path):
    """The detail that would justify editing an archived month is gone,
    so the archive closes the books through the cutover."""
    new = archived(seeded, tmp_path)
    assert new.closed_through == CUT
    assert new.detail_begins == CUT + timedelta(days=1)
    with pytest.raises(BeansError, match="closed through"):
        post(new, date(2025, 6, 1), "late entry",
             ("Expenses:Other", 100), ("Assets:Checking", -100))
    # After the cutover the ledger is fully writable.
    post(new, date(2026, 8, 1), "new entry",
         ("Expenses:Other", 100), ("Assets:Checking", -100))


def test_void_transactions_do_not_reach_the_summaries(led, tmp_path):
    seed(led, months=6)
    oops = post(led, date(2025, 3, 4), "mistake",
                ("Expenses:Other", 999_00), ("Assets:Checking", -999_00))
    led.void_transaction(oops.id)
    expected = led.balances(as_of=CUT)
    new = archived(led, tmp_path)
    assert new.balances(as_of=CUT) == expected


def test_mid_month_cutover_keeps_a_partial_month(led, tmp_path):
    """A cutover inside a month summarizes only that month's elapsed
    part, and the summary is dated on or before the cutover."""
    seed(led, months=8)
    cut = date(2025, 5, 12)
    new = archived(led, tmp_path, through=cut)
    assert new.balances(as_of=cut) == led.balances(as_of=cut)
    assert max(t.date for t in new.transactions(end=cut)) <= cut


# -- --drop-detail -----------------------------------------------------------


def test_drop_detail_keeps_net_worth_and_folds_equity(seeded, tmp_path):
    new = archived(seeded, tmp_path, drop_detail=True)
    before = reports.balance_sheet(seeded, CUT)
    after = reports.balance_sheet(new, CUT)
    assert after["net_worth"] == before["net_worth"]
    assert after["total_assets"] == before["total_assets"]
    assert after["total_liabilities"] == before["total_liabilities"]
    assert after["total_equity"] == before["total_equity"]
    assert after["balanced"]
    # Cumulative net income has been closed into contributed capital.
    assert before["retained_earnings"] != 0
    assert after["retained_earnings"] == 0


def test_drop_detail_moves_history_begins_but_compaction_does_not(
        seeded, tmp_path):
    compacted = archived(seeded, tmp_path, "compact.db")
    dropped = archived(seeded, tmp_path, "dropped.db", drop_detail=True)
    assert compacted.history_begins == seeded.history_begins
    assert dropped.history_begins == CUT


def test_drop_detail_needs_an_equity_account(led, tmp_path):
    seed(led, months=6)
    led.update_account(led.find_account("Equity:Opening Balances"),
                       name="Equity:Contributed")
    led.add_account("Equity:Other", AccountType.EQUITY)
    with pytest.raises(BeansError, match="one equity account"):
        archive.archive(led, CUT, tmp_path / "out.db", drop_detail=True)
    assert not (tmp_path / "out.db").exists()


# -- guard rails -------------------------------------------------------------


def test_refuses_a_cutover_that_is_not_in_the_past(seeded, tmp_path):
    with pytest.raises(BeansError, match="in the past"):
        archive.archive(seeded, date.today(), tmp_path / "out.db")


def test_refuses_when_there_is_nothing_to_archive(seeded, tmp_path):
    with pytest.raises(BeansError, match="nothing to archive"):
        archive.archive(seeded, date(2024, 1, 1), tmp_path / "out.db")


def test_refuses_to_overwrite_the_source(seeded, tmp_path):
    with pytest.raises(BeansError, match="destination is the ledger itself"):
        archive.archive(seeded, CUT, seeded.path)


def test_refuses_to_overwrite_without_force(seeded, tmp_path):
    out = tmp_path / "out.db"
    out.write_text("not a ledger")
    with pytest.raises(BeansError, match="already exists"):
        archive.archive(seeded, CUT, out)
    assert out.read_text() == "not a ledger"
    archive.archive(seeded, CUT, out, force=True)
    assert Ledger(out).balances(as_of=CUT) == seeded.balances(as_of=CUT)


def test_verification_failure_leaves_no_file(seeded, tmp_path, monkeypatch):
    """A wrong archive must not be handed back. The check is real, so
    breaking the rewrite has to be observable through it."""
    def corrupt(new, through, summary, drop_detail):
        with new.db:
            new.db.execute("DELETE FROM postings WHERE txn_id IN "
                           "(SELECT id FROM transactions WHERE date <= ?)",
                           (through.isoformat(),))
            new.db.execute("DELETE FROM transactions WHERE date <= ?",
                           (through.isoformat(),))
    monkeypatch.setattr(archive, "_rewrite", corrupt)
    with pytest.raises(BeansError, match="verification failed"):
        archive.archive(seeded, CUT, tmp_path / "out.db")
    assert not (tmp_path / "out.db").exists()


def test_dry_run_writes_nothing(seeded, tmp_path):
    plan = archive.plan(seeded, CUT)
    assert plan["report"] == "archive_plan"
    assert plan["archived_transactions"] > plan["summary_transactions"] > 0
    assert plan["retained_transactions"] > 0
    assert "out" not in plan
    assert [p.name for p in tmp_path.iterdir()] == ["test.db"]


def test_plan_names_merchants_about_to_become_unlearnable(led, tmp_path):
    seed(led)
    post(led, date(2025, 4, 2), "COUNTY TAX COLLECTOR",
         ("Expenses:Taxes", 800_00), ("Assets:Checking", -800_00))
    lost = {m["merchant"] for m in archive.plan(led, CUT)[
        "unlearnable_merchants"]}
    # Seen once, only before the cutover, with no rule to fall back on.
    assert "COUNTY TAX COLLECTOR" in lost
    # Still active after the cutover, so its history is not what is at risk.
    assert "Groceries" not in lost


def test_an_import_rule_removes_a_merchant_from_the_warning(led, tmp_path):
    seed(led)
    post(led, date(2025, 4, 2), "COUNTY TAX COLLECTOR",
         ("Expenses:Taxes", 800_00), ("Assets:Checking", -800_00))
    led.add_import_rule("COUNTY TAX COLLECTOR",
                        led.find_account("Expenses:Taxes"))
    lost = {m["merchant"] for m in archive.plan(led, CUT)[
        "unlearnable_merchants"]}
    assert "COUNTY TAX COLLECTOR" not in lost


# -- history_begins ----------------------------------------------------------


def test_history_begins_defaults_to_the_first_transaction(seeded):
    assert seeded.history_begins == date(2025, 1, 1)


def test_history_begins_is_none_for_an_empty_ledger(led):
    assert led.history_begins is None


def test_net_worth_trend_omits_months_before_the_history(led):
    post(led, date(2026, 6, 1), "Opening balances",
         ("Assets:Checking", 5_000_00),
         ("Equity:Opening Balances", -5_000_00))
    data = reports.net_worth_trend(led, 12, end=date(2026, 8, 31))
    assert data["months_omitted"] == 9
    assert [r["month"] for r in data["rows"]] == ["2026-06", "2026-07",
                                                  "2026-08"]
    assert all(r["net_worth"] for r in data["rows"])


def test_trend_omits_periods_before_the_history(led):
    seed(led, months=3, start=date(2026, 4, 1))
    data = reports.trend(led, count=12, end_key="2026-06",
                         today=date(2026, 7, 15))
    assert data["periods_omitted"] == 9
    assert data["periods"] == ["2026-04", "2026-05", "2026-06"]


def test_trend_keeps_one_period_when_the_window_predates_everything(led):
    seed(led, months=2, start=date(2026, 6, 1))
    data = reports.trend(led, count=6, end_key="2026-03",
                         today=date(2026, 7, 15))
    assert data["periods"] == ["2026-03"]
    assert data["totals"]["average_income"] == 0


def test_forecast_shrinks_its_lookback_to_the_available_history(led):
    seed(led, months=2, start=date(2026, 7, 1))
    data = forecast.forecast(led, months=3, lookback=6)
    assert data["lookback_requested"] == 6
    assert data["lookback_months"] < 6
    text = forecast.render_forecast(data, 2, "$")
    assert "history begins" in text


def test_analysis_rates_use_only_months_the_ledger_covers(led):
    """Two months of spending over a year-long request is a runway six
    times too long if the empty months are counted."""
    seed(led, months=2, start=date(2026, 1, 1))
    data = analysis.analyze(led, date(2025, 1, 1), date(2026, 2, 28), "wide")
    narrow = analysis.analyze(led, date(2026, 1, 1), date(2026, 2, 28),
                              "narrow")
    assert data["rate_start"] == date(2026, 1, 1)
    assert data["liquidity_months"] == narrow["liquidity_months"]
    assert "history begins" in analysis.render_analysis(data, 2, "$")


def test_status_reports_no_30_day_delta_without_a_baseline(led):
    today = date.today()
    post(led, today, "Opening balances",
         ("Assets:Checking", 5_000_00),
         ("Equity:Opening Balances", -5_000_00))
    data = status.status_report(led, today=today)
    assert data["net_worth"] == 5_000_00
    assert data["net_worth_change_30d"] is None
    assert "over 30 days" not in status.render_status(data, 2, "$")


def test_status_reports_a_delta_once_there_is_one(led):
    today = date.today()
    post(led, today - timedelta(days=60), "Opening balances",
         ("Assets:Checking", 5_000_00),
         ("Equity:Opening Balances", -5_000_00))
    post(led, today - timedelta(days=5), "Salary",
         ("Assets:Checking", 100_00), ("Income:Salary", -100_00))
    data = status.status_report(led, today=today)
    assert data["net_worth_change_30d"] == 100_00
    assert "over 30 days" in status.render_status(data, 2, "$")


# -- CLI ---------------------------------------------------------------------


@pytest.fixture
def cli_ledger(tmp_path):
    path = str(tmp_path / "ledger.db")
    assert main(["-f", path, "init"]) == 0
    led = Ledger(path)
    seed(led)
    led.close()
    return path


def test_cli_dry_run_then_archive(capsys, cli_ledger, tmp_path):
    out = str(tmp_path / "rolled.db")
    assert main(["-f", cli_ledger, "archive", "--through", "2025-12-31",
                 "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "dry run" in text and "Nothing was written" in text
    assert not (tmp_path / "rolled.db").exists()

    assert main(["-f", cli_ledger, "archive", "--through", "2025-12-31",
                 "--out", out]) == 0
    text = capsys.readouterr().out
    assert "archive of record" in text
    assert Ledger(out).balances() == Ledger(cli_ledger).balances()


def test_cli_defaults_the_destination_alongside_the_source(capsys,
                                                           cli_ledger):
    assert main(["-f", cli_ledger, "archive",
                 "--through", "2025-12-31"]) == 0
    expected = str(cli_ledger).replace("ledger.db",
                                       "ledger-from-2025-12-31.db")
    assert expected in capsys.readouterr().out
    assert Ledger(expected).closed_through == CUT


def test_cli_json_keeps_counts_as_counts(capsys, cli_ledger, tmp_path):
    import json
    capsys.readouterr()  # drop the fixture's `init` output
    assert main(["-f", cli_ledger, "archive", "--through", "2025-12-31",
                 "--out", str(tmp_path / "j.db"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data["archived_transactions"], int)
    assert isinstance(data["summary_transactions"], int)
    assert data["archived_transactions"] > data["summary_transactions"]
    assert data["mode"] == "compact"


def test_cli_reports_the_error_without_a_traceback(capsys, cli_ledger):
    code = main(["-f", cli_ledger, "archive", "--through", "2024-01-01"])
    assert code == 1
    assert "nothing to archive" in capsys.readouterr().err


def test_an_existing_later_close_is_not_reopened(seeded, tmp_path):
    """Archiving locks the archived span, but must not unlock months the
    user had already closed past it."""
    seeded.close_books(date(2026, 3, 31))
    new = archived(seeded, tmp_path)
    assert new.closed_through == date(2026, 3, 31)
