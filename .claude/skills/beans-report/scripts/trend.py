#!/usr/bin/env python3
"""Classify a `series.py` series: drift, step, one-off, new, stopped, stable.

Reading a financial series is where the mistakes live. An average moved by a
single vet bill looks exactly like an average moved by twelve months of
creeping grocery prices, and only one of them is worth telling someone about.
So the arithmetic lives here — in a tested script — rather than being done by
eye, and it is deliberately **robust**: a median-of-pairwise-slopes
(Theil–Sen) fit and median-absolute-deviation noise bands, both of which
ignore a lone spike instead of being dragged around by it.

Two thresholds, kept separate on purpose:

* **scale** — is this distinguishable from the series' own noise? Statistical.
* **materiality** — is it big enough that a person should care? Economic,
  expressed as a share of typical monthly income.

A finding must clear both. That is what keeps a briefing to four lines instead
of thirty.

    ./series.py --months 12 -o series.json
    ./trend.py series.json
    ./trend.py series.json --floor-pct 2 --scope expenses
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

import beans_io as bio

# Classifications, most structural first — the order they are tested in.
STOPPED, NEW = "stopped", "new"
DRIFT, STEP, ONE_OFF, STABLE = "drift", "step", "one-off", "stable"
INSUFFICIENT = "insufficient-data"

# How many noise-widths a move must clear to count as signal rather than
# wobble. 3 is the usual robust-statistics convention and is deliberately
# conservative: this skill's failure mode is crying wolf about someone's money.
SIGMA = 3


# -- robust statistics -------------------------------------------------------

def median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def mad(values: list[Decimal], center: Decimal) -> Decimal:
    """Median absolute deviation from ``center`` — a noise width that one
    outlier cannot inflate, unlike a standard deviation."""
    return median([abs(value - center) for value in values]) or Decimal(0)


def theil_sen(points: list[tuple[int, Decimal]]) -> Decimal:
    """Median of the pairwise slopes. Robust to roughly a third of the points
    being outliers, which a least-squares fit is not."""
    slopes = []
    for i in range(len(points)):
        xi, yi = points[i]
        for j in range(i + 1, len(points)):
            xj, yj = points[j]
            if xj != xi:
                slopes.append((yj - yi) / (xj - xi))
    return median(slopes) or Decimal(0)


def linear_fit(points):
    """Theil–Sen slope with a median intercept; returns (slope, intercept,
    residuals)."""
    slope = theil_sen(points)
    intercept = median([y - slope * x for x, y in points]) or Decimal(0)
    residuals = [y - (intercept + slope * x) for x, y in points]
    return slope, intercept, residuals


def best_step(points):
    """Find the breakpoint that best splits the series into two flat halves.

    Returns (index, left_median, right_median, within_scale, cost). The scale
    is measured *within* each half — measuring it globally would make a clean
    step its own noise floor, and no step would ever be detectable.
    """
    values = [y for _x, y in points]
    n = len(values)
    best = None
    for split in range(1, n):
        left, right = values[:split], values[split:]
        if not left or not right:
            continue
        left_med, right_med = median(left), median(right)
        residuals = ([y - left_med for y in left]
                     + [y - right_med for y in right])
        cost = sum(abs(r) for r in residuals)
        if best is None or cost < best[0]:
            best = (cost, split, left_med, right_med, residuals)
    if best is None:
        return None
    cost, split, left_med, right_med, residuals = best
    return {"index": split, "left": left_med, "right": right_med,
            "diff": right_med - left_med,
            "scale": mad(residuals, Decimal(0)), "cost": cost}


# -- classification ----------------------------------------------------------

def _floor(scale: Decimal, decimals: int) -> Decimal:
    """Never let a noise width be zero: a perfectly flat series would make
    every subsequent cent look like a signal."""
    unit = Decimal(1).scaleb(-decimals)
    return max(scale, unit)


def _run(values: list[Decimal], from_end: bool, zero: bool) -> int:
    """Length of the leading (or trailing) run of zero — or non-zero —
    values."""
    ordered = list(reversed(values)) if from_end else values
    run = 0
    for value in ordered:
        if (value != 0) if zero else (value == 0):
            break
        run += 1
    return run


def classify(raw: list, *, decimals: int = 2, min_periods: int = 6) -> dict:
    """Classify one series of period values (money strings, or None where the
    underlying command failed)."""
    points = [(index, bio.dec(value))
              for index, value in enumerate(raw) if value is not None]
    n = len(points)
    result: dict = {"periods_used": n, "periods_given": len(raw)}
    if n < max(3, min(min_periods, 3)) or n < 3:
        return {**result, "classification": INSUFFICIENT,
                "reason": f"only {n} usable periods"}

    values = [y for _x, y in points]
    latest, first = values[-1], values[0]
    centre = median(values)
    result.update({
        "latest": bio.money_str(latest, decimals),
        "first": bio.money_str(first, decimals),
        "median": bio.money_str(centre, decimals),
        "min": bio.money_str(min(values), decimals),
        "max": bio.money_str(max(values), decimals),
    })

    # -- structural shapes first: an account that started or stopped is not a
    # -- trend, and describing it as one buries the actual news.
    # `stopped` and `new` describe a *standing* payment appearing or
    # lapsing, so both require the payment to have been recurring — two or
    # more periods. A single payment in an otherwise empty series is a
    # one-off, and calling it a cancelled subscription would be a fiction.
    trailing = _run(values, from_end=True, zero=True)
    leading = _run(values, from_end=False, zero=True)
    live_before = sum(1 for value in values[:n - trailing] if value != 0)
    live_after = _run(values, from_end=True, zero=False)
    if trailing >= 2 and live_before >= 2:
        prior = median([v for v in values[:n - trailing] if v != 0]) \
            or Decimal(0)
        return {**result, "classification": STOPPED,
                "direction": "down",
                "zero_periods": trailing,
                "prior_typical": bio.money_str(prior, decimals),
                "change": bio.signed_str(-prior, decimals),
                "magnitude": bio.money_str(prior, decimals)}
    if leading >= 2 and live_after >= 2:
        recent = median([v for v in values[leading:] if v != 0]) or Decimal(0)
        return {**result, "classification": NEW,
                "direction": "up",
                "absent_periods": leading,
                "change": bio.signed_str(recent, decimals),
                "magnitude": bio.money_str(recent, decimals)}

    # -- competing models: a line, a step, and a flat median ----------------
    slope, _intercept, residuals = linear_fit(points)
    lin_scale = _floor(mad(residuals, Decimal(0)), decimals)
    lin_cost = sum(abs(r) for r in residuals)
    span = points[-1][0] - points[0][0]
    drift = slope * span

    step = best_step(points)
    step_scale = _floor(step["scale"], decimals) if step else None

    const_scale = _floor(mad(values, centre), decimals)
    outliers = [{"index": x, "value": bio.money_str(y, decimals),
                 "deviation": bio.signed_str(y - centre, decimals)}
                for x, y in points if abs(y - centre) > SIGMA * const_scale]

    drift_sig = abs(drift) >= SIGMA * lin_scale
    step_sig = bool(step) and abs(step["diff"]) >= SIGMA * step_scale

    result.update({
        "monthly_slope": bio.signed_str(slope, decimals),
        "noise_width": bio.money_str(lin_scale, decimals),
        "outliers": outliers,
    })

    if drift_sig and step_sig:
        # Both fit. Believe whichever explains the series better; a tie goes
        # to the step, which claims less (one change, not a standing trend).
        drift_sig = lin_cost < step["cost"]
        step_sig = not drift_sig

    if drift_sig:
        return {**result, "classification": DRIFT,
                "direction": "up" if drift > 0 else "down",
                "change": bio.signed_str(drift, decimals),
                "magnitude": bio.money_str(abs(drift), decimals),
                "per_period": bio.signed_str(slope, decimals),
                "annualized": bio.signed_str(slope * 12, decimals)}
    if step_sig:
        return {**result, "classification": STEP,
                "direction": "up" if step["diff"] > 0 else "down",
                "break_index": step["index"],
                "before": bio.money_str(step["left"], decimals),
                "after": bio.money_str(step["right"], decimals),
                "change": bio.signed_str(step["diff"], decimals),
                "magnitude": bio.money_str(abs(step["diff"]), decimals)}
    if outliers:
        worst = max(outliers,
                    key=lambda o: abs(bio.dec(o["deviation"])))
        return {**result, "classification": ONE_OFF,
                "direction": "up" if bio.dec(worst["deviation"]) > 0
                else "down",
                "change": worst["deviation"],
                "magnitude": bio.money_str(abs(bio.dec(worst["deviation"])),
                                           decimals)}
    return {**result, "classification": STABLE, "direction": "flat",
            "change": bio.signed_str(Decimal(0), decimals),
            "magnitude": bio.money_str(Decimal(0), decimals)}


# -- driving it over a whole series ------------------------------------------

def typical_income(series: dict) -> Decimal:
    """Median income per period — the yardstick materiality is measured in."""
    values = [bio.dec(v) for v in series.get("totals", {})
              .get("total_income", []) if v is not None]
    return median(values) or Decimal(0)


def analyze(series: dict, *, scope: str = "all", floor_pct: Decimal,
            floor_abs: Decimal, min_periods: int) -> dict:
    decimals = int(series.get("decimals", 2))
    income = typical_income(series)
    materiality = max(floor_abs, income * floor_pct / 100)

    targets: list[tuple[str, str, list]] = []
    totals = series.get("totals", {})
    if scope in ("all", "totals"):
        for field in ("total_income", "total_expenses", "net_income"):
            if field in totals:
                targets.append((field, "total", totals[field]))
    if scope in ("all", "expenses", "income"):
        for name, values in series.get("accounts", {}).items():
            side = "income" if name.startswith("Income:") else "expenses"
            if scope in ("all", side):
                targets.append((name, side, values))

    findings, immaterial = [], 0
    for name, kind, values in targets:
        verdict = classify(values, decimals=decimals, min_periods=min_periods)
        verdict.update({"name": name, "kind": kind})
        if verdict["classification"] in (STABLE, INSUFFICIENT):
            continue
        magnitude = bio.dec(verdict.get("magnitude", "0"))
        if magnitude < materiality:
            immaterial += 1
            continue
        verdict["pct_of_typical_income"] = (
            str((magnitude / income * 100).quantize(Decimal("0.1")))
            if income else None)
        findings.append(verdict)

    findings.sort(key=lambda f: bio.dec(f.get("magnitude", "0")), reverse=True)
    return {
        "report": "beans-report/trend",
        "grain": series.get("grain"),
        "window": series.get("window"),
        "periods": series.get("periods"),
        "excluded_partial": series.get("excluded_partial"),
        "currency": series.get("currency"),
        "typical_income": bio.money_str(income, decimals),
        "materiality": bio.money_str(materiality, decimals),
        "materiality_note": (
            f"moves below {bio.money_str(materiality, decimals)} "
            f"({floor_pct}% of typical period income) are not reported"),
        "sigma": SIGMA,
        "findings": findings,
        "immaterial_count": immaterial,
        "empty_periods": series.get("empty_periods", []),
        "errors": series.get("errors", []),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify a beans series into drift / step / one-off / "
                    "new / stopped / stable.")
    parser.add_argument("series", nargs="?", default="-",
                        help="series.py JSON (default: stdin)")
    parser.add_argument("--scope",
                        choices=["all", "totals", "expenses", "income"],
                        default="all")
    parser.add_argument("--floor-pct", type=Decimal, default=Decimal("1"),
                        metavar="P",
                        help="ignore moves smaller than P%% of typical period "
                             "income (default 1)")
    parser.add_argument("--floor-abs", type=Decimal, default=Decimal("0"),
                        metavar="AMOUNT",
                        help="also ignore moves below this absolute amount")
    parser.add_argument("--min-periods", type=int, default=6, metavar="N",
                        help="below this, findings are reported with low "
                             "confidence (hard minimum 3)")
    parser.add_argument("-o", "--out", metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    text = sys.stdin.read() if args.series == "-" \
        else open(args.series, encoding="utf-8").read()
    try:
        series = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"error: input is not JSON ({exc}). Pipe series.py output in.",
              file=sys.stderr)
        return 2
    if series.get("report") != "beans-report/series":
        print("error: input is not a series.py document", file=sys.stderr)
        return 2

    result = analyze(series, scope=args.scope, floor_pct=args.floor_pct,
                     floor_abs=args.floor_abs, min_periods=args.min_periods)
    if len(series.get("periods", [])) < args.min_periods:
        result["confidence"] = (
            f"low — {len(series.get('periods', []))} periods is fewer than "
            f"the {args.min_periods} this reads reliably from")
    out = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(out + "\n")
        print(f"wrote {args.out} — {len(result['findings'])} findings",
              file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
