"""CSV import: turn bank-style exports into balanced transactions.

Each row needs a date, a description, and a signed amount (positive =
money into the target account). The counter-account is resolved in
order: the row's category column, then saved import rules matched
against the description (`beans rule add "WHOLE FOODS" Groceries`),
then the --category fallback.

Rows that match an existing transaction (same date, account, and
amount) are skipped by default, so re-importing overlapping bank
exports is safe.
"""

from __future__ import annotations

import csv
from pathlib import Path

from beans.ledger import Ledger
from beans.models import Account, Posting
from beans.utils import BeansError, parse_amount, parse_date


def _is_duplicate(led: Ledger, when, account: Account, amount: int) -> bool:
    row = led.db.execute(
        "SELECT 1 FROM postings p JOIN transactions t ON t.id = p.txn_id "
        "WHERE t.void = 0 AND t.date = ? AND p.account_id = ? "
        "AND p.amount = ? LIMIT 1",
        (when.isoformat(), account.id, amount),
    ).fetchone()
    return row is not None


def import_csv(
    led: Ledger,
    path: str,
    account: Account,
    default_category: Account | None = None,
    date_col: str = "date",
    desc_col: str = "description",
    amount_col: str = "amount",
    category_col: str = "category",
    dry_run: bool = False,
    dedupe: bool = True,
) -> dict:
    file = Path(path).expanduser()
    if not file.exists():
        raise BeansError(f"file not found: {path}")
    imported, skipped = [], []
    rules = led.import_rules()  # fetched once, matched per row
    with file.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise BeansError(f"{path} is empty or has no header row")
        fields = {f.strip().lower(): f for f in reader.fieldnames}
        for col, required in ((date_col, True), (amount_col, True),
                              (desc_col, False)):
            if required and col.lower() not in fields:
                raise BeansError(
                    f"column {col!r} not found in {path} "
                    f"(columns: {', '.join(reader.fieldnames)})"
                )
        for lineno, row in enumerate(reader, start=2):
            raw_date = (row.get(fields[date_col.lower()]) or "").strip()
            raw_amount = (row.get(fields.get(amount_col.lower(), "")) or "").strip()
            if not raw_date and not raw_amount:
                continue  # blank line
            try:
                when = parse_date(raw_date)
                amount = parse_amount(raw_amount, led.decimals)
            except BeansError as exc:
                raise BeansError(f"{path}:{lineno}: {exc}")
            desc = (row.get(fields.get(desc_col.lower(), ""), "") or "").strip()
            raw_cat = (row.get(fields.get(category_col.lower(), ""), "") or "").strip()
            if amount == 0:
                continue
            counter = None
            if raw_cat:
                try:
                    counter = led.find_account(raw_cat)
                except BeansError as exc:
                    raise BeansError(f"{path}:{lineno}: {exc}")
            if counter is None and desc:
                haystack = desc.lower()
                for _rule_id, pattern, rule_account in rules:
                    if pattern.lower() in haystack:
                        counter = rule_account
                        break
            if counter is None:
                counter = default_category
            if counter is None:
                raise BeansError(
                    f"{path}:{lineno}: no category column, no import rule "
                    f"matches {desc!r}, and no --category fallback given"
                )
            entry = {
                "id": None,
                "date": when.isoformat(),
                "description": desc,
                "amount": amount,
                "counter": counter.name,
            }
            if dedupe and _is_duplicate(led, when, account, amount):
                skipped.append(entry)
                continue
            if not dry_run:
                txn = led.add_transaction(when, desc, [
                    Posting(account_id=account.id, amount=amount),
                    Posting(account_id=counter.id, amount=-amount),
                ])
                entry["id"] = txn.id
            imported.append(entry)
    return {"imported": imported, "skipped": skipped}
