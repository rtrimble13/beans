#!/usr/bin/env python3
"""Establish whether this ledger can support a trend read — before reading one.

A trend over a ledger where a third of the spending sits in `Expenses:Other`
is a trend over a filing habit, not over spending. A trend that runs back past
the first transaction is a trend over structural zeros. Neither is visible in
the output once it has been drawn, so both are checked here, first, and said
out loud.

Everything is read-only. Exit status is 0 when the ledger is fit to analyze,
1 when a blocker was found — but read the JSON either way; a warning that does
not block still belongs in the briefing.

    ./preflight.py --months 12
    ./preflight.py --months 12 -f ~/.beans/ledger.db
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import calendar
from collections import Counter
from datetime import date, datetime
from decimal import Decimal

import beans_io as bio

# Accounts that mean "I have not decided yet". Spending parked here is
# invisible to a category trend, so its share is the headline data-quality
# number.
UNCATEGORIZED = ("Expenses:Other", "Expenses:Uncategorized",
                 "Expenses:Misc", "Expenses:Miscellaneous")

# Above this share of total expenses, per-category trends are not meaningful.
DEFAULT_UNCATEGORIZED_LIMIT = Decimal("25")


def default_ledger(explicit: str | None) -> str:
    if explicit:
        return explicit
    return os.environ.get("BEANS_LEDGER") or os.path.expanduser(
        "~/.beans/ledger.db")


def check(beans: str, ledger: str | None, months: int, grain: str,
          today: date, limit: Decimal) -> dict:
    warnings: list[str] = []
    blockers: list[str] = []
    report: dict = {
        "report": "beans-report/preflight",
        "generated": today.isoformat(),
        "ledger": default_ledger(ledger),
        "requested": {"periods": months, "grain": grain},
    }

    if not shutil.which(beans):
        blockers.append(
            f"`{beans}` is not on PATH — install beans, or pass --beans")
        report.update({"blockers": blockers, "warnings": warnings, "ok": False})
        return report

    # `--version` is a global flag, not a ledger command, so it bypasses the
    # read-only whitelist deliberately — it touches nothing.
    try:
        report["version"] = subprocess.run(
            [beans, "--version"], capture_output=True, text=True,
        ).stdout.strip() or None
    except OSError:                                     # pragma: no cover
        report["version"] = None

    # -- configuration -------------------------------------------------------
    try:
        text = bio.run_text(["config", "list"], beans=beans, ledger=ledger)
        config = {}
        for line in text.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()
        report["currency"] = config.get("currency", "USD")
        report["decimals"] = int(config.get("decimals", "2") or 2)
    except bio.BeansCommandError as exc:
        blockers.append(f"cannot read the ledger: {exc.stderr or exc}")
        report.update({"blockers": blockers, "warnings": warnings, "ok": False})
        return report

    decimals = report["decimals"]

    # -- period lock and the last complete period ---------------------------
    last_done = bio.last_complete(today, grain)
    report["last_complete_period"] = last_done
    report["excluded_partial"] = bio.shift(last_done, 1, grain)
    report["window"] = bio.period_keys(last_done, months, grain)

    try:
        status = bio.run_json(["status"], beans=beans, ledger=ledger)
        report["closed_through"] = status.get("closed_through")
    except bio.BeansCommandError:
        report["closed_through"] = None

    # -- coverage ------------------------------------------------------------
    try:
        transactions = bio.run_json(["tx", "list", "--period", "all"],
                                    beans=beans, ledger=ledger)
    except bio.BeansCommandError as exc:
        blockers.append(f"cannot list transactions: {exc.stderr or exc}")
        transactions = []

    live = [tx for tx in transactions if not tx.get("void")]
    report["transactions"] = len(live)
    report["voided"] = len(transactions) - len(live)
    if not live:
        blockers.append("the ledger has no transactions — nothing to trend")
    else:
        dates = sorted(tx["date"] for tx in live)
        report["first_transaction"], report["last_transaction"] = \
            dates[0], dates[-1]
        first_key = (dates[0][:7] if grain == "month"
                     else bio.quarter_key(
                         datetime.strptime(dates[0], "%Y-%m-%d").date()))
        covered = [key for key in report["window"] if key >= first_key]
        report["periods_covered"] = len(covered)
        uncovered = len(report["window"]) - len(covered)
        if uncovered:
            report["periods_before_first_transaction"] = uncovered
            warnings.append(
                f"{uncovered} of the {months} requested {grain}s predate the "
                f"first transaction ({dates[0]}); they are structural zeros, "
                f"not lean {grain}s. Consider --months {len(covered)}.")
        if len(covered) < 3:
            blockers.append(
                f"only {len(covered)} {grain}s of history are covered; a "
                "trend needs at least 3, and reads reliably from 6.")
        elif len(covered) < 6:
            warnings.append(
                f"only {len(covered)} {grain}s of history — findings are "
                "directional at best. Say so in the briefing.")

        # Sparse periods: a period with far fewer transactions than typical
        # usually means an unimported statement, not a frugal month.
        per_period = Counter(tx["date"][:7] for tx in live)
        in_window = [per_period.get(key, 0)
                     for key in report["window"] if key >= first_key]
        if in_window:
            typical = sorted(in_window)[len(in_window) // 2]
            sparse = [key for key in report["window"] if key >= first_key
                      and per_period.get(key, 0) * 3 < typical]
            if sparse:
                report["sparse_periods"] = sparse
                warnings.append(
                    "these periods have far fewer transactions than typical "
                    f"({', '.join(sparse)}) — check nothing is unimported "
                    "before reading them as low spending.")

    # -- how much spending is uncategorized ---------------------------------
    window = report["window"]
    if window:
        span_start, span_end = window[0], window[-1]
        try:
            whole = bio.run_json(["report", "income", "--from",
                                  _first_day(span_start, grain), "--to",
                                  _last_day(span_end, grain)],
                                 beans=beans, ledger=ledger)
        except bio.BeansCommandError:
            whole = None
        if whole:
            expenses = whole.get("expenses", {})
            total = bio.dec(whole.get("total_expenses"))
            parked = sum((bio.dec(value) for name, value in expenses.items()
                          if name in UNCATEGORIZED), Decimal(0))
            share = (parked / total * 100) if total else Decimal(0)
            report["uncategorized"] = {
                "amount": bio.money_str(parked, decimals),
                "total_expenses": bio.money_str(total, decimals),
                "pct": str(share.quantize(Decimal("0.1"))),
                "accounts": [name for name in expenses if name in UNCATEGORIZED],
            }
            if share >= limit:
                parked_in = ", ".join(report["uncategorized"]["accounts"])
                blockers.append(
                    f"{share.quantize(Decimal('0.1'))}% of spending in the "
                    f"window sits in {parked_in} — above the {limit}% limit. "
                    "Per-category trends are not meaningful until that is "
                    "categorized; totals still are.")
            elif share >= limit / 2:
                warnings.append(
                    f"{share.quantize(Decimal('0.1'))}% of spending is "
                    "uncategorized — category findings understate whatever is "
                    "hiding in there.")

    # -- context the briefing will want -------------------------------------
    for label, argv, key in (
        ("recurring rules", ["recur", "list"], "rules"),
        ("goals", ["goal", "list"], "rows"),
    ):
        try:
            data = bio.run_json(argv, beans=beans, ledger=ledger)
            report[argv[0]] = len(data.get(key, []))
        except bio.BeansCommandError:
            report[argv[0]] = None
    try:
        report["budgets"] = len(bio.run_json(["budget", "list"], beans=beans,
                                             ledger=ledger))
    except bio.BeansCommandError:
        report["budgets"] = None

    if not report.get("recur"):
        warnings.append("no recurring rules are defined — the skill cannot "
                        "check for subscription creep or lapsed payments.")
    if not report.get("budgets"):
        warnings.append("no budgets are set — budget calibration is "
                        "unavailable; report trends only.")

    report["warnings"] = warnings
    report["blockers"] = blockers
    report["ok"] = not blockers
    return report


def _first_day(key: str, grain: str) -> str:
    if grain == "quarter":
        year, quarter = key.split("-Q")
        return f"{int(year):04d}-{(int(quarter) - 1) * 3 + 1:02d}-01"
    return f"{key}-01"


def _last_day(key: str, grain: str) -> str:
    if grain == "quarter":
        year, quarter = key.split("-Q")
        year, month = int(year), int(quarter) * 3
    else:
        year, month = (int(part) for part in key.split("-"))
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check whether a beans ledger can support a trend read.")
    parser.add_argument("--months", "--periods", dest="months", type=int,
                        default=12, metavar="N")
    parser.add_argument("--grain", choices=["month", "quarter"],
                        default="month")
    parser.add_argument("--uncategorized-limit", type=Decimal,
                        default=DEFAULT_UNCATEGORIZED_LIMIT, metavar="PCT")
    parser.add_argument("--as-of", metavar="YYYY-MM-DD")
    parser.add_argument("--file", "-f", metavar="PATH")
    parser.add_argument("--beans", default="beans")
    parser.add_argument("-o", "--out", metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    today = (datetime.strptime(args.as_of, "%Y-%m-%d").date()
             if args.as_of else date.today())
    report = check(args.beans, args.file, args.months, args.grain, today,
                   args.uncategorized_limit)
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
