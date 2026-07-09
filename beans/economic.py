"""The economic (holistic) balance sheet: today's ledger position extended
with the present value of the future.

A traditional balance sheet shows *financial* capital — what you own and owe
right now. The economic balance sheet adds the discounted value of future cash
flows a household expects but hasn't booked yet:

  Economic assets      = financial capital (ledger assets)
                       + human capital (PV of future labour income)
                       + PV of pensions / benefits / expected inheritance
  Economic liabilities = financial liabilities (ledger debts)
                       + PV of future lifetime consumption (spending)
                       + PV of bequests / other future obligations
  Economic net worth   = economic assets - economic liabilities

By construction it reconciles with the accounting balance sheet:

  economic net worth = accounting net worth
                     + human capital + other benefits
                     - future consumption - other obligations

The forward-looking inputs are *assumptions*, never booked to the double-entry
ledger — they come from CLI flags or a markdown config document (see
`write_template`/`parse_config`). The financial-capital anchor always comes from
`Ledger.position()`, so actuals and assumptions stay cleanly separated.

Conventions match the rest of beans: money is integer minor units, rates are
`Decimal`, and every present value is rounded once with `ROUND_HALF_UP`. The
discounting core is built on the same compounding idiom as `loans.py`.
"""

from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import re

from beans import forecast
from beans.ledger import Ledger
from beans.loans import _round_minor, periodic_rate
from beans.render import Table, bold, green, money, red
from beans.utils import (
    BeansError,
    add_months,
    add_months_clamped,
    format_amount,
    parse_amount,
    parse_date,
    parse_percent,
)

# 100 years — a runaway guard on horizons, mirroring loans.MAX_SCHEDULE_MONTHS.
MAX_HORIZON_MONTHS = 1200

# The six forward-looking lines, each mapped to a balance-sheet label, a side,
# the EconomicInputs field giving its default horizon (years), and the field
# giving its default annual growth (None = no growth default).
_Spec = namedtuple("_Spec", "label side horizon_field growth_field")
_COMPONENTS: dict[str, _Spec] = {
    "income": _Spec("Human Capital", "asset", "work_years", "income_growth"),
    "pension": _Spec("Pension / Benefits", "asset", "live_years", "inflation"),
    "inheritance": _Spec("Inheritance / Other", "asset", "live_years", None),
    "consumption": _Spec("Future Consumption", "liability", "live_years",
                         "inflation"),
    "bequest": _Spec("Bequests / Other", "liability", "live_years", None),
    "other": _Spec("Other Obligations", "liability", "live_years", None),
}
COMPONENT_MODES = ("auto", "scalar", "stream", "none")

# Only these kinds can be estimated from the ledger, so `auto` is valid only
# for them; the rest have nothing in the books to project from.
_RUN_RATE_KINDS = ("income", "consumption")


# -- input model (transient; never persisted to the ledger) ------------------


@dataclass
class Segment:
    """One row of a piecewise-constant schedule: `amount` per month (minor
    units) prevails from `from_date` until the next segment's date."""

    from_date: date
    amount: int
    growth: Decimal = Decimal(0)  # annual


@dataclass
class Component:
    """One economic-balance-sheet line and how to value it.

    mode:
      auto   - estimate from the ledger run-rate (income/consumption only)
      scalar - a flat/growing annuity of `amount` per month over `years`
      stream - a piecewise-constant schedule of `segments`
      none   - excluded (zero)
    `flows` holds optional one-off dated lump sums for any mode.
    """

    kind: str
    mode: str = "none"
    amount: int | None = None       # scalar monthly minor units
    growth: Decimal | None = None   # scalar annual growth (None = use default)
    years: int | None = None        # horizon override (else the kind default)
    segments: list[Segment] = field(default_factory=list)
    flows: list[tuple[date, int]] = field(default_factory=list)


@dataclass
class EconomicInputs:
    as_of: date
    discount_rate: Decimal
    lookback: int = 12
    work_years: int = 25
    live_years: int = 40
    income_growth: Decimal = Decimal(0)
    inflation: Decimal = Decimal(0)
    components: dict[str, Component] = field(default_factory=dict)


# -- present-value core ------------------------------------------------------


def discount_factor(r: Decimal, n: int) -> Decimal:
    """Present-value factor for `n` periods at periodic rate `r`."""
    return (Decimal(1) + r) ** -n


def _annuity_pv(cash: int | Decimal, r: Decimal, g: Decimal, n: int) -> Decimal:
    """PV (as of one period before the first payment) of an ordinary annuity of
    `cash` per period for `n` periods, growing at periodic rate `g`, discounted
    at periodic rate `r`. Returns an unrounded Decimal so callers can sum
    several segments before the single final rounding."""
    if n <= 0:
        return Decimal(0)
    c = Decimal(cash)
    if r == 0 and g == 0:
        return c * n
    # Growing-annuity closed form divides by (r - g); the r == g singularity
    # needs its own branch. The plain-annuity (g == 0) case reduces from the
    # general form, so it needs no separate branch.
    if r == g:
        return c * n / (Decimal(1) + r)
    ratio = (Decimal(1) + g) / (Decimal(1) + r)
    return c / (r - g) * (Decimal(1) - ratio ** n)


def pv_annuity(cash: int, annual_rate: Decimal, months: int,
               annual_growth: Decimal = Decimal(0)) -> int:
    """PV in minor units of a monthly ordinary annuity of `cash` for `months`
    payments, growing at `annual_growth`, discounted at `annual_rate`."""
    return _round_minor(_annuity_pv(cash, periodic_rate(annual_rate),
                                    periodic_rate(annual_growth), months))


def pv_lump_sum(amount: int, annual_rate: Decimal, months: int) -> int:
    """PV in minor units of a single `amount` received `months` from now."""
    return _round_minor(
        Decimal(amount) * discount_factor(periodic_rate(annual_rate), months))


def pv_flows(flows: list[tuple[date, int]], as_of: date,
             annual_rate: Decimal) -> int:
    """PV in minor units of explicit one-off dated flows. Flows dated before
    `as_of` are already realized (booked to the ledger) and excluded; the rest
    are summed on the Decimal before a single rounding so many small flows don't
    accumulate drift."""
    r = periodic_rate(annual_rate)
    total = Decimal(0)
    for when, amount in flows:
        if when < as_of:
            continue
        total += Decimal(amount) * discount_factor(r, _months_between(as_of,
                                                                      when))
    return _round_minor(total)


def pv_stream(segments: list[Segment], as_of: date, annual_rate: Decimal,
              horizon_end: date) -> int:
    """PV in minor units of a piecewise-constant schedule. Each segment runs
    until the next segment's date (the last runs to `horizon_end`); its growing
    annuity is valued at its own start, then discounted back to `as_of`. One
    rounding at the end."""
    r = periodic_rate(annual_rate)
    ordered = sorted(segments, key=lambda s: s.from_date)
    total = Decimal(0)
    for i, seg in enumerate(ordered):
        g = periodic_rate(seg.growth)
        seg_start = max(seg.from_date, as_of)  # clamp a segment already begun
        seg_end = ordered[i + 1].from_date if i + 1 < len(ordered) \
            else horizon_end
        n = _months_between(seg_start, seg_end)
        if n <= 0:
            continue
        # If the segment began before as_of, its amount has already grown from
        # from_date to as_of; grow the base so the remaining annuity starts from
        # today's level rather than the (stale) original level.
        base = (Decimal(seg.amount)
                * (Decimal(1) + g) ** _months_between(seg.from_date, seg_start))
        at_start = _annuity_pv(base, r, g, n)
        total += at_start * discount_factor(r, _months_between(as_of, seg_start))
    return _round_minor(total)


def _months_between(as_of: date, when: date) -> int:
    """Whole elapsed months from `as_of` to `when` (0 if `when` is on/before
    `as_of`)."""
    if when <= as_of:
        return 0
    months = (when.year - as_of.year) * 12 + (when.month - as_of.month)
    if when.day < as_of.day:
        months -= 1
    return max(0, months)


# -- the economic balance sheet ----------------------------------------------


def _run_rates(led: Ledger, inputs: EconomicInputs, use_budget: bool,
               use_recurring: bool) -> dict[str, int]:
    """Monthly income and consumption run-rates (minor units), reusing the
    forecast engine's one-month average projection."""
    data = forecast.forecast(led, months=1, method="average",
                             lookback=inputs.lookback, use_budget=use_budget,
                             use_recurring=use_recurring)
    row = data["months"][0]
    return {"income": row["income"], "consumption": row["expenses"]}


def _component_pv(inputs: EconomicInputs, comp: Component,
                  run_rates: dict[str, int]) -> int:
    spec = _COMPONENTS[comp.kind]
    horizon_years = comp.years if comp.years is not None \
        else getattr(inputs, spec.horizon_field)
    horizon_months = min(horizon_years * 12, MAX_HORIZON_MONTHS)
    default_growth = (getattr(inputs, spec.growth_field)
                      if spec.growth_field else Decimal(0))

    if comp.mode == "none":
        return 0
    if comp.mode == "auto":
        basis = run_rates.get(comp.kind)
        if basis is None:  # no ledger basis (pension/inheritance/bequest/other)
            return 0
        return pv_annuity(basis, inputs.discount_rate, horizon_months,
                          default_growth)
    if comp.mode == "scalar":
        growth = comp.growth if comp.growth is not None else default_growth
        pv = pv_annuity(comp.amount or 0, inputs.discount_rate, horizon_months,
                        growth)
    elif comp.mode == "stream":
        # add_months_clamped keeps as_of's day-of-month, so the horizon is
        # exactly `horizon_months` payments long — matching the scalar path
        # (plain add_months would snap to the 1st and lose up to a month).
        horizon_end = add_months_clamped(inputs.as_of, horizon_months)
        pv = pv_stream(comp.segments, inputs.as_of, inputs.discount_rate,
                       horizon_end)
    else:
        return 0
    if comp.flows:
        pv += pv_flows(comp.flows, inputs.as_of, inputs.discount_rate)
    return pv


def economic_balance_sheet(led: Ledger, inputs: EconomicInputs,
                           use_budget: bool = False,
                           use_recurring: bool = False) -> dict:
    pos = led.position(as_of=inputs.as_of)
    financial_capital = pos["assets"]
    financial_liabilities = pos["liabilities"]
    accounting_net_worth = pos["net_worth"]

    need_auto = any(c.mode == "auto" for c in inputs.components.values())
    run_rates = (_run_rates(led, inputs, use_budget, use_recurring)
                 if need_auto else {})

    pv = {kind: (_component_pv(inputs, inputs.components[kind], run_rates)
                 if kind in inputs.components else 0)
          for kind in _COMPONENTS}

    human_capital = pv["income"]
    other_benefits = pv["pension"] + pv["inheritance"]
    future_consumption = pv["consumption"]
    other_obligations = pv["bequest"] + pv["other"]

    assets = {"Financial Capital": financial_capital,
              "Human Capital": human_capital}
    if pv["pension"]:
        assets["Pension / Benefits"] = pv["pension"]
    if pv["inheritance"]:
        assets["Inheritance / Other"] = pv["inheritance"]
    liabilities = {"Financial Liabilities": financial_liabilities,
                   "Future Consumption": future_consumption}
    if pv["bequest"]:
        liabilities["Bequests / Other"] = pv["bequest"]
    if pv["other"]:
        liabilities["Other Obligations"] = pv["other"]

    total_assets = financial_capital + human_capital + other_benefits
    total_liabilities = (financial_liabilities + future_consumption
                         + other_obligations)
    economic_net_worth = total_assets - total_liabilities

    return {
        "report": "economic_balance_sheet",
        "as_of": inputs.as_of,
        "discount_rate_pct": float(inputs.discount_rate * 100),
        "income_growth_pct": float(inputs.income_growth * 100),
        "inflation_pct": float(inputs.inflation * 100),
        "work_months": inputs.work_years * 12,
        "live_months": inputs.live_years * 12,
        "lookback_months": inputs.lookback,
        # The monthly figure actually used to value each line (the override or
        # scalar amount when given, else the ledger run-rate), not just the
        # ledger estimate.
        "monthly_income_basis": _monthly_basis(
            inputs.components.get("income"), run_rates.get("income", 0)),
        "monthly_expense_basis": _monthly_basis(
            inputs.components.get("consumption"),
            run_rates.get("consumption", 0)),
        "assets": assets,
        "liabilities": liabilities,
        "financial_capital": financial_capital,
        "human_capital": human_capital,
        "other_benefits": other_benefits,
        "financial_liabilities": financial_liabilities,
        "future_consumption": future_consumption,
        "other_obligations": other_obligations,
        "total_economic_assets": total_assets,
        "total_economic_liabilities": total_liabilities,
        "accounting_net_worth": accounting_net_worth,
        "economic_net_worth": economic_net_worth,
    }


def _monthly_basis(comp: Component | None, run_rate: int) -> int:
    """The single monthly figure a line was valued from, for the report header:
    the scalar amount, the ledger run-rate for `auto`, else 0 (a `stream` has no
    single monthly figure)."""
    if comp is None:
        return 0
    if comp.mode == "scalar":
        return comp.amount or 0
    if comp.mode == "auto":
        return run_rate
    return 0


def _basis_line(data: dict) -> str:
    return (f"Discount {data['discount_rate_pct']:.1f}% | "
            f"income growth {data['income_growth_pct']:.1f}% | "
            f"inflation {data['inflation_pct']:.1f}% | "
            f"work {data['work_months'] // 12}y | "
            f"horizon {data['live_months'] // 12}y")


def _net_worth_cell(value: int, decimals: int, symbol: str) -> str:
    text = money(value, decimals, symbol, color_negative=False)
    return green(text) if value >= 0 else red(text)


def render_economic_balance_sheet(data: dict, decimals: int,
                                  symbol: str) -> str:
    lines = [bold("ECONOMIC BALANCE SHEET"),
             f"As of: {data['as_of'].isoformat()}",
             _basis_line(data), ""]
    table = Table(align="lr")

    def block(title: str, amounts: dict[str, int], total: int) -> None:
        table.add(bold(title), "")
        for name, amount in amounts.items():
            table.add("  " + name, money(amount, decimals))
        table.rule()
        table.add(bold(f"Total {title}"), money(total, decimals, symbol))
        table.add("", "")

    block("Economic Assets", data["assets"], data["total_economic_assets"])
    block("Economic Liabilities", data["liabilities"],
          data["total_economic_liabilities"])
    table.rule()
    table.add(bold("Economic Net Worth"),
              _net_worth_cell(data["economic_net_worth"], decimals, symbol))
    table.add("Accounting Net Worth",
              money(data["accounting_net_worth"], decimals, symbol))
    lines.append(table.render())
    return "\n".join(lines)


def render_economic_npv(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("ECONOMIC NET PRESENT VALUE"),
             f"As of: {data['as_of'].isoformat()}",
             _basis_line(data), ""]
    table = Table(align="lr")
    table.add("Financial capital (net)",
              money(data["financial_capital"] - data["financial_liabilities"],
                    decimals))
    table.add("+ Human capital", money(data["human_capital"], decimals))
    if data["other_benefits"]:
        table.add("+ Pensions / benefits",
                  money(data["other_benefits"], decimals))
    table.add("- Future consumption",
              money(-data["future_consumption"], decimals))
    if data["other_obligations"]:
        table.add("- Bequests / obligations",
                  money(-data["other_obligations"], decimals))
    table.rule()
    table.add(bold("Economic net worth (NPV)"),
              _net_worth_cell(data["economic_net_worth"], decimals, symbol))
    lines.append(table.render())
    return "\n".join(lines)


# -- markdown config document ------------------------------------------------
#
# The document is constrained markdown: a `## Settings` section (a two-column
# table or `key: value` lines) plus one `## <component>` section per line of the
# economic balance sheet. Each component section carries a `Mode:` line and, for
# scalar/stream modes, a pipe table of values. HTML comments are stripped before
# parsing, so commented-out example tables are ignored. Parsing is strict and
# fails loud (BeansError naming the offending section/field) rather than
# silently mis-reading a plan.

# Heading keyword -> component kind, checked in order (so "inheritance" wins
# over the "benefit"/"other" it also contains, and "bequest" over "obligation").
_HEADING_KINDS = [
    ("human capital", "income"),
    ("income", "income"),
    ("consumption", "consumption"),
    ("spending", "consumption"),
    ("inheritance", "inheritance"),
    ("pension", "pension"),
    ("benefit", "pension"),
    ("bequest", "bequest"),
    ("obligation", "other"),
    ("other", "other"),
]

_SETTING_KEYS = {"as_of", "discount_rate", "lookback_months", "work_years",
                 "live_years", "income_growth", "inflation"}


def write_template(led: Ledger, as_of: date | None = None,
                   discount_rate: Decimal = Decimal("0.03"), lookback: int = 12,
                   work_years: int = 25, live_years: int = 40,
                   income_growth: Decimal = Decimal("0.01"),
                   inflation: Decimal = Decimal("0.02")) -> str:
    """A self-documenting markdown config, pre-filled with the user's current
    income/expense run-rates so they start from realistic numbers."""
    as_of = as_of or date.today()
    decimals = led.decimals
    rates = _run_rates(
        led, EconomicInputs(as_of=as_of, discount_rate=discount_rate,
                            lookback=lookback), False, False)
    inc = format_amount(rates["income"] or 0, decimals)
    exp = format_amount(rates["consumption"] or 0, decimals)

    def pct(value: Decimal) -> str:
        return f"{float(value) * 100:.1f}%"

    return f"""# Economic balance sheet — inputs

<!-- Edit the values below, then run:  beans economic bs --file <this file>
     `Mode: auto` lets beans estimate the line from your ledger run-rate.
     `Mode: scalar` uses the single Amount/Growth/Years row.
     `Mode: stream` uses the dated rows (a value prevails until the next date).
     `Mode: none` excludes the line. Keep several files for scenarios. -->

## Settings

| Field | Value |
|---|---|
| as_of | {as_of.isoformat()} |
| discount_rate | {pct(discount_rate)} |
| lookback_months | {lookback} |
| work_years | {work_years} |
| live_years | {live_years} |
| income_growth | {pct(income_growth)} |
| inflation | {pct(inflation)} |

## Human capital — future income

Mode: auto

| Amount (monthly) | Growth | Years |
|---|---|---|
| {inc} | {pct(income_growth)} | {work_years} |

## Future consumption — spending

Mode: auto

| Amount (monthly) | Growth | Years |
|---|---|---|
| {exp} | {pct(inflation)} | {live_years} |

## Pension / benefits

Mode: none

| From (date) | Amount (monthly) | Growth |
|---|---|---|
| {add_months(as_of, work_years * 12).isoformat()} | 0 | 0% |

## Expected inheritance / other benefits

Mode: none

| Date | Amount |
|---|---|
| {add_months(as_of, 120).isoformat()} | 0 |

## Bequests / other obligations

Mode: none

| Amount (monthly) | Growth | Years |
|---|---|---|
| 0 | 0% | {live_years} |
"""


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(c and set(c) <= set("-: ") for c in cells)


def _tables(body: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    """Every pipe table in a section body as (header, data_rows)."""
    tables, current = [], []
    for line in body + [""]:
        if line.strip().startswith("|"):
            current.append(_cells(line))
        elif current:
            rows = [r for r in current if not _is_separator(r)]
            if rows:
                tables.append((rows[0], rows[1:]))
            current = []
    return tables


def _find_mode(body: list[str]) -> str | None:
    for line in body:
        m = re.match(r"^\s*mode\s*:\s*(\w+)\s*$", line, re.IGNORECASE)
        if m:
            return m.group(1).lower()
    return None


def _col(header: list[str], keyword: str) -> int | None:
    for i, cell in enumerate(header):
        if keyword in cell.lower():
            return i
    return None


def _cell(row: list[str], index: int | None) -> str:
    return row[index] if index is not None and index < len(row) else ""


def _parse_int(text: str, label: str) -> int:
    try:
        return int(str(text).strip())
    except ValueError:
        raise BeansError(f"invalid whole number for {label}: {text!r}")


def _heading_kind(heading_lower: str) -> str | None:
    for keyword, kind in _HEADING_KINDS:
        if keyword in heading_lower:
            return kind
    return None


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """Split into (heading, body) on `##` headings; preamble is ignored."""
    sections, heading, body = [], None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*\S)\s*$", line)
        if m:
            if heading is not None:
                sections.append((heading, body))
            heading, body = m.group(1).strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections.append((heading, body))
    return sections


def _norm_key(text: str) -> str:
    return text.strip().strip("*").strip().lower().replace(" ", "_")


def _parse_settings(heading: str, body: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in body:
        s = line.strip()
        if s.startswith("|"):
            cells = _cells(s)
            if len(cells) >= 2 and not _is_separator(cells):
                key = _norm_key(cells[0])
                if key and cells[1] and key not in ("field", "setting", "key"):
                    out[key] = cells[1]
        else:
            m = re.match(r"^[-*\s]*([\w ]+?)\s*:\s*(.+?)\s*$", s)
            if m:
                out[_norm_key(m.group(1))] = m.group(2).strip()
    for key in out:
        if key not in _SETTING_KEYS:
            raise BeansError(
                f"unknown setting {key!r} in Settings "
                f"(valid: {', '.join(sorted(_SETTING_KEYS))})")
    return out


def _parse_component(kind: str, heading: str, body: list[str],
                     decimals: int) -> Component:
    mode = _find_mode(body)
    if mode is None:
        raise BeansError(f"component {heading!r} is missing a 'Mode:' line")
    if mode not in COMPONENT_MODES:
        raise BeansError(
            f"invalid mode {mode!r} for {heading!r} "
            f"(expected {', '.join(COMPONENT_MODES)})")
    if mode == "auto" and kind not in _RUN_RATE_KINDS:
        raise BeansError(
            f"component {heading!r}: mode 'auto' is only available for income "
            "and consumption (nothing in the ledger estimates this line) — "
            "use scalar, stream, or none")
    comp = Component(kind=kind, mode=mode)
    if mode in ("auto", "none"):
        return comp

    tables = _tables(body)
    if not tables:
        raise BeansError(
            f"component {heading!r} has mode {mode!r} but no table of values")
    header, rows = tables[0]
    ai = _col(header, "amount")
    if ai is None:
        raise BeansError(f"component {heading!r} table needs an 'Amount' column")

    if mode == "scalar":
        if not rows:
            raise BeansError(
                f"component {heading!r} (scalar) needs one row of values")
        row = rows[0]
        comp.amount = parse_amount(_cell(row, ai), decimals)
        gi, yi = _col(header, "growth"), _col(header, "year")
        if _cell(row, gi):
            comp.growth = parse_percent(_cell(row, gi), allow_negative=True)
        if _cell(row, yi):
            comp.years = _parse_int(_cell(row, yi), f"{heading} years")
        return comp

    # mode == "stream": a piecewise monthly schedule has a start-date column
    # ("From", or "Date" alongside a Growth column signalling monthly amounts);
    # a bare Date/Amount table (no growth) is one-off dated lump sums.
    fi, di, gi = _col(header, "from"), _col(header, "date"), _col(header,
                                                                  "growth")
    start_i = fi if fi is not None else (di if gi is not None else None)
    if start_i is not None:
        for row in rows:
            growth = (parse_percent(_cell(row, gi), allow_negative=True)
                      if _cell(row, gi) else Decimal(0))
            comp.segments.append(Segment(parse_date(_cell(row, start_i)),
                                         parse_amount(_cell(row, ai), decimals),
                                         growth))
        for earlier, later in zip(comp.segments, comp.segments[1:]):
            if later.from_date <= earlier.from_date:
                raise BeansError(
                    f"component {heading!r} stream dates must be strictly "
                    "ascending")
    elif di is not None:
        for row in rows:
            comp.flows.append((parse_date(_cell(row, di)),
                               parse_amount(_cell(row, ai), decimals)))
    else:
        raise BeansError(
            f"component {heading!r} stream table needs a 'From' or 'Date' "
            "column")
    return comp


def _build_inputs(settings: dict[str, str],
                  components: dict[str, Component]) -> EconomicInputs:
    if "discount_rate" not in settings:
        raise BeansError(
            "economic config is missing the required setting 'discount_rate'")
    as_of = parse_date(settings["as_of"]) if "as_of" in settings \
        else date.today()
    lookback = (_parse_int(settings["lookback_months"], "lookback_months")
                if "lookback_months" in settings else 12)
    work_years = (_parse_int(settings["work_years"], "work_years")
                  if "work_years" in settings else 25)
    live_years = (_parse_int(settings["live_years"], "live_years")
                  if "live_years" in settings else 40)
    for name, value in (("lookback_months", lookback), ("work_years",
                        work_years), ("live_years", live_years)):
        if value < 1:
            raise BeansError(f"{name} must be at least 1")
    return EconomicInputs(
        as_of=as_of,
        discount_rate=parse_percent(settings["discount_rate"]),
        lookback=lookback, work_years=work_years, live_years=live_years,
        income_growth=(parse_percent(settings["income_growth"],
                                     allow_negative=True)
                       if "income_growth" in settings else Decimal(0)),
        inflation=(parse_percent(settings["inflation"], allow_negative=True)
                   if "inflation" in settings else Decimal(0)),
        components=components,
    )


def parse_config(text: str, led: Ledger) -> EconomicInputs:
    """Parse a markdown config document into resolved EconomicInputs."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    settings: dict[str, str] = {}
    components: dict[str, Component] = {}
    for heading, body in _sections(text):
        if "setting" in heading.lower():
            settings = _parse_settings(heading, body)
            continue
        kind = _heading_kind(heading.lower())
        if kind is None:
            if _find_mode(body) is not None:
                raise BeansError(
                    f"unknown economic component section: {heading!r}")
            continue
        components[kind] = _parse_component(kind, heading, body, led.decimals)
    return _build_inputs(settings, components)
