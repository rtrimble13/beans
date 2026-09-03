#!/usr/bin/env python3
"""Rewrite an awkward statement export into the shape `beans` reads.

Output is always `date,description,amount` (plus `category` when the source
had one and it was kept), with ISO dates and one signed amount where positive
means money into the account. Handles the structural differences that column
flags cannot: non-ISO dates, split debit/credit columns, parenthesised
negatives, CR/DR suffixes, and preamble lines above the header.

    python3 normalize_csv.py statement.csv -o work/checking-2026-10.csv
    python3 normalize_csv.py card.csv -o work/card.csv --invert --drop-category

Reads the original and writes a new file; the source is never modified.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inspect_csv import (  # noqa: E402
    CR_DR, PARENS, find_header, match_role, sniff_dialect,
)

DATE_FORMATS = [
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%m/%d/%Y", "MM/DD/YYYY"),
    ("%d/%m/%Y", "DD/MM/YYYY"),
    ("%m/%d/%y", "MM/DD/YY"),
    ("%d/%m/%y", "DD/MM/YY"),
    ("%Y/%m/%d", "YYYY/MM/DD"),
    ("%d-%b-%Y", "DD-Mon-YYYY"),
    ("%d %b %Y", "DD Mon YYYY"),
    ("%b %d, %Y", "Mon DD, YYYY"),
    ("%d.%m.%Y", "DD.MM.YYYY"),
]


class Unreadable(Exception):
    """The file cannot be normalized without a human decision."""


def detect_date_format(values: list[str], preferred: str | None = None):
    """Pick the one format that parses every sampled date.

    Ambiguity between MM/DD and DD/MM is resolved by evidence when the file
    contains a day past the 12th, and otherwise refused — guessing here
    silently mis-dates a whole statement.
    """
    if preferred:
        for fmt, label in DATE_FORMATS:
            if label.lower() == preferred.lower() or fmt == preferred:
                return fmt, label
        raise Unreadable(f"unknown date format {preferred!r}")
    scored = []
    for fmt, label in DATE_FORMATS:
        hits = 0
        for value in values:
            try:
                datetime.strptime(value, fmt)
            except ValueError:
                continue
            hits += 1
        if hits:
            scored.append((hits, fmt, label))
    # The best format need not parse every sampled cell: a trailing "TOTAL"
    # or a section header is not a date and is dropped later. It does have to
    # parse all but a couple, so a genuinely mixed file still fails here.
    best = max((s for s, _f, _l in scored), default=0)
    # Detection is permissive — a row the chosen format cannot read is
    # dropped, not mis-dated, and `normalize` refuses outright if too many
    # rows go that way. The tie check below is what guards against picking
    # the wrong reading, which is the failure that would be silent.
    tolerated = max(1, min(len(values) - 2, 0.8 * len(values)))
    if not best or best < tolerated:
        raise Unreadable(
            f"no known date format parses these dates (e.g. {values[:3]}). "
            "Pass --date-format, e.g. --date-format 'DD.MM.YYYY'.")
    workable = [(fmt, label) for hits, fmt, label in scored if hits == best]
    if len(workable) > 1:
        labels = [label for _fmt, label in workable]
        # Both readings work on this sample, so the file itself cannot
        # settle it. Refuse rather than mis-date the statement.
        raise Unreadable(
            "dates are ambiguous — " + " and ".join(labels) +
            " both parse every row. Ask the user which their bank uses, "
            "then pass --date-format.")
    return workable[0]


def parse_number(text: str) -> float | None:
    raw = (text or "").strip()
    if not raw:
        return None
    negative = bool(PARENS.match(raw))
    suffix = CR_DR.search(raw)
    raw = CR_DR.sub("", raw).strip().strip("()")
    raw = re.sub(r"[,\s$€£¥]", "", raw)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise Unreadable(f"cannot read {text!r} as an amount")
    if negative:
        value = -value
    if suffix and suffix.group(1).upper() == "DR":
        value = -abs(value)
    elif suffix and suffix.group(1).upper() == "CR":
        value = abs(value)
    return value


def normalize(path: Path, out: Path, *, date_col=None, desc_col=None,
              amount_col=None, debit_col=None, credit_col=None,
              category_col=None, drop_category=False, invert=False,
              date_format=None, force=False) -> dict:
    if out.exists() and not force:
        raise Unreadable(f"{out} already exists — pass --force to overwrite")
    delimiter = sniff_dialect(path.read_text(encoding="utf-8-sig",
                                             errors="replace")[:8192])
    header_line, fields = find_header(path, delimiter)
    if not fields:
        raise Unreadable("no header row found in the first 20 lines")

    date_col = date_col or match_role(fields, "date")
    desc_col = desc_col or match_role(fields, "description")
    amount_col = amount_col or match_role(fields, "amount")
    debit_col = debit_col or match_role(fields, "debit")
    credit_col = credit_col or match_role(fields, "credit")
    category_col = category_col or match_role(fields, "category")

    if not date_col:
        raise Unreadable("no date column — pass --date-col")
    if not amount_col and not (debit_col and credit_col):
        raise Unreadable("no amount column and no debit/credit pair — "
                         "pass --amount-col, or --debit-col and --credit-col")
    for name in (date_col, desc_col, amount_col, debit_col, credit_col,
                 category_col):
        if name and name not in fields:
            raise Unreadable(f"column {name!r} not in {path.name} "
                             f"(columns: {', '.join(fields)})")

    with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        for _ in range(header_line + 1):
            next(reader, None)
        raw_rows = [r for r in reader if any(c.strip() for c in r)]

    index = {name: fields.index(name) for name in fields}

    def cell(row, name):
        if not name:
            return ""
        i = index[name]
        return row[i].strip() if len(row) > i else ""

    samples = [cell(r, date_col) for r in raw_rows if cell(r, date_col)][:40]
    if not samples:
        raise Unreadable("no dates found in the data rows")
    fmt, label = detect_date_format(samples, date_format)

    keep_category = bool(category_col) and not drop_category
    columns = ["date", "description", "amount"]
    if keep_category:
        columns.append("category")

    rows, dropped = [], 0
    for lineno, row in enumerate(raw_rows, start=header_line + 2):
        raw_date = cell(row, date_col)
        if not raw_date:
            dropped += 1
            continue
        try:
            when = datetime.strptime(raw_date, fmt).date()
        except ValueError:
            # A trailing "Total" or summary row, not a transaction.
            dropped += 1
            continue
        if amount_col:
            amount = parse_number(cell(row, amount_col))
        else:
            debit = parse_number(cell(row, debit_col)) or 0.0
            credit = parse_number(cell(row, credit_col)) or 0.0
            # Whichever column is populated carries the magnitude; a debit
            # is money out. Already-negative debits are respected rather
            # than flipped twice.
            amount = credit - abs(debit) if debit else credit
        if amount is None:
            dropped += 1
            continue
        if invert:
            amount = -amount
        entry = [when.isoformat(), cell(row, desc_col), f"{amount:.2f}"]
        if keep_category:
            entry.append(cell(row, category_col))
        rows.append(entry)

    if not rows:
        raise Unreadable("no usable data rows after normalization")
    # A row or two is a summary line, a blank, or a section header. More
    # than that, and more than a fifth of the file, means the chosen date
    # format is wrong for part of it — quietly writing the rest would lose
    # transactions.
    if dropped > 2 and dropped > 0.2 * (len(rows) + dropped):
        raise Unreadable(
            f"{dropped} of {len(rows) + dropped} rows could not be read as "
            f"{label} dates. Check the file, or pass --date-format.")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)

    return {
        "source": str(path), "output": str(out), "rows": len(rows),
        "dropped": dropped, "date_format": label, "inverted": invert,
        "amount_source": (f"{debit_col}/{credit_col}" if not amount_col
                          else amount_col),
        "category": ("kept" if keep_category else
                     "dropped" if category_col else "none in source"),
        "columns": columns,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csvfile")
    parser.add_argument("--output", "-o", required=True,
                        help="where to write the normalized copy")
    parser.add_argument("--date-col")
    parser.add_argument("--desc-col")
    parser.add_argument("--amount-col")
    parser.add_argument("--debit-col")
    parser.add_argument("--credit-col")
    parser.add_argument("--category-col")
    parser.add_argument("--drop-category", action="store_true",
                        help="discard the issuer's category column so the "
                             "ledger's own history decides instead")
    parser.add_argument("--invert", action="store_true",
                        help="flip every sign, for card exports reporting "
                             "purchases as positive")
    parser.add_argument("--date-format",
                        help="force a date format, e.g. 'DD/MM/YYYY', when "
                             "the file itself cannot settle it")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing output file")
    args = parser.parse_args(argv)

    path = Path(args.csvfile).expanduser()
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    try:
        result = normalize(
            path, Path(args.output).expanduser(),
            date_col=args.date_col, desc_col=args.desc_col,
            amount_col=args.amount_col, debit_col=args.debit_col,
            credit_col=args.credit_col, category_col=args.category_col,
            drop_category=args.drop_category, invert=args.invert,
            date_format=args.date_format, force=args.force,
        )
    except Unreadable as exc:
        print(f"cannot normalize {path.name}: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {result['rows']} row(s) to {result['output']}")
    print(f"  dates      {result['date_format']} -> YYYY-MM-DD")
    print(f"  amounts    from {result['amount_source']}"
          + ("  (inverted)" if result["inverted"] else ""))
    print(f"  category   {result['category']}")
    if result["dropped"]:
        print(f"  skipped    {result['dropped']} non-transaction row(s) "
              "(blank, total, or unparseable date)")
    print(f"\nNext: beans categorize {result['output']} --account ACCOUNT "
          "-o work/prepared.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
