#!/usr/bin/env python3
"""What does this economic balance sheet actually depend on?

`beans economic bs` answers "what is my economic net worth". That number is a
model output, not a measurement: on one real ledger it ranges from -$114,890
to +$1,069,480 depending only on assumptions nobody validated. Quoting the
point estimate alone is the single output shape that misleads.

So this script quotes the range instead. It re-runs the model across each
assumption in turn and reports:

  * the span each input produces, ranked — which one to go and think about;
  * whether an input is INERT, because a stream-mode config pins it and the
    global setting no longer does anything;
  * whether the input is monotonic, because the discount rate is not: it
    discounts human capital AND future consumption, over different horizons,
    so "be conservative, raise the rate" moves the answer in a direction that
    depends on where you started;
  * the SIGN-FLIP boundary — the value at which economic net worth crosses
    zero — which is the most useful single sentence this analysis produces.

Costs one `beans economic npv` run per grid point (roughly 30-50 runs, a few
seconds). Everything is read-only.

    ./sensitivity.py --file plan.md
    ./sensitivity.py --file plan.md --compare retire-early.md
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

import econ_io as eio

# Grids are absolute for rates (a plausible band) and relative for horizons
# (a life decision is "five years earlier", not "at 3%").
RATE_GRIDS = {
    "discount_rate": ["1%", "2%", "3%", "4%", "5%", "6%", "7%"],
    "income_growth": ["0%", "1%", "2%", "3%", "4%"],
    "inflation": ["0%", "1%", "2%", "3%", "4%"],
}
HORIZON_OFFSETS = (-10, -5, 0, 5, 10)

FLAGS = {"discount_rate": "--rate", "income_growth": "--growth",
         "inflation": "--inflation", "work_years": "--work-years",
         "live_years": "--live-years"}
LABELS = {"discount_rate": "discount rate", "income_growth": "income growth",
          "inflation": "inflation", "work_years": "years until you stop working",
          "live_years": "planning horizon"}


def run(flags: list[str], *, config: str | None, beans: str,
        ledger: str | None) -> dict:
    argv = ["economic", "npv"]
    if config:
        argv += ["--file", config]
    return eio.run_json(argv + flags, beans=beans, ledger=ledger)


def base_assumptions(data: dict) -> dict:
    """The assumptions actually in force, read back from the report rather
    than from what we think we passed."""
    return {
        "discount_rate": Decimal(str(data["discount_rate_pct"])) / 100,
        "income_growth": Decimal(str(data["income_growth_pct"])) / 100,
        "inflation": Decimal(str(data["inflation_pct"])) / 100,
        "work_years": int(data["work_months"]) // 12,
        "live_years": int(data["live_months"]) // 12,
    }


def _bisect_zero(parameter: str, low, high, *, config, beans, ledger,
                 is_rate: bool, rounds: int = 14):
    """Find where economic net worth crosses zero between two grid points."""
    def value_at(x):
        text = eio.rate_str(x, places=4) if is_rate else str(int(round(x)))
        result = run([FLAGS[parameter], text], config=config, beans=beans,
                     ledger=ledger)
        return text, eio.dec(result["economic_net_worth"])

    lo_text, lo_val = value_at(low)
    hi_text, hi_val = value_at(high)
    if (lo_val > 0) == (hi_val > 0):
        return None
    for _ in range(rounds):
        mid = (low + high) / 2
        mid_text, mid_val = value_at(mid)
        if (mid_val > 0) == (lo_val > 0):
            low, lo_val, lo_text = mid, mid_val, mid_text
        else:
            high, hi_val, hi_text = mid, mid_val, mid_text
        if not is_rate and abs(high - low) <= 1:
            break
    return {"crosses_between": [lo_text, hi_text],
            "boundary": hi_text if lo_val > 0 else lo_text,
            "direction": ("negative above" if lo_val > 0
                          else "negative below")}


def sweep(parameter: str, base: dict, *, config, beans, ledger,
          decimals: int) -> dict:
    is_rate = parameter in RATE_GRIDS
    if is_rate:
        values = list(RATE_GRIDS[parameter])
        numeric = [eio.parse_rate(v, field=parameter, allow_negative=True)
                   for v in values]
    else:
        anchor = base[parameter]
        numeric = sorted({max(1, anchor + off) for off in HORIZON_OFFSETS})
        values = [str(v) for v in numeric]

    points = []
    for text in values:
        result = run([FLAGS[parameter], text], config=config, beans=beans,
                     ledger=ledger)
        points.append({"value": text,
                       "economic_net_worth": result["economic_net_worth"]})

    worths = [eio.dec(p["economic_net_worth"]) for p in points]
    low, high = min(worths), max(worths)
    span = high - low
    rising = all(b >= a for a, b in zip(worths, worths[1:]))
    falling = all(b <= a for a, b in zip(worths, worths[1:]))

    out = {
        "parameter": parameter,
        "label": LABELS[parameter],
        "flag": FLAGS[parameter],
        "points": points,
        "min": eio.money_str(low, decimals),
        "max": eio.money_str(high, decimals),
        "span": eio.money_str(span, decimals),
        "monotonic": bool(rising or falling),
        # A span of zero means the config pins this line — a stream-mode
        # schedule carries its own growth, so the global setting is dead.
        "inert": span == 0,
    }
    if not (rising or falling):
        peak = max(range(len(worths)), key=lambda i: worths[i])
        out["note"] = (
            f"not monotonic — economic net worth peaks at "
            f"{points[peak]['value']} and falls away on both sides, so "
            "moving this in the 'conservative' direction does not reliably "
            "lower the answer")

    for (a_text, a_val), (b_text, b_val) in zip(
            zip(values, worths), zip(values[1:], worths[1:])):
        if (a_val > 0) != (b_val > 0):
            found = _bisect_zero(
                parameter, numeric[values.index(a_text)],
                numeric[values.index(b_text)], config=config, beans=beans,
                ledger=ledger, is_rate=is_rate)
            if found:
                out["sign_flip"] = found
            break
    return out


def compare(base_config, other_config, *, beans, ledger, decimals) -> dict:
    left = run([], config=base_config, beans=beans, ledger=ledger)
    right = run([], config=other_config, beans=beans, ledger=ledger)
    fields = ("economic_net_worth", "human_capital", "future_consumption",
              "other_benefits", "other_obligations", "financial_capital")
    rows = []
    for field in fields:
        if field not in left or field not in right:
            continue
        delta = eio.dec(right[field]) - eio.dec(left[field])
        rows.append({"field": field, "base": left[field],
                     "other": right[field],
                     "delta": eio.signed_str(delta, decimals)})
    return {"base_config": base_config or "(no config)",
            "other_config": other_config, "rows": rows}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report what an economic balance sheet depends on.")
    parser.add_argument("--file", dest="config", metavar="PATH",
                        help="economic config document (else CLI defaults)")
    parser.add_argument("--sweep", metavar="LIST",
                        default=",".join(FLAGS),
                        help="comma-separated parameters to sweep "
                             f"(default: all of {', '.join(FLAGS)})")
    parser.add_argument("--compare", metavar="PATH",
                        help="also diff against a second config document")
    parser.add_argument("-f", "--ledger", metavar="PATH", help="ledger file")
    parser.add_argument("--beans", default="beans", help="beans executable")
    parser.add_argument("-o", "--out", metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    meta = eio.read_config_meta(args.beans, args.ledger)
    decimals = meta["decimals"]

    wanted = [p.strip() for p in args.sweep.split(",") if p.strip()]
    unknown = [p for p in wanted if p not in FLAGS]
    if unknown:
        print(f"error: unknown parameter(s): {', '.join(unknown)}. "
              f"Choose from {', '.join(FLAGS)}.", file=sys.stderr)
        return 2

    try:
        base_run = run([], config=args.config, beans=args.beans,
                       ledger=args.ledger)
    except eio.BeansCommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    base = base_assumptions(base_run)

    sweeps = [sweep(parameter, base, config=args.config, beans=args.beans,
                    ledger=args.ledger, decimals=decimals)
              for parameter in wanted]
    ranked = sorted((s for s in sweeps if not s["inert"]),
                    key=lambda s: eio.dec(s["span"]), reverse=True)

    result = {
        "report": "beans-economic/sensitivity",
        "config": args.config,
        "base": {
            "economic_net_worth": base_run["economic_net_worth"],
            "accounting_net_worth": base_run["accounting_net_worth"],
            "assumptions": {
                "discount_rate": eio.rate_str(base["discount_rate"]),
                "income_growth": eio.rate_str(base["income_growth"]),
                "inflation": eio.rate_str(base["inflation"]),
                "work_years": base["work_years"],
                "live_years": base["live_years"],
            },
            "monthly_income_basis": base_run.get("monthly_income_basis"),
            "monthly_expense_basis": base_run.get("monthly_expense_basis"),
        },
        "sweeps": sweeps,
        "drivers": [s["parameter"] for s in ranked],
        "inert": [s["parameter"] for s in sweeps if s["inert"]],
        "sign_flips": {s["parameter"]: s["sign_flip"] for s in sweeps
                       if "sign_flip" in s},
        "currency": meta["currency"],
    }
    if args.compare:
        result["comparison"] = compare(args.config, args.compare,
                                       beans=args.beans, ledger=args.ledger,
                                       decimals=decimals)

    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"wrote {args.out} — {len(sweeps)} sweeps, "
              f"{len(result['sign_flips'])} sign flip(s)", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
