"""Tests for the economic balance sheet: the present-value core, the compute
that ties it back to the accounting balance sheet, and the markdown config
document. The PV math is pinned against closed-form values (and cross-checked
against the loan amortization core), mirroring tests/test_loans.py."""

from datetime import date
from decimal import Decimal

import pytest

from beans import economic
from beans.economic import Component, EconomicInputs, Segment
from beans.loans import payment_for, periodic_rate
from beans.utils import BeansError, add_months
from tests.conftest import post


# -- present-value core ------------------------------------------------------


def test_pv_annuity_zero_rate_is_the_sum():
    assert economic.pv_annuity(100000, Decimal("0"), 12) == 1200000


def test_pv_lump_sum_discounts_one_amount():
    expected = round(Decimal(1000000) / Decimal("1.01") ** 12)
    assert economic.pv_lump_sum(1000000, Decimal("0.12"), 12) == expected


def test_pv_annuity_reciprocates_loan_payment():
    # The PV of the level payment that amortizes $30,000 must return ~$30,000;
    # they differ only by the payment's rounding to whole cents.
    pay = payment_for(3000000, periodic_rate(Decimal("0.0625")), 60)
    pv = economic.pv_annuity(pay, Decimal("0.0625"), 60)
    assert abs(pv - 3000000) <= 50


def test_pv_annuity_r_equals_g_singularity():
    # The growing-annuity closed form divides by (r - g); at r == g it must use
    # the dedicated branch instead of blowing up.
    n = 24
    r = periodic_rate(Decimal("0.06"))
    assert economic.pv_annuity(100000, Decimal("0.06"), n, Decimal("0.06")) == \
        round(Decimal(100000) * n / (Decimal(1) + r))


def test_pv_annuity_growing_matches_closed_form():
    n, C = 24, 100000
    r, g = periodic_rate(Decimal("0.05")), periodic_rate(Decimal("0.02"))
    expected = round(Decimal(C) / (r - g) * (1 - ((1 + g) / (1 + r)) ** n))
    assert economic.pv_annuity(C, Decimal("0.05"), n, Decimal("0.02")) == expected


def test_pv_flows_single_flow_equals_lump_sum():
    as_of = date(2026, 1, 1)
    when = add_months(as_of, 1)
    assert economic.pv_flows([(when, 500000)], as_of, Decimal("0.06")) == \
        economic.pv_lump_sum(500000, Decimal("0.06"), 1)


def test_pv_stream_single_segment_equals_annuity():
    as_of = date(2026, 1, 1)
    rate = Decimal("0.04")
    segs = [Segment(as_of, 500000, Decimal("0.02"))]
    horizon = add_months(as_of, 120)
    assert economic.pv_stream(segs, as_of, rate, horizon) == \
        economic.pv_annuity(500000, rate, 120, Decimal("0.02"))


def test_pv_stream_stops_at_retirement():
    # Income for 20 years then zero: the PV is exactly the 240-month annuity.
    as_of = date(2026, 1, 1)
    rate = Decimal("0.03")
    segs = [Segment(date(2026, 1, 1), 800000, Decimal(0)),
            Segment(date(2046, 1, 1), 0, Decimal(0))]
    horizon = add_months(as_of, 480)
    assert economic.pv_stream(segs, as_of, rate, horizon) == \
        economic.pv_annuity(800000, rate, 240, Decimal(0))


# -- the economic balance sheet ----------------------------------------------


def _scalar_inputs(**over):
    base = dict(
        as_of=date(2026, 6, 1), discount_rate=Decimal("0.03"),
        work_years=2, live_years=3,
        components={"income": Component("income", "scalar", amount=300000),
                    "consumption": Component("consumption", "scalar",
                                             amount=150000)})
    base.update(over)
    return EconomicInputs(**base)


def test_reconciles_with_accounting_balance_sheet(led):
    post(led, date(2026, 1, 1), "open",
         ("Assets:Checking", 1000000),
         ("Liabilities:Credit Card", -200000),
         ("Equity:Opening Balances", -800000))
    data = economic.economic_balance_sheet(led, _scalar_inputs())

    assert data["financial_capital"] == 1000000
    assert data["financial_liabilities"] == 200000
    assert data["accounting_net_worth"] == 800000
    assert data["human_capital"] == economic.pv_annuity(300000, Decimal("0.03"),
                                                        24)
    assert data["future_consumption"] == economic.pv_annuity(
        150000, Decimal("0.03"), 36)
    # The economic net worth is the accounting net worth plus/minus the forward
    # PVs — a structural guard against a component landing in the wrong bucket.
    assert data["economic_net_worth"] == (
        data["accounting_net_worth"] + data["human_capital"]
        + data["other_benefits"] - data["future_consumption"]
        - data["other_obligations"])


def test_zero_rate_human_capital_is_flat_sum(led):
    data = economic.economic_balance_sheet(
        led, _scalar_inputs(discount_rate=Decimal("0")))
    assert data["human_capital"] == 300000 * 24       # 2 years, no discount
    assert data["future_consumption"] == 150000 * 36  # 3 years, no discount


def test_empty_ledger_collapses_to_accounting(led):
    inputs = EconomicInputs(
        as_of=date.today(), discount_rate=Decimal("0.03"),
        components={"income": Component("income", "auto"),
                    "consumption": Component("consumption", "auto")})
    data = economic.economic_balance_sheet(led, inputs)
    assert data["human_capital"] == 0
    assert data["future_consumption"] == 0
    assert data["economic_net_worth"] == data["accounting_net_worth"] == 0


def test_auto_uses_the_forecast_run_rate(led):
    # `auto` must value from the forecast run-rate; assert the wiring, not a
    # date-sensitive magnitude.
    prev_month = add_months(date.today(), -1)
    post(led, prev_month, "salary",
         ("Assets:Checking", 600000), ("Income:Salary", -600000))
    inputs = EconomicInputs(
        as_of=date.today(), discount_rate=Decimal("0.02"),
        income_growth=Decimal("0.01"),
        components={"income": Component("income", "auto")})
    data = economic.economic_balance_sheet(led, inputs)
    rates = economic._run_rates(led, inputs, False, False)
    assert data["human_capital"] == economic.pv_annuity(
        rates["income"], Decimal("0.02"), inputs.work_years * 12,
        Decimal("0.01"))


# -- markdown config document ------------------------------------------------


def test_template_round_trips(led):
    text = economic.write_template(led, as_of=date(2026, 7, 1),
                                   discount_rate=Decimal("0.03"))
    inputs = economic.parse_config(text, led)
    assert inputs.as_of == date(2026, 7, 1)
    assert inputs.discount_rate == Decimal("0.03")
    assert inputs.work_years == 25
    assert inputs.live_years == 40
    assert inputs.income_growth == Decimal("0.01")
    assert inputs.inflation == Decimal("0.02")
    assert inputs.components["income"].mode == "auto"
    assert inputs.components["consumption"].mode == "auto"
    # `none` lines parse but contribute nothing.
    assert inputs.components["pension"].mode == "none"


def test_config_scalar_component(led):
    text = (
        "## Settings\n| discount_rate | 0% |\n| as_of | 2026-01-01 |\n\n"
        "## Human capital — income\nMode: scalar\n"
        "| Amount (monthly) | Growth | Years |\n|---|---|---|\n"
        "| 5,000 | 0% | 10 |\n")
    inputs = economic.parse_config(text, led)
    comp = inputs.components["income"]
    assert comp.mode == "scalar"
    assert comp.amount == 500000   # $5,000 in cents
    assert comp.years == 10
    data = economic.economic_balance_sheet(led, inputs)
    assert data["human_capital"] == 500000 * 120  # 10y, zero discount


def test_config_stream_and_one_off_flow(led):
    text = (
        "## Settings\n| discount_rate | 3% |\n| as_of | 2026-01-01 |\n\n"
        "## Pension / benefits\nMode: stream\n"
        "| From (date) | Amount (monthly) | Growth |\n|---|---|---|\n"
        "| 2046-01-01 | 2,000 | 0% |\n\n"
        "## Expected inheritance / other benefits\nMode: stream\n"
        "| Date | Amount |\n|---|---|\n"
        "| 2036-01-01 | 100,000 |\n")
    inputs = economic.parse_config(text, led)
    assert len(inputs.components["pension"].segments) == 1
    assert inputs.components["inheritance"].flows == [(date(2036, 1, 1),
                                                       10000000)]
    data = economic.economic_balance_sheet(led, inputs)
    # Both are asset-side benefits, so economic assets exceed the ledger.
    assert data["other_benefits"] > 0
    assert data["total_economic_assets"] > data["financial_capital"]


def test_config_missing_discount_rate_errors(led):
    text = "## Settings\n| as_of | 2026-01-01 |\n"
    with pytest.raises(BeansError, match="discount_rate"):
        economic.parse_config(text, led)


def test_config_unknown_setting_errors(led):
    text = "## Settings\n| discount_rate | 3% |\n| bogus | 5 |\n"
    with pytest.raises(BeansError, match="bogus"):
        economic.parse_config(text, led)


def test_config_bad_mode_errors(led):
    text = ("## Settings\n| discount_rate | 3% |\n\n"
            "## Human capital — income\nMode: sideways\n")
    with pytest.raises(BeansError, match="mode"):
        economic.parse_config(text, led)


def test_config_non_ascending_stream_dates_error(led):
    text = ("## Settings\n| discount_rate | 3% |\n\n"
            "## Human capital — income\nMode: stream\n"
            "| From | Amount | Growth |\n|---|---|---|\n"
            "| 2030-01-01 | 5,000 | 0% |\n| 2028-01-01 | 4,000 | 0% |\n")
    with pytest.raises(BeansError, match="ascending"):
        economic.parse_config(text, led)


def test_config_negative_horizon_errors(led):
    text = "## Settings\n| discount_rate | 3% |\n| work_years | 0 |\n"
    with pytest.raises(BeansError, match="work_years"):
        economic.parse_config(text, led)


# -- regression tests for review findings ------------------------------------


def test_pv_stream_grows_a_segment_started_before_as_of():
    # A raise that began before today must be valued from today's grown level,
    # not the stale original amount.
    as_of = date(2026, 1, 1)
    rate, growth = Decimal("0.04"), Decimal("0.03")
    seg = [Segment(date(2020, 1, 1), 500000, growth)]  # started 72 months ago
    horizon = add_months(as_of, 240)
    got = economic.pv_stream(seg, as_of, rate, horizon)
    # Base grown from 2020 to as_of (72 months), then a 240-month annuity — the
    # same Decimal path the implementation takes (round once at the end).
    r_m, g_m = periodic_rate(rate), periodic_rate(growth)
    grown_base = Decimal(500000) * (1 + g_m) ** 72
    expected = economic._round_minor(economic._annuity_pv(grown_base, r_m, g_m,
                                                          240))
    assert got == expected
    # And it is far above the buggy figure that ignored the pre-as_of growth.
    assert got > economic.pv_annuity(500000, rate, 240, growth)


def test_stream_and_scalar_agree_when_as_of_not_first_of_month():
    # The horizon must be exactly `work_years` payments long regardless of the
    # day-of-month of as_of, so scalar and an equivalent single-segment stream
    # match. This exercises the compute path (via _component_pv), not pv_stream
    # directly, so the add_months_clamped horizon is under test.
    as_of = date(2026, 7, 9)
    rate = Decimal("0.03")
    scalar = EconomicInputs(
        as_of=as_of, discount_rate=rate, work_years=25,
        components={"income": Component("income", "scalar", amount=900000,
                                        growth=Decimal("0.01"))})
    stream = EconomicInputs(
        as_of=as_of, discount_rate=rate, work_years=25,
        components={"income": Component(
            "income", "stream",
            segments=[Segment(as_of, 900000, Decimal("0.01"))])})

    class _EmptyLed:
        def position(self, as_of=None):
            return {"assets": 0, "liabilities": 0, "cash": 0, "net_worth": 0}

    led = _EmptyLed()
    a = economic.economic_balance_sheet(led, scalar)["human_capital"]
    b = economic.economic_balance_sheet(led, stream)["human_capital"]
    assert a == b


def test_pv_flows_excludes_past_dated_flows():
    as_of = date(2026, 1, 1)
    # A flow before as_of is already realized and must not inflate the PV.
    assert economic.pv_flows([(date(2020, 1, 1), 100000)], as_of,
                             Decimal("0.03")) == 0
    # A flow on as_of counts at full value; one in the future is discounted.
    assert economic.pv_flows([(as_of, 100000)], as_of, Decimal("0.03")) == 100000


def test_config_date_growth_header_is_a_stream_not_lump_sums(led):
    # A monthly schedule written with a `Date` header (plus Growth) must parse
    # as segments, not one-off flows.
    text = ("## Settings\n| discount_rate | 3% |\n| as_of | 2026-01-01 |\n\n"
            "## Pension / benefits\nMode: stream\n"
            "| Date | Amount (monthly) | Growth |\n|---|---|---|\n"
            "| 2027-01-01 | 1,000 | 0% |\n| 2030-01-01 | 2,000 | 0% |\n")
    comp = economic.parse_config(text, led).components["pension"]
    assert len(comp.segments) == 2
    assert comp.flows == []
    assert comp.segments[0].amount == 100000


def test_config_auto_rejected_for_non_runrate_kind(led):
    text = ("## Settings\n| discount_rate | 3% |\n\n"
            "## Pension / benefits\nMode: auto\n")
    with pytest.raises(BeansError, match="auto"):
        economic.parse_config(text, led)
