#!/usr/bin/env python3
"""Work out the shape of a statement CSV, and say which `beans` flags it needs.

`beans` is strict about two things — dates must be YYYY-MM-DD, and the amount
must be one signed column — and has no header alias table. Most real exports
satisfy neither. This reads a file and reports what it actually found, so the
mapping is derived from the file rather than guessed at.

    python3 inspect_csv.py statement.csv
    python3 inspect_csv.py statement.csv --json

Writes nothing and never touches a ledger.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# Header spellings seen in the wild, mapped to the role beans needs filled.
# Order matters within a role: earlier entries win when a file has several.
HEADER_HINTS = {
    "date": ["posting date", "post date", "posted date", "transaction date",
             "trans date", "date", "value date", "settlement date"],
    "description": ["description", "memo", "payee", "name", "details",
                    "narrative", "transaction description", "merchant"],
    "amount": ["amount", "transaction amount", "amount (usd)", "value",
               "net amount"],
    "debit": ["debit", "withdrawal", "withdrawals", "money out", "paid out",
              "debit amount"],
    "credit": ["credit", "deposit", "deposits", "money in", "paid in",
               "credit amount"],
    "category": ["category", "transaction category", "type of transaction"],
    "balance": ["balance", "running balance", "ledger balance",
                "balance (usd)"],
}

ISO = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
SLASHED = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")
NAMED = re.compile(r"^\d{1,2}[- ][A-Za-z]{3,}[- ]\d{2,4}$")
PARENS = re.compile(r"^\(.*\)$")
CR_DR = re.compile(r"\b(CR|DR)\b", re.IGNORECASE)
MONEYISH = re.compile(r"^[+-]?[$€£¥]?[\d,]+(\.\d+)?$")

# Rows whose sign is legitimately the other way on a card statement, and
# which would otherwise dilute the "purchases are positive" signal.
NOT_A_PURCHASE = re.compile(
    r"payment|thank you|autopay|auto pay|pymt|refund|return|reversal|"
    r"transfer|xfer|credit adjustment", re.IGNORECASE)


def sniff_dialect(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def find_header(path: Path, delimiter: str) -> tuple[int, list[str]]:
    """Return (0-based line index, fields) of the real header row.

    Some exports put account blurb above the header, so the first line is
    not always it. The header is the first row where at least two cells
    look like known column names.
    """
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
        for index, row in enumerate(csv.reader(fh, delimiter=delimiter)):
            if index > 20:
                break
            cells = [c.strip().lower() for c in row if c.strip()]
            if len(cells) < 2:
                continue
            known = sum(1 for c in cells
                        for names in HEADER_HINTS.values() if c in names)
            if known >= 2:
                return index, row
    return 0, []


def match_role(fields: list[str], role: str) -> str | None:
    lowered = {f.strip().lower(): f for f in fields}
    for candidate in HEADER_HINTS[role]:
        if candidate in lowered:
            return lowered[candidate]
    return None


def classify_date(values: list[str]) -> tuple[str, bool]:
    """(described format, is it ISO and therefore usable as-is)."""
    if not values:
        return "unknown (no data rows)", False
    if all(ISO.match(v) for v in values):
        return "YYYY-MM-DD (ISO)", True
    parts = [SLASHED.match(v) for v in values]
    if all(parts):
        firsts = [int(m.group(1)) for m in parts if m]
        seconds = [int(m.group(2)) for m in parts if m]
        if any(n > 12 for n in firsts):
            return "DD/MM/YYYY", False
        if any(n > 12 for n in seconds):
            return "MM/DD/YYYY", False
        return "MM/DD/YYYY or DD/MM/YYYY (ambiguous — confirm with the user)", False
    if all(NAMED.match(v) for v in values):
        return "DD-Mon-YYYY", False
    return "unrecognized", False


def clean_number(text: str) -> float | None:
    raw = text.strip()
    if not raw:
        return None
    negative = bool(PARENS.match(raw))
    raw = CR_DR.sub("", raw).strip().strip("()")
    raw = re.sub(r"[,\s$€£¥]", "", raw)
    try:
        value = float(raw)
    except ValueError:
        return None
    return -value if negative else value


def inspect(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    delimiter = sniff_dialect(text[:8192])
    header_line, fields = find_header(path, delimiter)
    if not fields:
        return {"file": str(path), "error":
                "no header row found in the first 20 lines"}

    with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        for _ in range(header_line + 1):
            next(reader, None)
        rows = [r for r in reader if any(c.strip() for c in r)]

    def column(name: str | None) -> list[str]:
        if not name or name not in fields:
            return []
        idx = fields.index(name)
        return [r[idx].strip() for r in rows if len(r) > idx and r[idx].strip()]

    roles = {role: match_role(fields, role) for role in HEADER_HINTS}
    date_values = column(roles["date"])[:40]
    date_format, date_ok = classify_date(date_values)

    raw_amounts = column(roles["amount"])
    amounts = [a for a in (clean_number(v) for v in raw_amounts)
               if a is not None]
    split = bool(roles["debit"] and roles["credit"]) and not roles["amount"]

    # Sign convention, judged on purchases only: every card statement carries
    # at least one payment row whose sign is legitimately the other way, and
    # counting those hides the signal on a short file.
    purchases = []
    if roles["amount"] and roles["description"]:
        d_idx = fields.index(roles["description"])
        a_idx = fields.index(roles["amount"])
        for row in rows:
            if len(row) <= max(d_idx, a_idx):
                continue
            if NOT_A_PURCHASE.search(row[d_idx]):
                continue
            value = clean_number(row[a_idx])
            if value is not None:
                purchases.append(value)
    judged = purchases or amounts
    positives = sum(1 for a in judged if a > 0)
    mostly_positive = bool(judged) and positives / len(judged) > 0.8
    has_parens = any(PARENS.match(v) for v in raw_amounts)
    has_crdr = any(CR_DR.search(v) for v in raw_amounts)

    findings, flags, rewrite = [], [], []

    if not roles["date"]:
        findings.append("No recognizable date column — ask the user which one it is.")
    elif date_ok:
        if roles["date"].strip().lower() != "date":
            flags.append(f'--date-col "{roles["date"]}"')
    else:
        rewrite.append(f"dates are {date_format}; beans accepts only YYYY-MM-DD")

    if roles["description"] and roles["description"].strip().lower() != "description":
        flags.append(f'--desc-col "{roles["description"]}"')
    if not roles["description"]:
        findings.append("No description column — history-based categorization "
                        "cannot work without one.")

    if split:
        rewrite.append(f'debit/credit are split across '
                       f'"{roles["debit"]}" and "{roles["credit"]}"')
    elif not roles["amount"]:
        findings.append("No amount column found — ask the user which one it is.")
    else:
        if roles["amount"].strip().lower() != "amount":
            flags.append(f'--amount-col "{roles["amount"]}"')
        if has_parens:
            rewrite.append("negatives are written as (45.00), which "
                           "parse_amount rejects")
        if has_crdr:
            rewrite.append("amounts carry CR/DR suffixes")
        if mostly_positive:
            findings.append(
                f"{positives} of {len(judged)} non-payment amounts are "
                "positive — this "
                "looks like a card export reporting purchases as positive. "
                "Confirm with the user, then use --invert.")
            flags.append("--invert")

    if roles["category"]:
        if roles["category"].strip().lower() != "category":
            flags.append(f'--category-col "{roles["category"]}"')
        findings.append(
            f'A "{roles["category"]}" column is present. beans scores a '
            "pre-filled category 1.00 and never second-guesses it — fine if "
            "the user filled it in, risky if the card issuer did. Spot-check "
            "it or drop the column.")

    if roles["balance"]:
        tail = column(roles["balance"])
        if tail:
            findings.append(
                f'Running balance column "{roles["balance"]}" ends at '
                f"{tail[-1]} — that is the statement's ending balance for "
                "`beans reconcile ACCOUNT --balance`.")

    if header_line:
        rewrite.append(f"{header_line} preamble line(s) sit above the header")

    return {
        "file": str(path),
        "delimiter": delimiter,
        "header_line": header_line + 1,
        "columns": fields,
        "roles": {k: v for k, v in roles.items() if v},
        "data_rows": len(rows),
        "date_format": date_format,
        "amount_style": ("split debit/credit" if split
                         else "single signed column" if roles["amount"]
                         else "unknown"),
        "needs_rewrite": rewrite,
        "beans_flags": flags,
        "findings": findings,
    }


def render(data: dict) -> str:
    if "error" in data:
        return f"{data['file']}: {data['error']}"
    out = [f"{data['file']}  —  {data['data_rows']} data row(s), "
           f"delimiter {data['delimiter']!r}, header on line "
           f"{data['header_line']}", ""]
    out.append("Columns: " + ", ".join(data["columns"]))
    out.append("Mapped:  " + ", ".join(f"{k}={v!r}"
                                       for k, v in data["roles"].items()))
    out.append(f"Dates:   {data['date_format']}")
    out.append(f"Amounts: {data['amount_style']}")
    out.append("")
    if data["needs_rewrite"]:
        out.append("NEEDS normalize_csv.py — beans cannot read this as-is:")
        out += [f"  - {r}" for r in data["needs_rewrite"]]
        out.append("")
    if data["beans_flags"]:
        out.append("beans flags: " + " ".join(data["beans_flags"]))
        out.append("")
    if not data["needs_rewrite"] and not data["beans_flags"]:
        out.append("Ready to use as-is: default column names, ISO dates, "
                   "signed amounts.")
        out.append("")
    if data["findings"]:
        out.append("Check with the user:")
        out += [f"  - {f}" for f in data["findings"]]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csvfile")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    args = parser.parse_args(argv)
    path = Path(args.csvfile).expanduser()
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    data = inspect(path)
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 1 if "error" in data else 0


if __name__ == "__main__":
    raise SystemExit(main())
