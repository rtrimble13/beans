from datetime import date

import pytest

from beans import utils

from beans.utils import (
    BeansError,
    add_months,
    format_amount,
    months_in_range,
    parse_amount,
    parse_date,
    parse_period,
    prior_period,
    signed_foreign,
)


def test_signed_foreign_tracks_base_sign():
    # Magnitude is parsed at the foreign currency's precision, then signed to
    # match the base leg: positive base -> positive foreign, negative -> neg.
    assert signed_foreign("1000", 110000, "EUR") == 100000
    assert signed_foreign("1000", -110000, "EUR") == -100000
    # A magnitude given with its own sign is normalized to the base leg's.
    assert signed_foreign("-1000", 110000, "EUR") == 100000
    # JPY has 0 decimals: no scaling, sign still follows the base leg.
    assert signed_foreign("1000000", -67000, "JPY") == -1000000


def test_parse_amount():
    assert parse_amount("54.20") == 5420
    assert parse_amount("-1,234.56") == -123456
    assert parse_amount("$600") == 60000
    assert parse_amount("100", decimals=0) == 100
    # Multi-character symbols and codes, as emitted by currency_symbol().
    assert parse_amount("C$10") == 1000
    assert parse_amount("-A$3") == -300
    assert parse_amount("CHF 10") == 1000
    assert parse_amount("EUR 5.50") == 550
    assert parse_amount("$-5") == -500
    with pytest.raises(BeansError, match="invalid amount"):
        parse_amount("abc")
    with pytest.raises(BeansError, match="invalid amount"):
        parse_amount("XYZ10")
    with pytest.raises(BeansError, match="decimal places"):
        parse_amount("1.234")


def test_format_amount():
    assert format_amount(5420) == "54.20"
    assert format_amount(-123456, symbol="$") == "-$1,234.56"
    assert format_amount(100, decimals=0) == "100"
    assert format_amount(5) == "0.05"


def test_parse_date():
    assert parse_date("2026-06-11") == date(2026, 6, 11)
    assert parse_date("today") == date.today()
    assert parse_date(None, default=date(2026, 1, 1)) == date(2026, 1, 1)
    with pytest.raises(BeansError, match="invalid date"):
        parse_date("06/11/2026")
    with pytest.raises(BeansError, match="invalid date"):
        parse_date("2026-02-30")


def test_parse_period_named():
    start, end, _ = parse_period("2026")
    assert (start, end) == (date(2026, 1, 1), date(2026, 12, 31))
    start, end, _ = parse_period("2026-02")
    assert (start, end) == (date(2026, 2, 1), date(2026, 2, 28))
    start, end, _ = parse_period("2026-Q2")
    assert (start, end) == (date(2026, 4, 1), date(2026, 6, 30))
    start, end, _ = parse_period("all")
    assert start is None
    start, end, _ = parse_period("ytd")
    assert start == date(date.today().year, 1, 1)
    with pytest.raises(BeansError, match="invalid period"):
        parse_period("never")


def test_parse_period_explicit_dates_override():
    start, end, _ = parse_period("ytd", start="2026-03-01", end="2026-03-15")
    assert (start, end) == (date(2026, 3, 1), date(2026, 3, 15))
    with pytest.raises(BeansError, match="after"):
        parse_period(None, start="2026-03-15", end="2026-03-01")


def test_months_in_range():
    assert months_in_range(date(2026, 1, 1), date(2026, 1, 31)) == 1
    assert months_in_range(date(2026, 1, 1), date(2026, 3, 31)) == 3
    assert 0.4 < months_in_range(date(2026, 1, 1), date(2026, 1, 15)) < 0.6


def test_add_months():
    assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 1)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)


def test_prior_period_whole_months():
    start, end, _ = prior_period(date(2026, 4, 1), date(2026, 6, 30))
    assert (start, end) == (date(2026, 1, 1), date(2026, 3, 31))


def test_prior_period_arbitrary_span():
    start, end, _ = prior_period(date(2026, 6, 10), date(2026, 6, 19))
    assert (start, end) == (date(2026, 5, 31), date(2026, 6, 9))


# -- period keys -------------------------------------------------------------

@pytest.mark.parametrize("when,grain,expected", [
    (date(2026, 9, 4), "month", "2026-09"),
    (date(2026, 1, 31), "month", "2026-01"),
    (date(2026, 9, 4), "quarter", "2026-Q3"),
    (date(2026, 1, 1), "quarter", "2026-Q1"),
    (date(2026, 12, 31), "quarter", "2026-Q4"),
])
def test_period_key(when, grain, expected):
    assert utils.period_key(when, grain) == expected


@pytest.mark.parametrize("key,delta,grain,expected", [
    ("2026-01", -1, "month", "2025-12"),
    ("2025-12", 1, "month", "2026-01"),
    ("2026-06", -6, "month", "2025-12"),
    ("2026-Q1", -1, "quarter", "2025-Q4"),
    ("2025-Q4", 1, "quarter", "2026-Q1"),
    ("2026-05", 0, "month", "2026-05"),
])
def test_shift_period(key, delta, grain, expected):
    assert utils.shift_period(key, delta, grain) == expected


@pytest.mark.parametrize("today,grain,expected", [
    # A period in progress is never the last complete one.
    (date(2026, 9, 4), "month", "2026-08"),
    (date(2026, 9, 29), "month", "2026-08"),
    (date(2026, 9, 30), "month", "2026-09"),   # the last day counts
    (date(2026, 1, 1), "month", "2025-12"),
    (date(2026, 2, 28), "month", "2026-02"),   # short month, non-leap
    (date(2024, 2, 28), "month", "2024-01"),   # leap year: not month end
    (date(2024, 2, 29), "month", "2024-02"),
    (date(2026, 9, 4), "quarter", "2026-Q2"),
    (date(2026, 9, 30), "quarter", "2026-Q3"),
    (date(2026, 1, 15), "quarter", "2025-Q4"),
])
def test_last_complete_period(today, grain, expected):
    assert utils.last_complete_period(today, grain) == expected


def test_period_months():
    assert utils.period_months("2026-05") == ["2026-05"]
    assert utils.period_months("2026-Q2") == ["2026-04", "2026-05", "2026-06"]
    assert utils.period_months("2026-Q4") == ["2026-10", "2026-11", "2026-12"]


def test_period_key_round_trips_through_parse_period():
    for key in ("2026-02", "2026-11", "2026-Q1", "2026-Q4"):
        start, _end, _label = utils.parse_period(key)
        grain = "quarter" if "Q" in key else "month"
        assert utils.period_key(start, grain) == key
