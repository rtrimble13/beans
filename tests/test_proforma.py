"""The pro-forma projection and the statements built on it.

`forecast --report bs` is only worth having if the statement it prints
obeys the same rules the historical one does, so these tests pin the
properties rather than the numbers: it balances, the three statements
articulate with each other, card-funded spending stays out of operating
cash, a loan amortizes, recurring rules are not counted twice, and the
`forecast` dict still carries everything `economic.py` reads off it.
"""

from datetime import date, timedelta

import pytest

from beans import archive, forecast, proforma, reports
from beans.cli import main
from beans.ledger import Ledger
from beans.models import AccountType, Posting
from beans.utils import add_months, month_bounds
from tests.conftest import post

TODAY = date.today()


def month_start(offset: int) -> date:
    """The first of the month `offset` months from this one."""
    return add_months(month_bounds(TODAY.year, TODAY.month)[0], offset)


def seed(led, months=6):
    """A household whose plumbing is worth recovering: salary and tax
    through checking, groceries on the credit card paid off monthly, a
    savings sweep and a brokerage contribution — the last two invisible to
    any income statement. History ends with the last complete month."""
    opening = month_start(-months)
    post(led, opening, "Opening balances",
         ("Assets:Checking", 8_000_00),
         ("Assets:Savings", 20_000_00),
         ("Assets:Investments:Brokerage", 30_000_00),
         ("Liabilities:Credit Card", -400_00),
         ("Equity:Opening Balances", -57_600_00))
    for i in range(months):
        start = month_start(-months + i)
        post(led, start + timedelta(days=14), "Paycheck",
             ("Assets:Checking", 4_000_00), ("Expenses:Taxes", 1_000_00),
             ("Income:Salary", -5_000_00))
        post(led, start + timedelta(days=7), "Groceries",
             ("Expenses:Food:Groceries", 400_00),
             ("Liabilities:Credit Card", -400_00))
        post(led, start + timedelta(days=24), "Card payment",
             ("Liabilities:Credit Card", 400_00),
             ("Assets:Checking", -400_00))
        post(led, start + timedelta(days=1), "Sweep",
             ("Assets:Savings", 300_00), ("Assets:Checking", -300_00))
        post(led, start + timedelta(days=2), "Brokerage contribution",
             ("Assets:Investments:Brokerage", 500_00),
             ("Assets:Checking", -500_00))
    return led


@pytest.fixture
def household(led):
    return seed(led)


def statements(led, **kwargs):
    kinds = ("is", "bs", "cf")
    pf = proforma.project(led, **kwargs)
    return {k: forecast.forecast_statement(led, k, pf=pf) for k in kinds}


# -- the properties a statement must have ------------------------------------


@pytest.mark.parametrize("months", [1, 3, 12])
@pytest.mark.parametrize("method", ["average", "trend"])
def test_projected_balance_sheet_balances(household, months, method):
    data = forecast.forecast_statement(household, "bs", months=months,
                                       method=method)
    assert data["balanced"]
    assert data["total_assets"] == (data["total_liabilities"]
                                    + data["total_equity"])


def test_projected_balance_sheet_balances_on_an_empty_ledger(led):
    data = forecast.forecast_statement(led, "bs", months=3)
    assert data["balanced"]
    assert data["net_worth"] == 0


def test_the_three_statements_articulate(household):
    """The cash-flow statement must explain the change in cash, and the
    balance sheet's retained earnings must advance by net income — the
    same ties the historical statements obey."""
    s = statements(household, months=6)
    cf, bs, income = s["cf"], s["bs"], s["is"]
    assert cf["cash_ending"] - cf["cash_beginning"] == cf["net_change"]

    opening = reports.balance_sheet(household, date.today())
    assert (bs["retained_earnings"] - opening["retained_earnings"]
            == income["net_income"])
    assert bs["net_worth"] == opening["net_worth"] + income["net_income"]


def test_statements_cover_the_window_the_balance_sheet_ends_on(household):
    s = statements(household, months=2)
    assert s["bs"]["as_of"] == s["is"]["end"] == s["cf"]["end"]
    assert s["is"]["start"] == date.today() + timedelta(days=1)
    assert s["bs"]["as_of"] == month_bounds(month_start(2).year,
                                            month_start(2).month)[1]


def test_statements_say_they_are_projections(household):
    for kind, title in (("is", "PROJECTED INCOME STATEMENT"),
                        ("bs", "PROJECTED BALANCE SHEET"),
                        ("cf", "PROJECTED STATEMENT OF CASH FLOWS")):
        data = forecast.forecast_statement(household, kind, months=1)
        assert data["title"] == title
        assert data["forecast"]["projected"] is True
        assert data["forecast"]["statement"] == kind
        text = forecast.render_forecast_statement(data, 2, "$")
        assert title in text
        # The basis is on the face of the statement, not just in the JSON.
        assert "Basis:" in text


# -- where the money comes from ----------------------------------------------


def test_funding_mix_recovers_the_card_and_the_cash_split(household):
    start, end = month_start(-6), month_start(0) - timedelta(days=1)
    ratios, transfers, mixed, pure = proforma.funding_mix(household, start,
                                                          end)
    names = {a.name: a.id for a in household.accounts()}
    groceries = ratios[names["Expenses:Food:Groceries"]]
    assert groceries == pytest.approx(
        {names["Liabilities:Credit Card"]: -1.0})
    salary = ratios[names["Income:Salary"]]
    assert salary == pytest.approx({names["Assets:Checking"]: -1.0})
    # The sweep, the brokerage contribution and the card payoff have no
    # income/expense leg at all — the run-rate is the only way to see them.
    assert pure == 18
    assert mixed == 12
    assert transfers[names["Assets:Savings"]] == 6 * 300_00


def test_pure_transfers_reach_the_projected_balance_sheet(household):
    """Savings and the brokerage keep growing, and the cash they come out
    of keeps shrinking — none of which any income statement can see."""
    now = reports.balance_sheet(household, date.today())
    data = forecast.forecast_statement(household, "bs", months=3)
    for name, monthly in (("Assets:Savings", 300_00),
                          ("Assets:Investments:Brokerage", 500_00)):
        grew = data["assets"][name] - now["assets"][name]
        # Four months of run-rate: the part-elapsed month plus three.
        assert grew == pytest.approx(4 * monthly, abs=100)


def test_projected_cash_is_not_just_accumulated_net_income(household):
    """The defect this feature exists to fix: $800 a month of the
    household's net income leaves for savings and the brokerage, so cash
    cannot grow by the whole of it."""
    data = forecast.forecast(household, months=12)
    rows = data["months"]
    cash_growth = rows[-1]["projected_cash"] - data["current_cash"]
    net_income = sum(r["net"] for r in rows)
    assert cash_growth < net_income
    # Net worth is unaffected by a transfer, so it still tracks net income.
    assert (rows[-1]["projected_net_worth"] - data["current_net_worth"]
            == pytest.approx(net_income + data["stub_income"]
                             - data["stub_expenses"], abs=100))


def test_summary_and_balance_sheet_agree(household):
    """The last row of the summary table and the projected balance sheet
    are the same claim, so they had better be the same number."""
    summary = forecast.forecast(household, months=6)
    sheet = forecast.forecast_statement(household, "bs", months=6)
    assert summary["months"][-1]["projected_net_worth"] == sheet["net_worth"]
    cash_accounts = [a.name for a in household.accounts(
        type_=AccountType.ASSET) if a.is_cash]
    assert summary["months"][-1]["projected_cash"] == sum(
        sheet["assets"].get(name, 0) for name in cash_accounts)


def test_an_account_with_no_history_is_funded_from_cash(household):
    """A budget on a category the books have never seen has no funding mix
    to read; it must still balance."""
    household.set_budget(household.find_account("Expenses:Health"),
                         200_00, "monthly")
    data = forecast.forecast_statement(household, "bs", months=2,
                                       use_budget=True)
    assert data["balanced"]
    sources = {d["account"]: d["source"]
               for d in forecast.forecast(household, months=2,
                                          use_budget=True)["accounts"]}
    assert sources["Expenses:Health"] == "budget"


# -- the grain the cash-flow classifier reads --------------------------------


def test_card_funded_spending_stays_out_of_operating_cash(household):
    """Groceries go on the card, so they are not an operating *cash* flow
    until the card is paid — exactly as the historical statement treats
    them. Bundling a month into one entry would silently reclassify them."""
    data = forecast.forecast_statement(household, "cf", months=1)
    assert "Expenses:Food:Groceries" not in data["operating"]
    assert "Expenses:Taxes" in data["operating"]
    assert "Liabilities:Credit Card" in data["financing"]
    assert "Assets:Investments:Brokerage" in data["investing"]


def test_projected_transactions_are_tagged_and_never_written(household):
    before = len(household.transactions())
    pf = proforma.project(household, months=3)
    assert pf.txns
    assert all(proforma.PROJECTED_TAG in t.tags for t in pf.txns)
    assert all(t.id < 0 for t in pf.txns)
    assert len(household.transactions()) == before


def test_every_projected_transaction_balances(household):
    pf = proforma.project(household, months=6, method="trend")
    for txn in pf.txns:
        assert sum(p.amount for p in txn.postings) == 0


# -- recurring rules ---------------------------------------------------------


def test_recurring_rules_are_not_double_counted(led):
    """The sweep is a rule that has already posted six months of history.
    Projecting the rule *and* the run-rate it created would move twice as
    much money as the household actually moves."""
    checking = led.find_account("Assets:Checking")
    savings = led.find_account("Assets:Savings")
    post(led, month_start(-6), "Opening balances",
         ("Assets:Checking", 10_000_00), ("Equity:Opening Balances",
                                          -10_000_00))
    led.add_recurring("sweep", "monthly", month_start(-6), [
        Posting(account_id=savings.id, amount=300_00),
        Posting(account_id=checking.id, amount=-300_00),
    ])
    from beans.recurring import run_due
    run_due(led, month_start(0) - timedelta(days=1))

    data = forecast.forecast_statement(led, "bs", months=3,
                                       use_recurring=True)
    now = reports.balance_sheet(led, date.today())
    moved = data["assets"]["Assets:Savings"] - now["assets"]["Assets:Savings"]
    # Three scheduled occurrences remain inside the window, not six.
    assert moved == 3 * 300_00
    assert data["balanced"]


def test_recurring_accounts_are_projected_from_the_schedule(led):
    rent = led.find_account("Expenses:Housing:Rent")
    checking = led.find_account("Assets:Checking")
    led.add_recurring("rent", "monthly", month_start(1), [
        Posting(account_id=rent.id, amount=1_500_00),
        Posting(account_id=checking.id, amount=-1_500_00),
    ])
    data = forecast.forecast_statement(led, "is", months=3,
                                       use_recurring=True)
    assert data["expenses"]["Expenses:Housing:Rent"] == 3 * 1_500_00


# -- loans -------------------------------------------------------------------


def _with_mortgage(led):
    """A mortgage paid monthly out of checking: interest to expenses,
    principal against the liability."""
    from decimal import Decimal
    account = led.add_account("Liabilities:Mortgage", AccountType.LIABILITY,
                              liquidity="noncurrent")
    led.add_account("Expenses:Interest", AccountType.EXPENSE)
    post(led, month_start(-6), "Opening balances",
         ("Assets:Checking", 20_000_00), ("Liabilities:Mortgage",
                                          -200_000_00),
         ("Equity:Opening Balances", 180_000_00))
    led.add_loan(account, 200_000_00, Decimal("0.06"), 360, 1_199_10,
                 month_start(-6))
    balance = 200_000_00
    for i in range(6):
        interest = round(balance * 0.06 / 12)
        principal = 1_199_10 - interest
        balance -= principal
        post(led, month_start(-6 + i), "Mortgage payment",
             ("Liabilities:Mortgage", principal),
             ("Expenses:Interest", interest),
             ("Assets:Checking", -1_199_10))
    return led


def test_a_loan_amortizes_on_its_schedule(led):
    """Held at the historical average the interest/principal split never
    moves, so the loan never amortizes. The schedule fixes that: interest
    falls and principal rises, month over month."""
    _with_mortgage(led)
    pf = proforma.project(led, months=12)
    expense_id = led.find_account("Expenses:Interest").id
    interest = [
        sum(p.amount for p in t.postings if p.account_id == expense_id)
        for t in pf.txns
        if t.description == "Projected: Expenses:Interest"
    ]
    assert len(interest) >= 12
    assert interest == sorted(interest, reverse=True)
    assert interest[0] > interest[-1]
    sources = {d["account"]: d["source"]
               for d in forecast.forecast(led, months=12)["accounts"]}
    assert sources["Expenses:Interest"] == "amortized"


def test_a_projected_loan_balance_keeps_its_current_split(led):
    _with_mortgage(led)
    data = forecast.forecast_statement(led, "bs", months=12)
    assert data["balanced"]
    current = data["liabilities_current"]["Liabilities:Mortgage"]
    noncurrent = data["liabilities_noncurrent"]["Liabilities:Mortgage"]
    assert current > 0 and noncurrent > 0
    assert (current + noncurrent
            == data["liabilities"]["Liabilities:Mortgage"])


# -- archived ledgers --------------------------------------------------------


def test_a_compacted_lookback_window_is_clamped_and_disclosed(led, tmp_path):
    """`beans archive` replaces a month with one bundled entry, which would
    smear the funding mix across every account. The mix stops where detail
    does, and the statement says so."""
    seed(led, months=6)
    cut = month_start(-3) - timedelta(days=1)
    archive.archive(led, cut, tmp_path / "archived.db")
    new = Ledger(tmp_path / "archived.db")
    data = forecast.forecast_statement(new, "bs", months=1)
    assert data["balanced"]
    assert any("detail begins" in w for w in data["forecast"]["warnings"])
    # The classification the bundling would have destroyed still holds.
    flows = forecast.forecast_statement(new, "cf", months=1)
    assert "Expenses:Food:Groceries" not in flows["operating"]
    new.close()


def test_income_projection_survives_archival(led, tmp_path):
    """Compaction preserves monthly flows, so what the forecast projects
    for income and expenses is unchanged — the promise `beans archive`
    makes."""
    seed(led, months=6)
    before = forecast.forecast(led, months=3)
    cut = month_start(-3) - timedelta(days=1)
    archive.archive(led, cut, tmp_path / "archived.db")
    new = Ledger(tmp_path / "archived.db")
    after = forecast.forecast(new, months=3)
    assert [r["income"] for r in after["months"]] == \
        [r["income"] for r in before["months"]]
    assert [r["expenses"] for r in after["months"]] == \
        [r["expenses"] for r in before["months"]]
    new.close()


# -- contracts other modules depend on ---------------------------------------


def test_forecast_dict_keeps_the_keys_its_callers_read(household):
    data = forecast.forecast(household, months=1)
    for key in ("report", "method", "lookback_months", "lookback_requested",
                "history_begins", "horizon_months", "use_budget",
                "use_recurring", "current_cash", "current_net_worth",
                "months", "accounts", "total_projected_net"):
        assert key in data
    # `economic.py` reads the first month's run-rate off this row.
    row = data["months"][0]
    assert row["income"] and row["expenses"]
    assert set(row) >= {"month", "income", "expenses", "net",
                        "projected_cash", "projected_net_worth"}


def test_economic_balance_sheet_still_builds(household):
    """`economic.py` estimates its run-rates off `forecast()`; it must keep
    seeing a full month's income in the first row."""
    from decimal import Decimal

    from beans import economic
    inputs = economic.EconomicInputs(
        as_of=date.today(), discount_rate=Decimal("0.03"),
        components={kind: economic.Component(kind, "auto")
                    for kind in ("income", "consumption")})
    data = economic.economic_balance_sheet(household, inputs)
    assert data["human_capital"] > 0
    assert data["future_consumption"] > 0


# -- the command -------------------------------------------------------------


@pytest.mark.parametrize("which", ["is", "bs", "cf", "income", "balance",
                                   "cashflow", "all", "summary"])
def test_cli_report_flag(household, tmp_path, capsys, which):
    assert main(["-f", str(household.path), "forecast", "-n", "1",
                 "--report", which]) == 0
    out = capsys.readouterr().out
    assert "PROJECTED" in out or which == "summary"


def test_cli_json_is_self_identifying(household, capsys):
    import json
    assert main(["-f", str(household.path), "forecast", "-n", "1",
                 "--report", "bs", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["report"] == "balance_sheet"
    assert data["forecast"]["projected"] is True
    assert data["forecast"]["horizon_months"] == 1
    assert data["balanced"] is True
    # Money is major-unit strings; counts stay integers.
    assert isinstance(data["net_worth"], str)


def test_cli_report_all_prints_three_statements(household, capsys):
    assert main(["-f", str(household.path), "forecast", "--report",
                 "all"]) == 0
    out = capsys.readouterr().out
    assert out.count("PROJECTED") == 3


def test_cli_flat_balance_sheet(household, capsys):
    assert main(["-f", str(household.path), "forecast", "-n", "1",
                 "--report", "bs", "--flat"]) == 0
    out = capsys.readouterr().out
    assert "Current Assets" not in out
    assert "Total Assets" in out


# -- what a run-rate is allowed to be ----------------------------------------


def test_opening_balances_are_not_a_monthly_transfer(household):
    """The opening entry moves five figures between accounts and touches
    equity. Annualizing it would project a household depositing its whole
    net worth every month, forever."""
    pf = proforma.project(household, months=3)
    names = {a.id: a.name for a in household.accounts()}
    run_rate = {names[k]: v for k, v in pf.transfers.items()}
    assert run_rate["Assets:Savings"] == 300_00
    assert run_rate["Assets:Investments:Brokerage"] == 500_00
    assert "Equity:Opening Balances" not in run_rate


def test_a_one_off_transfer_is_not_a_run_rate(household):
    """A $15,000 withdrawal from the brokerage in one month is not $2,500 a
    month. Direction is part of the shape, so it does not merge with the
    monthly contribution that uses the same two accounts."""
    post(household, month_start(-3), "Car purchase",
         ("Assets:Investments:Brokerage", -15_000_00),
         ("Assets:Checking", 15_000_00))
    pf = proforma.project(household, months=3)
    names = {a.id: a.name for a in household.accounts()}
    run_rate = {names[k]: v for k, v in pf.transfers.items()}
    assert run_rate["Assets:Investments:Brokerage"] == 500_00
    assert run_rate["Assets:Checking"] == -1_200_00


def test_a_fully_archived_lookback_still_balances_and_says_so(led, tmp_path):
    """Every month of the window compacted: there is no funding mix left to
    read at all, so projections fall back to cash — and say so rather than
    quietly inventing a mix from the summaries."""
    seed(led, months=6)
    archive.archive(led, month_start(0) - timedelta(days=1),
                    tmp_path / "all.db")
    new = Ledger(tmp_path / "all.db")
    data = forecast.forecast_statement(new, "bs", months=2)
    assert data["balanced"]
    assert any("No line-item detail" in w
               for w in data["forecast"]["warnings"])
    new.close()


def test_a_month_end_base_date_has_no_stub(household):
    """On the last day of a month there is no remainder to project, so the
    window is exactly the whole months asked for."""
    pf = proforma.project(household, months=2,
                          base_date=month_start(1) - timedelta(days=1))
    assert pf.stub_end is None
    assert pf.window_start == month_start(1)
    assert pf.window_end == month_start(3) - timedelta(days=1)
    assert all(t.date >= pf.window_start for t in pf.txns)


def test_the_stub_completes_the_month_it_does_not_repeat_it(household):
    """Projecting from mid-month must not re-project what the month has
    already seen: the stub is the run-rate less what is already booked."""
    mid = month_start(0) + timedelta(days=20)
    post(household, month_start(0) + timedelta(days=7), "Groceries",
         ("Expenses:Food:Groceries", 400_00),
         ("Liabilities:Credit Card", -400_00))
    pf = proforma.project(household, months=1, base_date=mid)
    groceries = household.find_account("Expenses:Food:Groceries").id
    stub = [d.stub for d in pf.drivers if d.account.id == groceries]
    assert stub == [0]
