"""CSV import: turn bank-style exports into balanced transactions.

Each row needs a date, a description, and a signed amount (positive =
money into the target account). An optional category column names the
counter-account; rows without one fall back to --category."""

from __future__ import annotations

import csv
from pathlib import Path

from beans.ledger import Ledger
from beans.models import Account, Posting
from beans.utils import BeansError, parse_amount, parse_date


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
) -> list[dict]:
    file = Path(path).expanduser()
    if not file.exists():
        raise BeansError(f"file not found: {path}")
    results = []
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
            if raw_cat:
                try:
                    counter = led.find_account(raw_cat)
                except BeansError as exc:
                    raise BeansError(f"{path}:{lineno}: {exc}")
            elif default_category:
                counter = default_category
            else:
                raise BeansError(
                    f"{path}:{lineno}: no category given and no --category "
                    "fallback account specified"
                )
            if amount == 0:
                continue
            postings = [
                Posting(account_id=account.id, amount=amount),
                Posting(account_id=counter.id, amount=-amount),
            ]
            if not dry_run:
                txn = led.add_transaction(when, desc, postings)
                txn_id = txn.id
            else:
                txn_id = None
            results.append({
                "id": txn_id,
                "date": when.isoformat(),
                "description": desc,
                "amount": amount,
                "counter": counter.name,
            })
    return results
