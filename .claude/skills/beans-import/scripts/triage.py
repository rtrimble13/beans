#!/usr/bin/env python3
"""Group a prepared CSV's uncertain rows by merchant, so review is one pass.

`beans categorize -o` writes one row per transaction, sorted by file order.
Review is per *merchant*, not per row: six visits to the same new coffee shop
is one decision, not six. This regroups the file that way, separates thin
evidence from conflicting evidence (which need opposite responses), flags the
transfer/refund traps, and — when `beans` is on PATH — validates every proposed
account against the live chart so a typo surfaces here rather than at import.

    python3 triage.py work/prepared.csv
    python3 triage.py work/prepared.csv --threshold 0.8 --json

Reads only. Writes nothing, changes nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Rows worth a human's attention below this confidence. Not a threshold beans
# knows or honours — beans deliberately has none — purely a display cutoff for
# this report. Nothing is ever accepted or rejected on it.
DEFAULT_THRESHOLD = 0.75

_DIGITS = re.compile(r"\d+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")

# Descriptor fragments that are almost never an expense. Money moving between
# the user's own accounts, booked as an expense, double-counts it.
TRANSFER_HINTS = [
    "transfer", "xfer", "payment thank you", "online payment",
    "autopay", "auto pay", "card payment", "pymt", "bill pay",
    "to savings", "from savings", "to checking", "from checking",
    "atm withdrawal", "cash withdrawal", "internal transfer",
]
REFUND_HINTS = ["refund", "return", "reversal", "credit adjustment",
                "chargeback"]


def merchant_key(text: str) -> str:
    """Mirror of beans/classify.py merchant_key: digits are noise."""
    lowered = _PUNCT.sub(" ", (text or "").lower())
    return " ".join(_DIGITS.sub(" ", lowered).split())


def chart_accounts() -> set[str] | None:
    """Account names the ledger actually has, or None if beans is unreachable."""
    try:
        done = subprocess.run(["beans", "account", "list", "--names"],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


def read_prepared(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
        for required in ("date", "description", "amount"):
            if required not in fields:
                raise SystemExit(
                    f"{path} does not look like a prepared CSV: no "
                    f"{required!r} column (columns: "
                    f"{', '.join(reader.fieldnames or [])})")
        rows = []
        for lineno, raw in enumerate(reader, start=2):
            def get(name):
                return (raw.get(fields.get(name, ""), "") or "").strip()
            if not get("date") and not get("amount"):
                continue
            try:
                amount = float(re.sub(r"[,\s$€£¥]", "", get("amount")) or 0)
            except ValueError:
                amount = 0.0
            try:
                confidence = float(get("confidence") or 0)
            except ValueError:
                confidence = 0.0
            rows.append({
                "line": lineno, "date": get("date"),
                "description": get("description"), "amount": amount,
                "category": get("category"), "confidence": confidence,
                "basis": get("basis"),
            })
    return rows


def evidence_kind(basis: str) -> str:
    """Thin and conflicting evidence score alike and need opposite responses."""
    if not basis or basis == "no match":
        return "none"
    if basis.startswith("rule "):
        return "rule"
    if basis == "already set":
        return "column"
    if ":" in basis and "/" in basis:
        return "conflicting"
    if basis.lstrip("~").split()[0].isdigit() or basis.startswith("~"):
        return "thin"
    return "other"


def flags_for(description: str) -> list[str]:
    lowered = (description or "").lower()
    found = []
    if any(hint in lowered for hint in TRANSFER_HINTS):
        found.append("looks like a TRANSFER — counter-account is the other "
                     "account, not an expense")
    if any(hint in lowered for hint in REFUND_HINTS):
        found.append("looks like a REFUND — usually nets against the original "
                     "expense account, not income")
    return found


def triage(path: Path, threshold: float) -> dict:
    rows = read_prepared(path)
    accounts = chart_accounts()

    groups: dict[str, dict] = defaultdict(
        lambda: {"rows": [], "accounts": set(), "kinds": set(),
                 "flags": set(), "total": 0.0})
    for row in rows:
        group = groups[merchant_key(row["description"]) or "(no description)"]
        group["rows"].append(row)
        group["total"] += row["amount"]
        group["kinds"].add(evidence_kind(row["basis"]))
        group["flags"].update(flags_for(row["description"]))
        if row["category"]:
            group["accounts"].add(row["category"])

    needs_review, settled, unknown_accounts = [], 0, set()
    for key, group in groups.items():
        blank = [r for r in group["rows"] if not r["category"]]
        worst = min(r["confidence"] for r in group["rows"])
        for name in group["accounts"]:
            if accounts is not None and name not in accounts:
                unknown_accounts.add(name)
        interesting = (blank or worst < threshold or group["flags"]
                       or len(group["accounts"]) > 1
                       or (accounts is not None
                           and group["accounts"] - accounts))
        if not interesting:
            settled += len(group["rows"])
            continue
        sample = group["rows"][0]
        kinds = group["kinds"] - {"other"}
        needs_review.append({
            "merchant": key,
            "example": sample["description"],
            "rows": len(group["rows"]),
            "lines": [r["line"] for r in group["rows"]],
            "total": round(group["total"], 2),
            "confidence": worst,
            "proposed": sorted(group["accounts"]),
            "basis": sample["basis"],
            "evidence": ("conflicting" if "conflicting" in kinds
                         else "none" if "none" in kinds
                         else "thin" if "thin" in kinds
                         else "settled"),
            "unresolved_rows": len(blank),
            "flags": sorted(group["flags"]),
            "rule_candidate": bool(
                len(group["rows"]) > 1 and "conflicting" not in kinds
                and not group["flags"]),
        })

    # Least certain first, then the merchants you will see most often.
    needs_review.sort(key=lambda g: (g["confidence"], -g["rows"]))
    return {
        "file": str(path),
        "threshold": threshold,
        "chart_checked": accounts is not None,
        "summary": {
            "rows": len(rows),
            "merchants": len(groups),
            "settled_rows": settled,
            "needs_review": len(needs_review),
            "unresolved_rows": sum(1 for r in rows if not r["category"]),
        },
        "unknown_accounts": sorted(unknown_accounts),
        "merchants": needs_review,
    }


ADVICE = {
    "none": "no history — search the register, then fill it or add a rule",
    "thin": "few priors, all agreeing — accept if it looks right; it firms up "
            "on its own",
    "conflicting": "history disagrees — decide this row on its merits; a rule "
                   "would be wrong here",
    "settled": "history is consistent — check the flags below",
}


def render(data: dict) -> str:
    counts = data["summary"]
    out = [f"TRIAGE — {data['file']}", ""]
    out.append(f"{counts['rows']} row(s) across {counts['merchants']} "
               f"merchant(s): {counts['settled_rows']} settled, "
               f"{counts['needs_review']} merchant(s) need a look "
               f"({counts['unresolved_rows']} row(s) still have no account).")
    if not data["chart_checked"]:
        out.append("! `beans account list --names` did not run — proposed "
                   "account names were NOT validated against the ledger.")
    if data["unknown_accounts"]:
        out.append("! Not in the chart of accounts: "
                   + ", ".join(data["unknown_accounts"])
                   + " — fix the spelling or create the account first.")
    out.append("")
    if not data["merchants"]:
        out.append("Nothing needs review. Dry-run the import and show the "
                   "user the table.")
        return "\n".join(out)

    for group in data["merchants"]:
        head = (f"{group['example'][:38]:38}  {group['rows']:>2} row(s)  "
                f"{group['total']:>10,.2f}  conf {group['confidence']:.2f}")
        out.append(head)
        proposed = ", ".join(group["proposed"]) or "— none proposed —"
        out.append(f"    proposed : {proposed}")
        out.append(f"    basis    : {group['basis'] or 'no match'}")
        out.append(f"    evidence : {group['evidence']} — "
                   f"{ADVICE.get(group['evidence'], '')}")
        for flag in group["flags"]:
            out.append(f"    ! {flag}")
        if group["rule_candidate"]:
            out.append(f"    rule?    : recurs {group['rows']}x this "
                       "statement — a rule would settle it for good")
        out.append("")

    out.append("Propose these as a table (rules and cell edits separately), "
               "get approval, then apply. Nothing here has been changed.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prepared_csv")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"show merchants below this confidence "
                             f"(default: {DEFAULT_THRESHOLD}). A display "
                             f"cutoff only — beans has no auto-accept "
                             f"threshold and neither does this.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.prepared_csv).expanduser()
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    data = triage(path, args.threshold)
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
