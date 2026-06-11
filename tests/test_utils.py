from datetime import date

import pytest

from beans.utils import (
    BeansError,
    add_months,
    format_amount,
    months_in_range,
    parse_amount,
    parse_date,
    parse_period,
    prior_period,
)


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
