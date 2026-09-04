#!/usr/bin/env python3
"""What is actually known before any assumption is made?

An economic balance sheet has exactly one line that comes from the books —
Financial Capital — and five that come from somebody's beliefs about their own
life. Two of those five can be *estimated* from the ledger run-rate, and the
quality of that estimate is the thing nobody checks: a twenty-five year human
capital projection resting on six months of history is a fact the briefing has
to carry, not a detail.

So this runs first and reports the provenance: what `auto` would use, how much
history stands behind it, whether the run-rate is stable or drifting, and which
defaults are in force. Read-only.

    ./preflight.py
    ./preflight.py --lookback 12 --work-years 25 -f ~/.beans/ledger.db
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal

import econ_io as eio

# `beans economic bs` (no config) and `beans economic create-template` do not
# agree on these two, and the gap is large. Report which set is in force so a
# user who tries both paths is not left wondering why the answers differ.
CLI_DEFAULTS = {"income_growth": "0%", "inflation": "0%"}
TEMPLATE_DEFAULTS = {"income_growth": "1%", "inflation": "2%"}


def default_ledger(explicit: str | None) -> str:
    if explicit:
        return explicit
    return os.environ.get("BEANS_LEDGER") or os.path.expanduser(
        "~/.beans/ledger.db")


def check(*, beans: str, ledger: str | None, lookback: int, work_years: int,
          live_years: int, today: date) -> dict:
    warnings: list[str] = []
    blockers: list[str] = []
    report: dict = {
        "report": "beans-economic/preflight",
        "generated": today.isoformat(),
        "ledger": default_ledger(ledger),
    }

    if not shutil.which(beans):
        blockers.append(f"`{beans}` is not on PATH — install beans, or pass "
                        "--beans")
        return {**report, "blockers": blockers, "warnings": warnings,
                "ok": False}
    try:
        report["version"] = subprocess.run(
            [beans, "--version"], capture_output=True, text=True,
        ).stdout.strip() or None
    except OSError:                                     # pragma: no cover
        report["version"] = None

    meta = eio.read_config_meta(beans, ledger)
    report.update(currency=meta["currency"], decimals=meta["decimals"])

    # -- the one line that is not an assumption -----------------------------
    try:
        base = eio.run_json(["economic", "npv", "--lookback", str(lookback)],
                            beans=beans, ledger=ledger)
    except eio.BeansCommandError as exc:
        blockers.append(f"cannot read the ledger: {exc.stderr or exc}")
        return {**report, "blockers": blockers, "warnings": warnings,
                "ok": False}

    report["financial_capital"] = base["financial_capital"]
    report["accounting_net_worth"] = base["accounting_net_worth"]
    report["auto_basis"] = {
        "monthly_income": base.get("monthly_income_basis"),
        "monthly_expense": base.get("monthly_expense_basis"),
        "lookback_months": lookback,
    }
    report["defaults_in_force"] = {
        "note": ("`beans economic bs` with no config document uses these; "
                 "`beans economic create-template` pre-fills different ones "
                 "(income_growth 1%, inflation 2%), so the two entry points "
                 "disagree until you set them explicitly."),
        "cli": CLI_DEFAULTS,
        "template": TEMPLATE_DEFAULTS,
    }

    # -- how much history stands behind that run-rate -----------------------
    try:
        transactions = eio.run_json(["tx", "list", "--period", "all"],
                                    beans=beans, ledger=ledger)
    except eio.BeansCommandError:
        transactions = []
    live = [tx for tx in transactions if not tx.get("void")]
    if not live:
        blockers.append("the ledger has no transactions — there is no "
                        "run-rate to project, so every line would be an "
                        "assertion")
    else:
        dates = sorted(tx["date"] for tx in live)
        first = datetime.strptime(dates[0], "%Y-%m-%d").date()
        months = max(1, (today.year - first.year) * 12
                     + (today.month - first.month))
        report["history"] = {"first_transaction": dates[0],
                             "last_transaction": dates[-1],
                             "months_available": months,
                             "transactions": len(live)}
        if months < lookback:
            warnings.append(
                f"the ledger holds {months} months but the run-rate looks "
                f"back {lookback} — the estimate is averaging over months "
                "that do not exist.")
        # The ratio that actually matters, stated as a ratio.
        report["projection_leverage"] = {
            "history_months": months,
            "projected_months": work_years * 12,
            "ratio": f"1:{round(work_years * 12 / months)}",
        }
        if months < 12:
            warnings.append(
                f"{months} months of history is being projected {work_years} "
                f"years forward (1:{round(work_years * 12 / months)}). Say so "
                "whenever you quote human capital.")

        # A run-rate is only meaningful if it is not moving. `report trend`
        # exists since beans 1.1; on an older one this is simply skipped.
        try:
            trend = eio.run_json(
                ["report", "trend", "--periods", str(min(12, months))],
                beans=beans, ledger=ledger)
        except eio.BeansCommandError:
            trend = None
        if trend:
            movers = [row for row in trend.get("accounts", [])
                      if row["type"] in ("income", "expense")]
            report["run_rate_stability"] = [
                {"account": row["account"], "first": row["first"],
                 "last": row["last"], "change": row["change"]}
                for row in movers[:5]
            ]
            drifting = [row for row in movers
                        if abs(eio.dec(row["change"]))
                        > abs(eio.dec(row["average"])) * Decimal("0.15")]
            if drifting:
                warnings.append(
                    "the run-rate is not flat — "
                    + ", ".join(row["account"] for row in drifting[:3])
                    + " moved more than 15% across the window. A flat "
                      "annuity off a drifting base understates or overstates "
                      "for the whole horizon.")

    if live_years <= work_years:
        warnings.append(
            f"the planning horizon ({live_years}y) is not longer than the "
            f"working horizon ({work_years}y) — that models someone who stops "
            "spending when they stop earning.")

    report["warnings"] = warnings
    report["blockers"] = blockers
    report["ok"] = not blockers
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report what is known before any assumption is made.")
    parser.add_argument("--lookback", type=int, default=12, metavar="N")
    parser.add_argument("--work-years", type=int, default=25, metavar="N")
    parser.add_argument("--live-years", type=int, default=40, metavar="N")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD")
    parser.add_argument("-f", "--file", dest="ledger", metavar="PATH")
    parser.add_argument("--beans", default="beans")
    parser.add_argument("-o", "--out", metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    today = (datetime.strptime(args.as_of, "%Y-%m-%d").date()
             if args.as_of else date.today())
    report = check(beans=args.beans, ledger=args.ledger,
                   lookback=args.lookback, work_years=args.work_years,
                   live_years=args.live_years, today=today)
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
