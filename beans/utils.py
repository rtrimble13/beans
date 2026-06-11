"""Money, date, and period helpers shared across the application."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


class BeansError(Exception):
    """User-facing error; the CLI prints the message and exits non-zero."""


CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CAD": "C$",
    "AUD": "A$",
    "CHF": "CHF ",
    "INR": "₹",
}

AVG_DAYS_PER_MONTH = 365.25 / 12


def currency_symbol(code: str) -> str:
    return CURRENCY_SYMBOLS.get(code.upper(), code.upper() + " ")


def parse_amount(text: str, decimals: int = 2) -> int:
    """Parse a money string into integer minor units (e.g. cents).

    Accepts optional commas, currency symbols, and a leading sign.
    """
    cleaned = re.sub(r"[,$€£¥₹\s]", "", str(text))
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise BeansError(f"invalid amount: {text!r}")
    scaled = value.scaleb(decimals)
    if scaled != scaled.to_integral_value():
        raise BeansError(
            f"amount {text!r} has more than {decimals} decimal places"
        )
    return int(scaled)


def format_amount(minor: int, decimals: int = 2, symbol: str = "") -> str:
    """Format integer minor units as a human-readable money string."""
    sign = "-" if minor < 0 else ""
    quantum = 10**decimals
    whole, frac = divmod(abs(minor), quantum)
    if decimals:
        return f"{sign}{symbol}{whole:,}.{frac:0{decimals}d}"
    return f"{sign}{symbol}{whole:,}"


def parse_date(text: str | None, default: date | None = None) -> date:
    if text is None:
        if default is None:
            raise BeansError("a date is required")
        return default
    lowered = text.strip().lower()
    if lowered == "today":
        return date.today()
    if lowered == "yesterday":
        return date.today() - timedelta(days=1)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", lowered)
    if not m:
        raise BeansError(
            f"invalid date: {text!r} (use YYYY-MM-DD, 'today' or 'yesterday')"
        )
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError as exc:
        raise BeansError(f"invalid date {text!r}: {exc}")


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    start_month = 3 * (quarter - 1) + 1
    start = date(year, start_month, 1)
    end = month_bounds(year, start_month + 2)[1]
    return start, end


def add_months(d: date, months: int) -> date:
    """First day of the month `months` after the month containing d."""
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def parse_period(
    period: str | None,
    start: str | None = None,
    end: str | None = None,
    default: str = "ytd",
) -> tuple[date | None, date, str]:
    """Resolve a period spec into (start, end, label).

    A None start means "from the beginning of time". Accepted specs:
    all, ytd, this-month, last-month, this-quarter, last-quarter,
    this-year, last-year, YYYY, YYYY-MM, YYYY-QN. Explicit --from/--to
    dates override the named period.
    """
    today = date.today()
    if start or end:
        s = parse_date(start) if start else None
        e = parse_date(end) if end else today
        if s and s > e:
            raise BeansError("period start is after period end")
        label = f"{s.isoformat() if s else 'beginning'} to {e.isoformat()}"
        return s, e, label

    spec = (period or default).strip().lower()
    if spec == "all":
        return None, today, "all time"
    if spec == "ytd":
        return date(today.year, 1, 1), today, f"{today.year} year to date"
    if spec == "this-month":
        s, e = month_bounds(today.year, today.month)
        return s, min(e, today), f"{today:%B %Y}"
    if spec == "last-month":
        prev = month_bounds(today.year, today.month)[0] - timedelta(days=1)
        s, e = month_bounds(prev.year, prev.month)
        return s, e, f"{prev:%B %Y}"
    if spec == "this-year":
        return date(today.year, 1, 1), today, str(today.year)
    if spec == "last-year":
        year = today.year - 1
        return date(year, 1, 1), date(year, 12, 31), str(year)
    if spec in ("this-quarter", "last-quarter"):
        q = (today.month - 1) // 3 + 1
        year = today.year
        if spec == "last-quarter":
            q -= 1
            if q == 0:
                q, year = 4, year - 1
        s, e = quarter_bounds(year, q)
        return s, min(e, today), f"Q{q} {year}"
    m = re.fullmatch(r"(\d{4})", spec)
    if m:
        year = int(m.group(1))
        return date(year, 1, 1), date(year, 12, 31), str(year)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", spec)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            raise BeansError(f"invalid month in period: {period!r}")
        s, e = month_bounds(year, month)
        return s, e, f"{s:%B %Y}"
    m = re.fullmatch(r"(\d{4})-q([1-4])", spec)
    if m:
        year, q = int(m.group(1)), int(m.group(2))
        s, e = quarter_bounds(year, q)
        return s, e, f"Q{q} {year}"
    raise BeansError(
        f"invalid period: {period!r} (try ytd, all, this-month, last-month, "
        "this-quarter, this-year, 2026, 2026-06 or 2026-Q2)"
    )


def months_in_range(start: date, end: date) -> float:
    """Number of months covered by [start, end], exact for whole months."""
    if start > end:
        return 0.0
    next_day = end + timedelta(days=1)
    if start.day == 1 and next_day.day == 1:
        return (next_day.year - start.year) * 12 + next_day.month - start.month
    return ((end - start).days + 1) / AVG_DAYS_PER_MONTH


def prior_period(start: date | None, end: date) -> tuple[date | None, date, str]:
    """The period of equal length immediately before [start, end]."""
    if start is None:
        raise BeansError("cannot compare against a period with no start date")
    next_day = end + timedelta(days=1)
    if start.day == 1 and next_day.day == 1:
        months = (next_day.year - start.year) * 12 + next_day.month - start.month
        s = add_months(start, -months)
        e = start - timedelta(days=1)
    else:
        span = end - start
        e = start - timedelta(days=1)
        s = e - span
    label = f"{s.isoformat()} to {e.isoformat()}"
    return s, e, label
