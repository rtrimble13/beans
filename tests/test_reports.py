from datetime import date

import pytest

from beans import reports
from beans.analysis import analyze
from beans.budget import budget_report
from beans.models import AccountType
from beans.render import rollup
from beans.utils import BeansError
from tests.conftest import post


def seed(led):
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Checking", 500000),
         ("Liabilities:Credit Card", -120000),
         ("Equity:Opening Balances", -380000))
    post(led, date(2026, 1, 15), "paycheck",
         ("Assets:Checking", 400000),
         ("Assets:Investments:Retirement", 100000),
         ("Income:Salary", -500000))
    post(led, date(2026, 2, 1), "rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    post(led, date(2026, 2, 5), "card payment",
         ("Liabilities:Credit Card", 50000), ("Assets:Checking", -50000))
    post(led, date(2026, 2, 20), "groceries on card",
         ("Expenses:Food:Groceries", 30000),
         ("Liabilities:Credit Card", -30000))


def test_income_statement(led):
    seed(led)
    data = reports.income_statement(
        led, date(2026, 1, 1), date(2026, 12, 31), "2026")
    assert data["total_income"] == 500000
    assert data["total_expenses"] == 210000
    assert data["net_income"] == 290000
    assert data["income"]["Income:Salary"] == 500000


def test_income_statement_compare_bounded_period(led):
    seed(led)
    data = reports.income_statement(
        led, date(2026, 4, 1), date(2026, 6, 30), "2026-Q2", compare=True)
    # A bounded period gets a real prior-period comparison block.
    assert "compare" in data
    assert "compare_note" not in data
    assert data["compare"]["period"]  # prior period label is populated


def test_income_statement_compare_unbounded_degrades(led):
    seed(led)
    # --period all resolves start=None; comparing has no prior period, so it
    # must degrade with a note rather than raising (issue #12).
    data = reports.income_statement(
        led, None, date(2026, 12, 31), "all time", compare=True)
    assert "compare" not in data
    assert "compare_note" in data
    assert "unbounded period" in data["compare_note"]
    # The note renders into the text output; the report still produced.
    text = reports.render_income_statement(data, 2, "$")
    assert "comparison unavailable" in text


def test_balance_sheet_balances(led):
    seed(led)
    data = reports.balance_sheet(led, date(2026, 12, 31))
    assert data["balanced"]
    assert data["total_assets"] == 770000
    assert data["total_liabilities"] == 100000
    assert data["retained_earnings"] == 290000
    assert data["total_equity"] == 670000
    assert data["net_worth"] == 670000
    assert (data["total_assets"]
            == data["total_liabilities"] + data["total_equity"])


def test_balance_sheet_classified_split(led):
    from datetime import date as _date
    from decimal import Decimal

    seed(led)
    # Retirement is non-current by default; attach a loan to a liability.
    loans_acct = led.find_account("Liabilities:Loans")
    post(led, _date(2026, 3, 1), "car loan draw",
         ("Assets:Checking", 3000000), ("Liabilities:Loans", -3000000))
    led.add_loan(loans_acct, 3000000, Decimal("0.0625"), 60, 58348,
                 _date(2026, 3, 1))
    data = reports.balance_sheet(led, _date(2026, 12, 31))

    # Buckets re-sum to the type totals.
    assert (data["total_assets_current"] + data["total_assets_noncurrent"]
            == data["total_assets"])
    assert (data["total_liabilities_current"]
            + data["total_liabilities_noncurrent"]
            == data["total_liabilities"])
    # Retirement landed in non-current assets; the credit card (current tag,
    # no loan) is wholly current.
    assert "Assets:Investments:Retirement" in data["assets_noncurrent"]
    assert "Liabilities:Credit Card" in data["liabilities_current"]
    # The loan liability is split across both buckets.
    assert data["liabilities_current"]["Liabilities:Loans"] > 0
    assert data["liabilities_noncurrent"]["Liabilities:Loans"] > 0


def test_cash_flow_ties_to_cash_delta(led):
    seed(led)
    start, end = date(2026, 1, 1), date(2026, 12, 31)
    data = reports.cash_flow_statement(led, start, end, "2026")
    # Net change must reconcile with beginning/ending cash balances.
    assert data["net_change"] == data["cash_ending"] - data["cash_beginning"]
    # Salary in, rent out -> operating; retirement contribution -> investing;
    # card payment and opening borrowing -> financing.
    assert data["net_operating"] == 500000 - 180000
    assert data["net_investing"] == -100000
    assert data["net_financing"] == -50000 + 120000 + 380000
    # The card-only grocery purchase moved no cash and must not appear.
    assert "Expenses:Food:Groceries" not in data["operating"]


def test_cash_flow_respects_category_override(led):
    cc = led.find_account("Liabilities:Credit Card")
    led.update_account(cc, cf_category="operating")
    seed(led)
    data = reports.cash_flow_statement(
        led, date(2026, 1, 1), date(2026, 12, 31), "2026")
    assert "Liabilities:Credit Card" in data["operating"]
    assert "Liabilities:Credit Card" not in data["financing"]


def test_trial_balance_debits_equal_credits(led):
    seed(led)
    data = reports.trial_balance(led, date(2026, 12, 31))
    assert data["total_debits"] == data["total_credits"] > 0


def test_register_running_balance(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    data = reports.register(led, checking, None, date(2026, 12, 31))
    assert data["rows"][-1]["balance"] == 670000
    # Running balances are cumulative.
    assert [r["balance"] for r in data["rows"]] == [
        500000, 900000, 720000, 670000]


def test_register_opening_balance_with_start(led):
    seed(led)
    checking = led.find_account("Assets:Checking")
    data = reports.register(led, checking, date(2026, 2, 1),
                            date(2026, 12, 31))
    assert data["opening_balance"] == 900000
    assert data["rows"][-1]["balance"] == 670000


def test_budget_report_scaling(led):
    seed(led)
    led.set_budget(led.find_account("Rent"), 180000, "monthly")
    led.set_budget(led.find_account("Groceries"), 120000, "quarterly")
    data = budget_report(led, date(2026, 2, 1), date(2026, 2, 28), "Feb")
    by_name = {r["account"]: r for r in data["rows"]}
    rent = by_name["Expenses:Housing:Rent"]
    assert rent["budget"] == 180000
    assert rent["actual"] == 180000
    assert rent["pct_used"] == 100
    groceries = by_name["Expenses:Food:Groceries"]
    assert groceries["budget"] == 40000  # quarterly / 3
    assert groceries["actual"] == 30000


def test_budget_report_quarter_scales_monthly(led):
    seed(led)
    led.set_budget(led.find_account("Rent"), 180000, "monthly")
    data = budget_report(led, date(2026, 1, 1), date(2026, 3, 31), "Q1")
    [rent] = data["rows"]
    assert rent["budget"] == 540000


def test_analysis(led):
    seed(led)
    data = analyze(led, date(2026, 1, 1), date(2026, 12, 31), "2026")
    assert data["net_income"] == 290000
    assert data["savings_rate_pct"] == 58.0
    assert data["net_worth"] == 670000
    assert data["debt_to_assets_pct"] == round(100 * 100000 / 770000, 1)
    assert data["top_expenses"][0]["account"] == "Expenses:Housing:Rent"


def test_net_worth_trend(led):
    seed(led)
    data = reports.net_worth_trend(led, 3, end=date(2026, 3, 31))
    assert [r["month"] for r in data["rows"]] == [
        "2026-01", "2026-02", "2026-03"]
    jan, feb, mar = data["rows"]
    assert jan["net_worth"] == 880000  # opening 380k + paycheck 500k
    assert feb["net_worth"] == 670000  # rent -180k, groceries on card -30k
    assert feb["change"] == -210000
    assert mar["net_worth"] == 670000
    assert mar["change"] == 0


def test_jsonify_converts_money(led):
    seed(led)
    data = reports.balance_sheet(led, date(2026, 12, 31))
    j = reports.jsonify(data, 2)
    assert j["total_assets"] == "7700.00"
    assert j["balanced"] is True
    assert j["as_of"] == "2026-12-31"


def test_jsonify_money_uses_embedded_precision():
    # reports.Money carries its own decimals so foreign amounts render at
    # the foreign currency's precision regardless of the base decimals.
    data = {"base": 1100, "yen": reports.Money(1000000, 0),
            "eur": reports.Money(100000, 2), "missing": reports.Money(None, 0)}
    j = reports.jsonify(data, 2)
    assert j == {"base": "11.00", "yen": "1000000",
                 "eur": "1000.00", "missing": None}


# -- trend -------------------------------------------------------------------


def seed_trend(led):
    """Twelve months to August 2026, carrying one of each shape worth
    finding: a raise in March, groceries climbing $20 a month, rent flat, an
    insurance payment that stops after April, and one large one-off."""
    post(led, date(2025, 8, 1), "opening",
         ("Assets:Checking", 800000), ("Equity:Opening Balances", -800000))
    for index in range(12):
        year, month = (2025, 9 + index) if index < 4 else (2026, index - 3)
        pay = 600000 if index < 6 else 660000
        post(led, date(year, month, 15), "paycheck",
             ("Assets:Checking", pay), ("Income:Salary", -pay))
        post(led, date(year, month, 1), "rent",
             ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
        groceries = 50000 + 2000 * index
        post(led, date(year, month, 8), "groceries",
             ("Expenses:Food:Groceries", groceries),
             ("Assets:Checking", -groceries))
        if index < 8:
            post(led, date(year, month, 5), "insurance",
                 ("Expenses:Insurance", 14500), ("Assets:Checking", -14500))
    post(led, date(2026, 3, 11), "clinic",
         ("Expenses:Health", 240000), ("Assets:Checking", -240000))


def test_trend_window_ends_at_the_last_complete_period(led):
    """The rule the report exists to enforce: four days into September, the
    series stops at August and says which period it left out."""
    seed_trend(led)
    data = reports.trend(led, count=12, today=date(2026, 9, 4))
    assert data["periods"][0] == "2025-09"
    assert data["periods"][-1] == "2026-08"
    assert "2026-09" not in data["periods"]
    assert data["excluded_partial"] == "2026-09"
    assert data["complete_through"] == "2026-08"
    assert data["period_count"] == 12
    assert all(not row["partial"] for row in data["rows"])


def test_trend_includes_the_final_period_once_it_has_elapsed(led):
    seed_trend(led)
    data = reports.trend(led, count=2, today=date(2026, 8, 31))
    assert data["periods"][-1] == "2026-08"
    assert data["excluded_partial"] is None


def test_trend_ties_to_the_income_statement_period_by_period(led):
    """A trend that disagrees with the statement for the same month is worse
    than no trend, so every period is checked against one."""
    seed_trend(led)
    data = reports.trend(led, count=12, today=date(2026, 9, 4))
    for row in data["rows"]:
        start, end = row["start"], row["end"]
        statement = reports.income_statement(led, start, end, row["period"])
        assert row["income"] == statement["total_income"]
        assert row["expenses"] == statement["total_expenses"]
        assert row["net_income"] == statement["net_income"]


def test_trend_account_series_are_per_period_and_signed_naturally(led):
    seed_trend(led)
    data = reports.trend(led, count=12, today=date(2026, 9, 4))
    by_name = {row["account"]: row for row in data["accounts"]}
    groceries = by_name["Expenses:Food:Groceries"]
    assert groceries["amounts"] == [50000 + 2000 * i for i in range(12)]
    assert groceries["first"] == 50000
    assert groceries["last"] == 72000
    assert groceries["change"] == 22000
    assert groceries["total"] == sum(groceries["amounts"])
    assert groceries["average"] == round(sum(groceries["amounts"]) / 12)
    # Income is credit-normal but reported positive, like every statement.
    assert by_name["Income:Salary"]["amounts"][-1] == 660000


def test_trend_reports_a_lapsed_payment_as_trailing_zeros(led):
    """The insurance stops after April. Those must be zeros in the series,
    not missing entries — a gap would read as 'no data', not 'stopped'."""
    seed_trend(led)
    data = reports.trend(led, count=12, today=date(2026, 9, 4))
    insurance = next(row for row in data["accounts"]
                     if row["account"] == "Expenses:Insurance")
    assert insurance["amounts"] == [14500] * 8 + [0] * 4
    assert insurance["last"] == 0


def test_trend_omits_accounts_with_no_flow_in_the_window(led):
    seed_trend(led)
    data = reports.trend(led, count=3, today=date(2026, 9, 4))
    names = [row["account"] for row in data["accounts"]]
    assert "Expenses:Health" not in names      # the one-off was in March
    assert "Expenses:Housing:Rent" in names


def test_trend_ranks_accounts_by_largest_change(led):
    seed_trend(led)
    data = reports.trend(led, count=12, today=date(2026, 9, 4))
    changes = [abs(row["change"]) for row in data["accounts"]]
    assert changes == sorted(changes, reverse=True)


def test_trend_quarters_aggregate_their_months(led):
    seed_trend(led)
    months = reports.trend(led, count=6, grain="month",
                           end_key="2026-06", today=date(2026, 9, 4))
    quarter = reports.trend(led, count=2, grain="quarter",
                            end_key="2026-Q2", today=date(2026, 9, 4))
    assert quarter["periods"] == ["2026-Q1", "2026-Q2"]
    assert (sum(row["income"] for row in months["rows"])
            == sum(row["income"] for row in quarter["rows"]))
    assert (sum(row["expenses"] for row in months["rows"])
            == sum(row["expenses"] for row in quarter["rows"]))


def test_trend_savings_rate_matches_the_analysis_ratio(led):
    seed_trend(led)
    data = reports.trend(led, count=1, end_key="2026-08",
                         today=date(2026, 9, 4))
    row = data["rows"][0]
    ratios = analyze(led, row["start"], row["end"], "2026-08")
    assert row["savings_rate_pct"] == ratios["savings_rate_pct"]


def test_trend_savings_rate_is_none_without_income(led):
    post(led, date(2026, 6, 3), "rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    data = reports.trend(led, count=2, today=date(2026, 8, 4))
    assert all(row["savings_rate_pct"] is None for row in data["rows"])
    assert data["totals"]["savings_rate_pct"] is None


def test_trend_include_partial_labels_it_and_leaves_it_out_of_averages(led):
    """Including the period in progress is allowed, but it must not drag the
    average — that is how a four-day month becomes a 'collapse'."""
    seed_trend(led)
    post(led, date(2026, 9, 1), "rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    data = reports.trend(led, count=3, today=date(2026, 9, 4),
                         include_partial=True)
    assert data["periods"][-1] == "2026-09"
    assert data["rows"][-1]["partial"] is True
    assert data["rows"][-1]["income"] == 0
    assert data["excluded_partial"] is None
    # Two complete months of 660000 income; the stub is not averaged in.
    assert data["totals"]["complete_periods"] == 2
    assert data["totals"]["average_income"] == 660000


def test_trend_end_key_is_normalized(led):
    seed_trend(led)
    lower = reports.trend(led, count=2, grain="quarter", end_key="2026-q2",
                          today=date(2026, 9, 4))
    assert lower["periods"] == ["2026-Q1", "2026-Q2"]
    short = reports.trend(led, count=1, end_key="2026-6",
                          today=date(2026, 9, 4))
    assert short["periods"] == ["2026-06"]


def test_trend_rejects_a_bad_window(led):
    from beans.utils import BeansError
    with pytest.raises(BeansError, match="at least one period"):
        reports.trend(led, count=0)
    with pytest.raises(BeansError, match="invalid grain"):
        reports.trend(led, count=3, grain="week")


def test_trend_on_an_empty_ledger_is_empty_not_an_error(led):
    data = reports.trend(led, count=3, today=date(2026, 9, 4))
    assert data["accounts"] == []
    assert all(row["income"] == 0 for row in data["rows"])
    assert data["totals"]["net_income"] == 0


def test_render_trend_names_what_it_left_out(led):
    seed_trend(led)
    data = reports.trend(led, count=6, today=date(2026, 9, 4))
    text = reports.render_trend(data, 2, "$")
    assert "TREND" in text
    assert "2026-09 is still in progress and is excluded." in text
    assert "Expenses:Food:Groceries" in text
    assert "Average" in text


def test_render_trend_flags_a_partial_row(led):
    seed_trend(led)
    data = reports.trend(led, count=3, today=date(2026, 9, 4),
                         include_partial=True)
    text = reports.render_trend(data, 2, "$")
    assert "2026-09 *" in text
    assert "excluded from the average" in text


def test_trend_of_only_a_partial_period_says_nothing_is_complete(led):
    """A one-period window that is still in progress must not imply its
    average is comparable to anything."""
    seed_trend(led)
    post(led, date(2026, 9, 1), "rent",
         ("Expenses:Housing:Rent", 180000), ("Assets:Checking", -180000))
    data = reports.trend(led, count=1, today=date(2026, 9, 4),
                         include_partial=True)
    assert data["rows"][0]["partial"] is True
    assert data["totals"]["complete_periods"] == 0
    assert data["totals"]["average_expenses"] == 180000


# -- income statement --level ------------------------------------------------


def seed_levels(led):
    """Spending three and four segments deep, beside a two-segment account,
    so every level has something to roll up."""
    led.add_account("Expenses:Activities:Music Lessons", AccountType.EXPENSE)
    led.add_account("Expenses:Activities:Sports:Soccer", AccountType.EXPENSE)
    post(led, date(2026, 9, 1), "paycheck",
         ("Assets:Checking", 1000000), ("Income:Salary", -1000000))
    post(led, date(2026, 9, 2), "interest",
         ("Assets:Checking", 1000), ("Income:Interest", -1000))
    post(led, date(2026, 9, 3), "lessons",
         ("Expenses:Activities:Music Lessons", 165700),
         ("Assets:Checking", -165700))
    post(led, date(2026, 9, 4), "soccer",
         ("Expenses:Activities:Sports:Soccer", 59100),
         ("Assets:Checking", -59100))
    post(led, date(2026, 9, 5), "groceries",
         ("Expenses:Food:Groceries", 60000), ("Assets:Checking", -60000))
    post(led, date(2026, 9, 6), "dining",
         ("Expenses:Food:Dining", 40000), ("Assets:Checking", -40000))
    post(led, date(2026, 9, 7), "movies",
         ("Expenses:Entertainment", 20000), ("Assets:Checking", -20000))


def september(led, **kwargs):
    return reports.income_statement(
        led, date(2026, 9, 1), date(2026, 9, 30), "September 2026", **kwargs)


def test_collapse_rolls_each_account_up_to_its_ancestor():
    amounts = {"Expenses:Food:Groceries": 600, "Expenses:Food:Dining": 400,
               "Expenses:Entertainment": 200, "Expenses:A:B:C": 50}
    assert reports.collapse(amounts, None) is amounts
    assert reports.collapse(amounts, 1) == {}
    assert reports.collapse(amounts, 2) == {
        "Expenses:Food": 1000, "Expenses:Entertainment": 200,
        "Expenses:A": 50}
    assert reports.collapse(amounts, 3) == {
        "Expenses:Food:Groceries": 600, "Expenses:Food:Dining": 400,
        "Expenses:Entertainment": 200, "Expenses:A:B": 50}
    # Deeper than the deepest account is the full view.
    assert reports.collapse(amounts, 9) == amounts


def test_collapse_drops_a_subtotal_that_nets_to_zero():
    # A refund that exactly offsets the spend: no line, as for a zero
    # account in the full view.
    amounts = {"Expenses:Food:Groceries": 500, "Expenses:Food:Dining": -500,
               "Expenses:Health": 100}
    assert reports.collapse(amounts, 2) == {"Expenses:Health": 100}


@pytest.mark.parametrize("level", [0, -1])
def test_collapse_rejects_a_level_below_one(level):
    with pytest.raises(BeansError, match="must be 1 or more"):
        reports.collapse({}, level)


def test_income_statement_default_is_every_account(led):
    seed_levels(led)
    data = september(led)
    assert data["level"] is None
    assert data["expenses"]["Expenses:Activities:Sports:Soccer"] == 59100


def test_income_statement_level_two_is_one_level_below_the_sections(led):
    seed_levels(led)
    data = september(led, level=2)
    assert data["level"] == 2
    assert data["income"] == {"Income:Salary": 1000000,
                              "Income:Interest": 1000}
    assert data["expenses"] == {"Expenses:Activities": 224800,
                                "Expenses:Food": 100000,
                                "Expenses:Entertainment": 20000}


def test_income_statement_level_three_folds_only_deeper_accounts(led):
    seed_levels(led)
    data = september(led, level=3)
    assert data["expenses"] == {
        "Expenses:Activities:Music Lessons": 165700,
        "Expenses:Activities:Sports": 59100,
        "Expenses:Food:Groceries": 60000,
        "Expenses:Food:Dining": 40000,
        "Expenses:Entertainment": 20000}


@pytest.mark.parametrize("level", [None, 1, 2, 3, 4])
def test_income_statement_totals_are_the_same_at_every_level(led, level):
    seed_levels(led)
    data = september(led, level=level)
    full = september(led)
    for key in ("total_income", "total_expenses", "net_income"):
        assert data[key] == full[key]
    if level != 1:
        # The lines still add up to the totals once rolled up.
        assert sum(data["income"].values()) == data["total_income"]
        assert sum(data["expenses"].values()) == data["total_expenses"]


def test_income_statement_level_one_is_the_totals_alone(led):
    seed_levels(led)
    data = september(led, level=1)
    assert data["income"] == {} and data["expenses"] == {}
    assert data["total_income"] == 1001000
    assert data["total_expenses"] == 344800
    assert data["net_income"] == 656200
    text = reports.render_income_statement(data, 2, "$")
    assert "Total Income" in text and "Total Expenses" in text
    assert "Net Income" in text
    # No section headings over empty sections, and no accounts.
    lines = [line.strip() for line in text.splitlines()]
    assert "Income" not in lines and "Expenses" not in lines
    assert "Salary" not in text and "Activities" not in text


def test_render_income_statement_at_level_two(led):
    seed_levels(led)
    text = reports.render_income_statement(september(led, level=2), 2, "$")
    assert "Activities" in text and "2,248.00" in text
    assert "Music Lessons" not in text and "Soccer" not in text
    # Each rolled-up line carries its own share of income.
    assert "22.5%" in text  # 2,248.00 / 10,010.00


def test_income_statement_compare_is_rolled_up_too(led):
    seed_levels(led)
    data = september(led, level=2, compare=True)
    assert data["compare"]["level"] == 2


def test_income_statement_level_survives_json(led):
    seed_levels(led)
    out = reports.jsonify(september(led, level=2), 2)
    # A level is a count of name segments, not money.
    assert out["level"] == 2
    assert out["expenses"]["Expenses:Activities"] == "2248.00"


# -- a parent account with postings of its own -------------------------------


def amount_lines(text: str, section: str, total: str) -> list[str]:
    """The amount column of `section`'s lines, between its heading and the
    `total` line: what a reader adds up to check the total."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.strip() == section)
    end = next(i for i, line in enumerate(lines)
               if i > start and line.strip().startswith(total))
    return [line.split()[-1] if "%" not in line else line.split()[-2]
            for line in lines[start + 1:end]
            if line.strip() and not line.startswith("-")
            and any(ch.isdigit() for ch in line)]


def test_rollup_gives_a_parent_balance_its_own_line():
    amounts = {"Expenses:Food": 100, "Expenses:Food:Groceries": 200,
               "Expenses:Health": 50}
    assert rollup(amounts) == [
        ("Expenses", 0, 350, False),
        ("Food", 1, 300, False),
        ("Food (direct)", 2, 100, True),
        ("Groceries", 2, 200, True),
        ("Health", 1, 50, True),
    ]


def test_rollup_without_parent_postings_is_unchanged():
    rows = rollup({"Expenses:Food:Groceries": 200, "Expenses:Health": 50})
    assert not any("(direct)" in name for name, *_ in rows)
    # Only accounts that were posted to are leaves; headers carry no line.
    assert [(name, leaf) for name, _, _, leaf in rows] == [
        ("Expenses", False), ("Food", False), ("Groceries", True),
        ("Health", True)]


def test_income_statement_shows_a_parent_accounts_own_spending(led):
    led.add_account("Expenses:Food", AccountType.EXPENSE)
    post(led, date(2026, 9, 1), "paycheck",
         ("Assets:Checking", 100000), ("Income:Salary", -100000))
    post(led, date(2026, 9, 2), "market",
         ("Expenses:Food", 10000), ("Assets:Checking", -10000))
    post(led, date(2026, 9, 3), "groceries",
         ("Expenses:Food:Groceries", 20000), ("Assets:Checking", -20000))
    data = reports.income_statement(
        led, date(2026, 9, 1), date(2026, 9, 30), "September 2026")
    text = reports.render_income_statement(data, 2, "$")
    assert "Food (direct)" in text
    # The visible lines add up to the total printed under them.
    assert amount_lines(text, "Expenses", "Total Expenses") == \
        ["100.00", "200.00"]
    assert data["total_expenses"] == 30000
    # Rolled up, the parent's own spending joins its sub-accounts' in one
    # line, and there is nothing left to show separately.
    rolled = reports.render_income_statement(
        reports.income_statement(led, date(2026, 9, 1), date(2026, 9, 30),
                                 "September 2026", level=2), 2, "$")
    assert "(direct)" not in rolled
    assert amount_lines(rolled, "Expenses", "Total Expenses") == ["300.00"]


def test_flat_balance_sheet_shows_a_parent_accounts_own_balance(led):
    led.add_account("Assets:Investments", AccountType.ASSET,
                    liquidity="noncurrent")
    post(led, date(2026, 1, 1), "opening",
         ("Assets:Checking", 100000), ("Equity:Opening Balances", -100000))
    post(led, date(2026, 1, 2), "unsorted holding",
         ("Assets:Investments", 30000), ("Assets:Checking", -30000))
    post(led, date(2026, 1, 3), "brokerage",
         ("Assets:Investments:Brokerage", 20000),
         ("Assets:Checking", -20000))
    for classified in (True, False):
        data = reports.balance_sheet(led, date(2026, 1, 31),
                                     classified=classified)
        text = reports.render_balance_sheet(data, 2, "$")
        assert "Investments (direct)" in text
        assert "300.00" in text
        assert data["balanced"] is True
    flat = reports.render_balance_sheet(
        reports.balance_sheet(led, date(2026, 1, 31), classified=False),
        2, "$")
    assert amount_lines(flat, "Assets", "Total Assets") == \
        ["500.00", "300.00", "200.00"]
