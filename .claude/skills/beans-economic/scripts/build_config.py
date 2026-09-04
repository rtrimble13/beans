#!/usr/bin/env python3
"""Turn answers about someone's life into a `beans economic` config document.

The six lines of an economic balance sheet are assumptions, not measurements —
four of them cannot be derived from the ledger at all. Eliciting them is a
conversation; this script is only the part that must not be done by hand:
choosing the right table shape for each mode, writing every rate in a form
`beans` reads the way it was meant, and proving the result parses before
anyone relies on it.

It never overwrites an existing document (that is someone's plan) and never
lets a broken one land: the file is rendered, validated by actually running
`beans economic npv --file`, and only then moved into place.

    ./build_config.py answers.json -o plan.md
    cat answers.json | ./build_config.py - -o plan.md --ledger ~/.beans/ledger.db

The answers schema is in `references/config-format.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime

import econ_io as eio

# kind -> (heading, side). The headings are chosen so beans' own
# `_heading_kind` keyword match lands on the intended line — including "Other
# obligations", which the stock `create-template` has no section for at all.
LINES: dict[str, str] = {
    "income": "Human capital — future income",
    "consumption": "Future consumption — spending",
    "pension": "Pension / benefits",
    "inheritance": "Expected inheritance",
    "bequest": "Bequests",
    "other": "Other obligations",
}
# `auto` estimates from the ledger run-rate, which only exists for these two.
AUTO_KINDS = ("income", "consumption")
MODES = ("auto", "scalar", "stream", "none")

REQUIRED_SETTINGS = ("discount_rate",)
RATE_SETTINGS = {"discount_rate": False, "income_growth": True,
                 "inflation": True}
INT_SETTINGS = ("work_years", "live_years", "lookback_months")

DEFAULTS = {"discount_rate": "3%", "income_growth": "0%", "inflation": "0%",
            "work_years": 25, "live_years": 40, "lookback_months": 12}


class InvalidAnswers(Exception):
    """The answers do not describe a config that could be written."""


def _clean(text) -> str:
    """Notes go into the document body; a pipe would be read as a table."""
    return str(text).replace("|", "/").strip()


def _date(value, field: str) -> date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise InvalidAnswers(f"{field}: {value!r} is not a YYYY-MM-DD date")


def _amount(value, field: str) -> str:
    try:
        return eio.money_str(eio.dec(value))
    except Exception:
        raise InvalidAnswers(f"{field}: {value!r} is not an amount")


def validate(answers: dict) -> dict:
    """Normalize and check the answers, raising on anything beans would
    reject later — or worse, accept and misread."""
    if not isinstance(answers, dict):
        raise InvalidAnswers("answers must be a JSON object")

    settings = dict(DEFAULTS)
    settings.update(answers.get("settings") or {})
    for key in REQUIRED_SETTINGS:
        if not settings.get(key):
            raise InvalidAnswers(f"settings.{key} is required")
    rates = {}
    for key, signed in RATE_SETTINGS.items():
        rates[key] = eio.parse_rate(settings[key], field=f"settings.{key}",
                                    allow_negative=signed)
    ints = {}
    for key in INT_SETTINGS:
        try:
            ints[key] = int(settings[key])
        except (TypeError, ValueError):
            raise InvalidAnswers(f"settings.{key}: {settings[key]!r} is not a "
                                 "whole number")
        if ints[key] < 1:
            raise InvalidAnswers(f"settings.{key} must be at least 1")

    as_of = (_date(answers["as_of"], "as_of") if answers.get("as_of")
             else date.today())

    lines = answers.get("lines") or {}
    unknown = set(lines) - set(LINES)
    if unknown:
        raise InvalidAnswers(
            f"unknown line(s): {', '.join(sorted(unknown))}. "
            f"Expected any of: {', '.join(LINES)}")

    resolved = {}
    for kind in LINES:
        # A line nobody mentioned is excluded — but that is a claim about
        # someone's life, so it is recorded as one, never left implicit.
        spec = dict(lines.get(kind) or {"mode": "none",
                                        "note": "not discussed"})
        mode = str(spec.get("mode", "none")).lower()
        if mode not in MODES:
            raise InvalidAnswers(
                f"lines.{kind}.mode={mode!r} (expected {', '.join(MODES)})")
        if mode == "auto" and kind not in AUTO_KINDS:
            raise InvalidAnswers(
                f"lines.{kind}: mode 'auto' works only for "
                f"{' and '.join(AUTO_KINDS)} — nothing in the ledger "
                "estimates this line. Use scalar, stream, or none.")
        entry = {"mode": mode, "note": _clean(spec.get("note", ""))}

        if mode == "scalar":
            if spec.get("amount") is None:
                raise InvalidAnswers(f"lines.{kind}: scalar needs an amount")
            entry["amount"] = _amount(spec["amount"], f"lines.{kind}.amount")
            entry["growth"] = eio.parse_rate(
                spec.get("growth", "0%"), field=f"lines.{kind}.growth",
                allow_negative=True)
            # `spec.get("years")` would treat 0 as absent and silently fall
            # back to the default horizon; 0 is a mistake, not an omission.
            if spec.get("years") is None:
                entry["years"] = None
            else:
                try:
                    entry["years"] = int(spec["years"])
                except (TypeError, ValueError):
                    raise InvalidAnswers(
                        f"lines.{kind}.years: {spec['years']!r} is not a "
                        "whole number")
                if entry["years"] < 1:
                    raise InvalidAnswers(
                        f"lines.{kind}.years must be at least 1")

        elif mode == "stream":
            segments, flows = spec.get("segments"), spec.get("flows")
            if bool(segments) == bool(flows):
                raise InvalidAnswers(
                    f"lines.{kind}: stream needs exactly one of `segments` (a "
                    "monthly schedule) or `flows` (dated lump sums)")
            if segments:
                rows = []
                for index, seg in enumerate(segments):
                    rows.append({
                        "from": _date(seg.get("from"),
                                      f"lines.{kind}.segments[{index}].from"),
                        "amount": _amount(
                            seg.get("amount", 0),
                            f"lines.{kind}.segments[{index}].amount"),
                        "growth": eio.parse_rate(
                            seg.get("growth", "0%"),
                            field=f"lines.{kind}.segments[{index}].growth",
                            allow_negative=True),
                    })
                for earlier, later in zip(rows, rows[1:]):
                    if later["from"] <= earlier["from"]:
                        raise InvalidAnswers(
                            f"lines.{kind}: stream dates must strictly "
                            f"ascend ({earlier['from']} then {later['from']})")
                entry["segments"] = rows
            else:
                entry["flows"] = [
                    {"date": _date(flow.get("date"),
                                   f"lines.{kind}.flows[{index}].date"),
                     "amount": _amount(flow.get("amount", 0),
                                       f"lines.{kind}.flows[{index}].amount")}
                    for index, flow in enumerate(flows)
                ]
        resolved[kind] = entry

    return {"as_of": as_of, "rates": rates, "ints": ints, "lines": resolved}


def render(spec: dict) -> str:
    """Render the validated answers as a beans economic config document."""
    rates, ints = spec["rates"], spec["ints"]
    excluded = [kind for kind, line in spec["lines"].items()
                if line["mode"] == "none"]
    out = [
        "# Economic balance sheet — inputs",
        "",
        "<!-- Written by the beans-economic skill from answers you gave, and",
        "     validated by running `beans economic npv --file` against it.",
        "     Every figure below is an ASSUMPTION. None of it is posted to",
        "     your ledger; only Financial Capital comes from the books.",
        f"     Re-run with:  beans economic bs --file <this file>  -->",
        "",
        "## Settings",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| as_of | {spec['as_of'].isoformat()} |",
        f"| discount_rate | {eio.rate_str(rates['discount_rate'])} |",
        f"| lookback_months | {ints['lookback_months']} |",
        f"| work_years | {ints['work_years']} |",
        f"| live_years | {ints['live_years']} |",
        f"| income_growth | {eio.rate_str(rates['income_growth'])} |",
        f"| inflation | {eio.rate_str(rates['inflation'])} |",
        "",
    ]
    if excluded:
        out += [
            "<!-- EXCLUDED LINES. Each of these is modelled as zero, which is",
            "     a claim about this household, not an absence of one:",
        ] + [f"       {LINES[kind]}"
             + (f" — {spec['lines'][kind]['note']}"
                if spec["lines"][kind]["note"] else "")
             for kind in excluded] + ["  -->", ""]

    for kind, heading in LINES.items():
        line = spec["lines"][kind]
        out += [f"## {heading}", ""]
        if line["note"]:
            out += [line["note"], ""]
        out += [f"Mode: {line['mode']}", ""]

        if line["mode"] == "scalar":
            years = line["years"] if line["years"] is not None else (
                ints["work_years"] if kind == "income" else ints["live_years"])
            out += ["| Amount (monthly) | Growth | Years |",
                    "|---|---|---|",
                    f"| {line['amount']} | {eio.rate_str(line['growth'])} "
                    f"| {years} |", ""]
        elif line["mode"] == "stream" and line.get("segments"):
            out += ["| From (date) | Amount (monthly) | Growth |",
                    "|---|---|---|"]
            out += [f"| {row['from'].isoformat()} | {row['amount']} "
                    f"| {eio.rate_str(row['growth'])} |"
                    for row in line["segments"]]
            out += [""]
        elif line["mode"] == "stream":
            # A lump-sum table must NOT carry a Growth column — that is how
            # beans tells one-off flows from a monthly schedule.
            out += ["| Date | Amount |", "|---|---|"]
            out += [f"| {row['date'].isoformat()} | {row['amount']} |"
                    for row in line["flows"]]
            out += [""]
    return "\n".join(out).rstrip() + "\n"


def validate_against_beans(text: str, *, beans: str, ledger: str | None):
    """Prove the document parses, by running the real command against it."""
    handle, path = tempfile.mkstemp(suffix=".md", text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
        return eio.run_json(["economic", "npv", "--file", path],
                            beans=beans, ledger=ledger)
    finally:
        os.unlink(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a validated `beans economic` config from answers.")
    parser.add_argument("answers", nargs="?", default="-",
                        help="answers JSON (default: stdin)")
    parser.add_argument("-o", "--out", required=True, metavar="PATH",
                        help="where to write the config document")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing document (it is somebody's "
                             "plan; prefer a new name)")
    parser.add_argument("--no-validate", action="store_true",
                        help="skip the beans round-trip (for tests)")
    parser.add_argument("--file", "-f", dest="ledger", metavar="PATH",
                        help="ledger file")
    parser.add_argument("--beans", default="beans", help="beans executable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    raw = (sys.stdin.read() if args.answers == "-"
           else open(args.answers, encoding="utf-8").read())
    try:
        answers = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: answers are not JSON ({exc})", file=sys.stderr)
        return 2

    if os.path.exists(args.out) and not args.force:
        print(f"error: {args.out} already exists — that is someone's plan. "
              "Write a new file, or pass --force if you are sure.",
              file=sys.stderr)
        return 2

    try:
        spec = validate(answers)
        text = render(spec)
    except (InvalidAnswers, eio.AmbiguousRate) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = None
    if not args.no_validate:
        try:
            result = validate_against_beans(text, beans=args.beans,
                                            ledger=args.ledger)
        except eio.BeansCommandError as exc:
            print("error: the document this produced does not parse — that is "
                  "a bug in the skill, not in your answers.", file=sys.stderr)
            print(f"  {exc.stderr}", file=sys.stderr)
            return 1

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)

    excluded = [LINES[kind] for kind, line in spec["lines"].items()
                if line["mode"] == "none"]
    print(f"wrote {args.out}", file=sys.stderr)
    if result:
        print(f"  economic net worth: {result['economic_net_worth']} "
              f"(accounting: {result['accounting_net_worth']})",
              file=sys.stderr)
    if excluded:
        print(f"  modelled as zero: {', '.join(excluded)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
