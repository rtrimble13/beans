#!/usr/bin/env python3
"""Cross-reference a prepared CSV against the ledger's recurring rules.

A recurring rule and a bank statement can describe the same real-world
payment. `beans recur run` posts rent from a template on its due date; the
statement reports the same rent on the day it actually cleared. Import dedupe
keys on `(date, amount)` exactly, so it catches that pair only when both agree
to the cent and to the day — which for rent due on the 1st and cleared on the
3rd, or a utility bill whose amount moves every month, they do not.

So the duplicate this script exists to find is the one dedupe cannot see:

    ledger  2026-10-01  rent      -1,800.00   (posted by `beans recur run`)
    csv     2026-10-03  RENT ACH  -1,800.00   (about to import — not a dup key)

It reads `beans recur list/show`, the already-posted instances
(`beans search recurring`) and the not-yet-posted ones
(`beans recur run --dry-run`), then pairs each against the prepared file.

    python3 recur_match.py work/prepared.csv --account Assets:Checking
    python3 recur_match.py work/prepared.csv -a Assets:Checking --json

Reads only. Runs no beans command that writes.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

# `beans reconcile --statement` defaults to the same window; a payment that
# clears more than a working week after its due date is unusual enough that
# pairing it automatically would be a guess.
DEFAULT_WINDOW = 5

# How far a rule's template amount may sit from the statement's amount and
# still be the same payment. Variable bills (utilities, usage-based) are the
# whole reason this is not zero: the rule carries last year's estimate.
DEFAULT_TOLERANCE = Decimal("0.10")   # 10% ...
TOLERANCE_FLOOR = Decimal("5.00")     # ... or $5, whichever is more generous

_MONEY = re.compile(r"[,\s$€£¥]")


class BeansUnavailable(RuntimeError):
    pass


# -- talking to beans --------------------------------------------------------


def run_beans(argv: list[str], ledger: str | None,
              beans: str = "beans") -> str:
    cmd = [beans] + (["-f", ledger] if ledger else []) + argv
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BeansUnavailable(f"could not run {' '.join(cmd)}: {exc}")
    if done.returncode != 0:
        raise BeansUnavailable(
            f"{' '.join(cmd)} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def beans_json(argv: list[str], ledger: str | None, beans: str = "beans"):
    raw = run_beans(argv + ["--json"], ledger, beans)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BeansUnavailable(f"beans {' '.join(argv)} did not return JSON: {exc}")


def money(text) -> Decimal:
    try:
        return Decimal(_MONEY.sub("", str(text or "0")) or "0")
    except InvalidOperation:
        return Decimal("0")


def as_date(text: str) -> date | None:
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def same_account(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


# -- the rules ---------------------------------------------------------------


def rule_postings(name: str, ledger: str | None, beans: str) -> list[tuple[str, Decimal]]:
    """Parse `beans recur show`'s posting block.

    `recur show` has no --json, and it is the only command that reports which
    accounts a rule touches. The block is `    ACCOUNT   AMOUNT` per line, so
    split from the right: account names may contain spaces, amounts may not.
    """
    out = run_beans(["recur", "show", name], ledger, beans)
    postings, in_block = [], False
    for line in out.splitlines():
        if line.strip() == "postings:":
            in_block = True
            continue
        if not in_block:
            continue
        if not line.startswith("    ") or not line.strip():
            break
        account, _, amount = line.strip().rpartition(" ")
        if account.strip():
            postings.append((account.strip(), money(amount)))
    return postings


def rules_for_account(account: str, ledger: str | None, beans: str) -> dict[str, dict]:
    """Active-or-not rules with a leg on the target account, keyed by name.

    `leg` is the amount as it hits *that* account — the sign the statement
    will show. A rent rule is +1800 to Expenses and -1800 to Checking; the
    checking export reports -1800.
    """
    listing = beans_json(["recur", "list"], ledger, beans)
    found = {}
    for row in listing.get("rules", []):
        postings = rule_postings(row["name"], ledger, beans)
        leg = next((amt for acct, amt in postings if same_account(acct, account)),
                   None)
        if leg is None:
            continue
        found[row["name"]] = {
            "name": row["name"],
            "frequency": row["frequency"],
            "status": row["status"],
            "next_due": row.get("next_due"),
            "end": row.get("end"),
            "posted_count": row.get("posted_count"),
            "leg": leg,
            "postings": [{"account": a, "amount": str(m)} for a, m in postings],
            "counter": next((a for a, _ in postings if not same_account(a, account)),
                            None),
        }
    return found


def posted_instances(account: str, span: tuple[date, date], window: int,
                     ledger: str | None, beans: str) -> list[dict]:
    """Instances `beans recur run` has already written near the statement span.

    Tagged `recurring` by post_recurring_instance. `beans search` is a LIKE
    across description/payee/tags, so re-check the tag rather than trusting
    the hit: a transaction *described* "recurring donation" is not one.
    """
    start, end = span
    lo, hi = start - timedelta(days=window), end + timedelta(days=window)
    rows = []
    for txn in beans_json(["search", "recurring"], ledger, beans):
        if txn.get("void") or "recurring" not in (txn.get("tags") or []):
            continue
        when = as_date(txn.get("date", ""))
        if when is None or not (lo <= when <= hi):
            continue
        leg = next((money(p["amount"]) for p in txn.get("postings", [])
                    if same_account(p["account"], account)), None)
        if leg is None:
            continue
        rows.append({
            "state": "posted",
            "txn_id": txn.get("id"),
            "date": when,
            "description": txn.get("description", ""),
            "amount": leg,
        })
    return rows


def pending_instances(rules: dict[str, dict], span: tuple[date, date],
                      window: int, ledger: str | None, beans: str) -> list[dict]:
    """Instances that are due in the span but have NOT been posted yet.

    A dry run, so nothing is written. Reports the expense-side total rather
    than the account leg, so take the amount from the rule's own template.
    """
    start, end = span
    lo = start - timedelta(days=window)
    hi = end + timedelta(days=window)
    data = beans_json(["recur", "run", "--to", hi.isoformat(), "--dry-run"],
                      ledger, beans)
    rows = []
    for item in data.get("posted", []):
        rule = rules.get(item["rule"])
        if rule is None:
            continue
        when = as_date(item.get("date", ""))
        if when is None or not (lo <= when <= hi):
            continue
        rows.append({
            "state": "pending",
            "txn_id": None,
            "rule": rule["name"],
            "date": when,
            "description": item.get("description", ""),
            "amount": rule["leg"],
        })
    return rows


def attribute(instance: dict, rules: dict[str, dict]) -> str | None:
    """Which rule a posted instance came from.

    post_recurring_instance uses the rule's description, defaulting to its
    name, so the description is the only link back. Fall back to a unique
    amount match; report nothing rather than guess between two candidates.
    """
    if instance.get("rule"):
        return instance["rule"]
    desc = (instance["description"] or "").strip().lower()
    for name in rules:
        if desc == name.strip().lower():
            return name
    by_amount = [n for n, r in rules.items() if r["leg"] == instance["amount"]]
    return by_amount[0] if len(by_amount) == 1 else None


# -- the prepared file -------------------------------------------------------


def read_prepared(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
        for required in ("date", "amount"):
            if required not in fields:
                raise SystemExit(
                    f"{path} does not look like a prepared CSV: no "
                    f"{required!r} column (columns: "
                    f"{', '.join(reader.fieldnames or [])})")
        rows = []
        for lineno, raw in enumerate(reader, start=2):
            def get(name):
                return (raw.get(fields.get(name, ""), "") or "").strip()
            when = as_date(get("date"))
            if when is None:
                continue
            rows.append({
                "line": lineno,
                "date": when,
                "description": get("description"),
                "amount": money(get("amount")),
                "category": get("category"),
            })
    return rows


def tolerance_for(amount: Decimal, ratio: Decimal) -> Decimal:
    return max(abs(amount) * ratio, TOLERANCE_FLOOR)


def pair(instance: dict, rows: list[dict], taken: set[int], window: int,
         ratio: Decimal) -> dict | None:
    """Best statement row for one instance: exact amount first, then nearest
    date. Amount equality is the strong signal; the date only breaks ties."""
    limit = tolerance_for(instance["amount"], ratio)
    best = None
    for row in rows:
        if row["line"] in taken:
            continue
        drift = abs((row["date"] - instance["date"]).days)
        if drift > window:
            continue
        delta = abs(row["amount"] - instance["amount"])
        if delta > limit:
            continue
        rank = (delta != 0, drift, delta)
        if best is None or rank < best[0]:
            best = (rank, row, drift, delta)
    if best is None:
        return None
    _, row, drift, delta = best
    return {"row": row, "date_drift": drift, "amount_delta": delta}


# -- verdicts ----------------------------------------------------------------

VERDICTS = {
    "dedupe_skips": (
        "already in the ledger at the same date and amount — `import` will "
        "skip it as a duplicate. Expected; just say it happened."),
    "duplicate_risk": (
        "already in the ledger, but NOT at the same (date, amount) — dedupe "
        "will not catch it and importing posts it TWICE. Resolve before "
        "importing."),
    "rule_behind": (
        "the statement carries this payment but the rule has not posted it "
        "yet. Import the statement's row (it has the real date and amount); "
        "the rule is then behind and `beans recur run` would post a "
        "duplicate later."),
    "posted_not_on_statement": (
        "posted from the rule but nothing on the statement matches it. The "
        "bank has not cleared it, or the rule fired for something that did "
        "not happen. Phase 6 will report it as `outstanding`."),
    "pending_not_on_statement": (
        "due in this period but neither posted nor on the statement. Nothing "
        "to do for this import — check it is not simply overdue."),
}


def analyze(path: Path, account: str, window: int, ratio: Decimal,
            ledger: str | None, beans: str) -> dict:
    rows = read_prepared(path)
    if not rows:
        raise SystemExit(f"{path}: no dated rows to check")
    span = (min(r["date"] for r in rows), max(r["date"] for r in rows))

    rules = rules_for_account(account, ledger, beans)
    instances = []
    if rules:
        instances = (posted_instances(account, span, window, ledger, beans)
                     + pending_instances(rules, span, window, ledger, beans))
        instances.sort(key=lambda i: (i["date"], i["description"]))

    findings, taken = [], set()
    for instance in instances:
        match = pair(instance, rows, taken, window, ratio)
        if match:
            taken.add(match["row"]["line"])
        if instance["state"] == "posted":
            if match is None:
                verdict = "posted_not_on_statement"
            elif match["date_drift"] == 0 and match["amount_delta"] == 0:
                verdict = "dedupe_skips"
            else:
                verdict = "duplicate_risk"
        else:
            verdict = "rule_behind" if match else "pending_not_on_statement"
        findings.append({
            "verdict": verdict,
            "rule": attribute(instance, rules),
            "state": instance["state"],
            "txn_id": instance["txn_id"],
            "instance_date": instance["date"].isoformat(),
            "instance_description": instance["description"],
            "instance_amount": str(instance["amount"]),
            "statement_row": (
                None if match is None else {
                    "line": match["row"]["line"],
                    "date": match["row"]["date"].isoformat(),
                    "description": match["row"]["description"],
                    "amount": str(match["row"]["amount"]),
                    "category": match["row"]["category"],
                    "date_drift": match["date_drift"],
                    "amount_delta": str(match["amount_delta"]),
                }),
        })

    order = list(VERDICTS)
    findings.sort(key=lambda f: order.index(f["verdict"]))
    counts = {name: sum(1 for f in findings if f["verdict"] == name)
              for name in VERDICTS}
    return {
        "file": str(path),
        "account": account,
        "window_days": window,
        "statement_span": [span[0].isoformat(), span[1].isoformat()],
        "rules": [
            {k: (str(v) if isinstance(v, Decimal) else v)
             for k, v in rule.items()}
            for rule in rules.values()
        ],
        "summary": {
            "statement_rows": len(rows),
            "rules_on_account": len(rules),
            "instances_checked": len(instances),
            "needs_action": counts["duplicate_risk"] + counts["rule_behind"],
            **counts,
        },
        "findings": findings,
    }


def render(data: dict) -> str:
    counts = data["summary"]
    out = [f"RECURRING CROSS-CHECK — {data['file']}",
           f"account {data['account']}, statement "
           f"{data['statement_span'][0]} .. {data['statement_span'][1]}, "
           f"±{data['window_days']} day window", ""]

    if not data["rules"]:
        out.append("No recurring rule posts to this account. Nothing to "
                   "reconcile against — carry on with the import.")
        return "\n".join(out)

    out.append(f"{counts['rules_on_account']} rule(s) touch this account; "
               f"{counts['instances_checked']} instance(s) fall in the "
               f"window.")
    for rule in data["rules"]:
        out.append(f"    {rule['name']:<20} {rule['frequency']:<10} "
                   f"{rule['status']:<10} leg {rule['leg']:>12} "
                   f"-> {rule['counter'] or '?'}")
    out.append("")

    if counts["needs_action"]:
        out.append(f"** {counts['needs_action']} finding(s) need a decision "
                   f"BEFORE `beans import` runs. **")
    else:
        out.append("No duplication risk found. Dedupe covers what overlaps.")
    out.append("")

    shown = None
    for finding in data["findings"]:
        if finding["verdict"] != shown:
            shown = finding["verdict"]
            out.append(f"[{shown}] {VERDICTS[shown]}")
            out.append("")
        rule = finding["rule"] or "(unattributed)"
        where = (f"txn #{finding['txn_id']}" if finding["txn_id"]
                 else "not yet posted")
        out.append(f"  {rule}  —  ledger {finding['instance_date']} "
                   f"{finding['instance_amount']:>12}  ({where})")
        row = finding["statement_row"]
        if row:
            out.append(f"      statement line {row['line']}: {row['date']} "
                       f"{row['description'][:34]:34} {row['amount']:>12}")
            drift = []
            if row["date_drift"]:
                drift.append(f"{row['date_drift']} day(s) apart")
            if money(row["amount_delta"]):
                drift.append(f"{row['amount_delta']} apart in amount")
            if drift:
                why = ("a later `beans recur run` posts the rule's own copy"
                       if finding["state"] == "pending"
                       else "the dedupe key does not match, so import posts "
                            "a second copy")
                out.append(f"      -> {', '.join(drift)} — {why}")
        out.append("")

    out.append("Present every finding above for approval before importing. "
               "Nothing here has been changed.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prepared_csv")
    parser.add_argument("--account", "-a", required=True,
                        help="the full account name the statement belongs to, "
                             "as resolved in Phase 0")
    parser.add_argument("--window", "-w", type=int, default=DEFAULT_WINDOW,
                        help=f"days a rule's due date may differ from the "
                             f"statement's (default: {DEFAULT_WINDOW})")
    parser.add_argument("--tolerance", type=Decimal, default=DEFAULT_TOLERANCE,
                        help=f"fraction a variable bill's amount may differ by, "
                             f"or {TOLERANCE_FLOOR} if that is larger "
                             f"(default: {DEFAULT_TOLERANCE})")
    parser.add_argument("--ledger", "-f", help="ledger path (default: the one "
                                               "beans would open)")
    parser.add_argument("--beans", default="beans", help="beans executable")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.prepared_csv).expanduser()
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    try:
        data = analyze(path, args.account, args.window, args.tolerance,
                       args.ledger, args.beans)
    except BeansUnavailable as exc:
        print(f"cannot introspect recurring rules: {exc}\n"
              "Resolve this before importing — an unchecked recurring rule "
              "is how a payment gets booked twice.", file=sys.stderr)
        return 2
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
