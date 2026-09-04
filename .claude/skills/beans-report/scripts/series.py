#!/usr/bin/env python3
"""Gather many periods of `beans` reports into one series.

`beans` reports a period at a time: every statement except `networth` is a
snapshot, and `--compare` reaches exactly one period back. Answering "is this
drifting?" therefore means running the same report across N periods and lining
the results up — which is all this script does. It runs read-only commands and
copies the figures they print. **It performs no financial arithmetic**: every
amount in the output came verbatim from a `beans --json` report, so a number
here can always be traced back to a command you can re-run yourself.

The current period is excluded by default. See `last_complete` in beans_io.

    ./series.py --months 12                     # totals + per-account series
    ./series.py --months 12 --ratios --budgets  # add analyze/budget per period
    ./series.py --grain quarter --periods 8
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

import beans_io as bio

# Ratio fields lifted verbatim from `beans analyze --json`.
RATIO_FIELDS = ("savings_rate_pct", "liquidity_months", "current_ratio",
                "quick_ratio", "debt_to_assets_pct",
                "debt_to_annual_income_pct", "net_worth", "cash")


def read_config(beans: str, ledger: str | None) -> dict:
    """currency and decimals from `beans config list` (which has no --json)."""
    out = {"currency": "USD", "decimals": 2}
    try:
        text = bio.run_text(["config", "list"], beans=beans, ledger=ledger)
    except bio.BeansCommandError:
        return out
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key == "currency":
            out["currency"] = value
        elif key == "decimals" and value.isdigit():
            out["decimals"] = int(value)
    return out


def months_between(first: str, second: str) -> int:
    """Whole months from ``first`` to ``second`` (YYYY-MM keys)."""
    fy, fm = (int(p) for p in first.split("-"))
    sy, sm = (int(p) for p in second.split("-"))
    return (sy * 12 + sm) - (fy * 12 + fm)


def anchor_month(key: str, grain: str) -> str:
    """The month a period ends in — a quarter's series lines up with the
    month-end net-worth rows through its final month."""
    if grain != "quarter":
        return key
    year, quarter = key.split("-Q")
    return f"{int(year):04d}-{int(quarter) * 3:02d}"


def gather(*, count: int, grain: str, end_key: str, beans: str,
           ledger: str | None, want_ratios: bool, want_budgets: bool,
           today: date) -> dict:
    keys = bio.period_keys(end_key, count, grain)
    config = read_config(beans, ledger)
    errors: list[dict] = []

    def attempt(label: str, argv: list[str]):
        try:
            return bio.run_json(argv, beans=beans, ledger=ledger)
        except bio.BeansCommandError as exc:
            errors.append({"period": label, "command": " ".join(argv),
                           "error": exc.stderr or str(exc)})
            return None

    # -- income statement per period (the backbone of the series) ------------
    statements: dict[str, dict] = {}
    for key in keys:
        data = attempt(key, ["report", "income", "--period", key])
        if data is not None:
            statements[key] = data

    # Union of every account seen, so each account has a value in every period.
    # An account absent from a period's statement had no flow that period,
    # which is a real zero — not a gap.
    names: set[str] = set()
    for data in statements.values():
        names.update(data.get("income", {}))
        names.update(data.get("expenses", {}))

    accounts: dict[str, list[str | None]] = {}
    for name in sorted(names):
        row = []
        for key in keys:
            data = statements.get(key)
            if data is None:
                row.append(None)          # the command failed; not a zero
                continue
            side = data.get("income", {}) if name.startswith("Income:") \
                else data.get("expenses", {})
            row.append(side.get(name, bio.money_str(bio.dec(0),
                                                    config["decimals"])))
        accounts[name] = row

    totals = {
        field: [statements[key].get(field) if key in statements else None
                for key in keys]
        for field in ("total_income", "total_expenses", "net_income")
    }

    # A period with no income and no expenses is structurally empty — usually
    # before the ledger's first transaction. Flag it; do not silently trend it.
    empty = [key for key in keys
             if key in statements
             and bio.dec(statements[key].get("total_income")) == 0
             and bio.dec(statements[key].get("total_expenses")) == 0]

    result = {
        "report": "beans-report/series",
        "generated": today.isoformat(),
        "grain": grain,
        "count": len(keys),
        "currency": config["currency"],
        "decimals": config["decimals"],
        "window": {"first": keys[0], "last": keys[-1]} if keys else {},
        "excluded_partial": (bio.shift(end_key, 1, grain)
                             if end_key == bio.last_complete(today, grain)
                             else None),
        "periods": keys,
        "labels": {key: statements[key].get("period")
                   for key in keys if key in statements},
        "totals": totals,
        "accounts": accounts,
        "empty_periods": empty,
    }

    # -- month-end net worth (one call, already a series) --------------------
    if keys:
        span = months_between(anchor_month(keys[0], grain),
                              bio.month_key(today)) + 1
        trend = attempt("net_worth", ["networth", "--months", str(span)])
        if trend:
            wanted = {anchor_month(key, grain) for key in keys}
            result["net_worth"] = [row for row in trend.get("rows", [])
                                   if row.get("month") in wanted]

    # -- optional per-period ratios -----------------------------------------
    if want_ratios:
        ratios: dict[str, list] = {field: [] for field in RATIO_FIELDS}
        for key in keys:
            data = attempt(key, ["analyze", "--period", key])
            for field in RATIO_FIELDS:
                ratios[field].append(data.get(field) if data else None)
        result["ratios"] = ratios

    # -- optional per-period budget variance --------------------------------
    if want_budgets:
        budgets = {}
        for key in keys:
            data = attempt(key, ["budget", "report", "--period", key])
            if data and data.get("rows"):
                budgets[key] = data["rows"]
        result["budgets"] = budgets

    if errors:
        result["errors"] = errors
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gather N periods of beans reports into one series.")
    parser.add_argument("--months", "--periods", dest="count", type=int,
                        default=12, metavar="N",
                        help="how many periods to gather (default 12)")
    parser.add_argument("--grain", choices=["month", "quarter"],
                        default="month")
    parser.add_argument("--end", metavar="KEY",
                        help="last period to include (default: the last "
                             "COMPLETE period before today)")
    parser.add_argument("--include-partial", action="store_true",
                        help="include the period in progress. Off by "
                             "default: a part-elapsed period reads as a "
                             "collapse that never happened.")
    parser.add_argument("--ratios", action="store_true",
                        help="also gather `beans analyze` per period")
    parser.add_argument("--budgets", action="store_true",
                        help="also gather `beans budget report` per period")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD",
                        help="treat this date as today (for tests)")
    parser.add_argument("--file", "-f", metavar="PATH", help="ledger file")
    parser.add_argument("--beans", default="beans", help="beans executable")
    parser.add_argument("-o", "--out", metavar="PATH",
                        help="write JSON here instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    today = (datetime.strptime(args.as_of, "%Y-%m-%d").date()
             if args.as_of else date.today())
    if args.count < 1:
        print("error: need at least one period", file=sys.stderr)
        return 2

    end_key = args.end
    if not end_key:
        end_key = (bio.month_key(today) if args.grain == "month"
                   else bio.quarter_key(today)) if args.include_partial \
            else bio.last_complete(today, args.grain)

    try:
        data = gather(count=args.count, grain=args.grain, end_key=end_key,
                      beans=args.beans, ledger=args.file,
                      want_ratios=args.ratios, want_budgets=args.budgets,
                      today=today)
    except bio.NotReadOnly as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except bio.BeansCommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(data, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"wrote {args.out} — {data['count']} {data['grain']}s "
              f"({data['window'].get('first')} … "
              f"{data['window'].get('last')})", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
