from datetime import date

from beans import reports
from beans.analysis import analyze
from beans.budget import budget_report
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
