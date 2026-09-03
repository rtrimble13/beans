"""CSV import: turn bank-style exports into balanced transactions.

Each row needs a date, a description, and a signed amount (positive =
money into the target account). The counter-account is resolved in
order: the row's category column, then saved import rules matched
against the description (`beans rule add "WHOLE FOODS" Groceries`),
then — only when `learn` is set — what the ledger's own history says
about that merchant, and finally the --category fallback.

History inference is opt-in here on purpose. `import` writes to the
ledger, and an inferred account that nobody reviewed is exactly the
mistake you find out about a month later. The reviewable path is
`beans categorize`, which applies the same classifier and hands you a
file to check first.

Re-importing overlapping bank exports is safe: deduplication is
count-aware. For each (date, account, amount) key it skips only as
many rows as the ledger already holds for that key, so two genuinely
distinct rows that share a date and amount (e.g. two $4.50 coffees on
the same day) both import, while re-importing the same file is a
no-op. The dry run applies the identical counting logic, so the
preview always matches the real run.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from beans.ledger import Ledger
from beans.matching import resolve_columns
from beans.models import Account, Posting
from beans.render import Table, money
from beans.utils import BeansError, parse_amount, parse_date


def _existing_counts(led: Ledger, account: Account) -> Counter:
    """Count the non-void postings the ledger already holds for the target
    account, grouped by (date, amount). One query, not one per row."""
    rows = led.db.execute(
        "SELECT t.date, p.amount, COUNT(*) "
        "FROM postings p JOIN transactions t ON t.id = p.txn_id "
        "WHERE t.void = 0 AND p.account_id = ? "
        "GROUP BY t.date, p.amount",
        (account.id,),
    ).fetchall()
    return Counter({(when, amount): count for when, amount, count in rows})


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
    learn: bool = False,
) -> dict:
    file = Path(path).expanduser()
    if not file.exists():
        raise BeansError(f"file not found: {path}")
    imported, skipped = [], []
    rules = led.import_rules()  # fetched once, matched per row
    classifier = None
    if learn:
        from beans.classify import Classifier
        classifier = Classifier(led, account)
    # Count-aware dedupe: the ledger's existing per-key counts, plus a
    # running tally of keys seen so far in this file. A row is a duplicate
    # only once the running count catches up to what the ledger holds, so
    # distinct same-day/same-amount rows survive and re-imports stay no-ops.
    # Seeded and incremented identically in dry-run, so preview == real run.
    ledger_counts = _existing_counts(led, account) if dedupe else Counter()
    seen: Counter = Counter()
    with file.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = resolve_columns(reader.fieldnames, path,
                                 required=[date_col, amount_col])
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
                counter = led.match_import_rule(desc, rules)
            if counter is None and classifier is not None and desc:
                found = classifier.suggest(desc)
                if found.account:
                    counter = led.find_account(found.account)
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
            if dedupe:
                key = (when.isoformat(), amount)
                already = seen[key] < ledger_counts[key]
                seen[key] += 1
                if already:
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


# -- the report --------------------------------------------------------------


def import_report(account: Account, source: str, result: dict,
                  dry_run: bool = False) -> dict:
    """Shape one import run for `--json` and for the text renderer alike, so
    the two can never disagree about what happened."""
    imported, skipped = result["imported"], result["skipped"]
    return {
        "report": "import",
        "account": account.name,
        "source": source,
        "dry_run": dry_run,
        "summary": {
            "rows": len(imported) + len(skipped),
            "imported": len(imported),
            "skipped": len(skipped),
        },
        "imported": imported,
        "skipped": skipped,
    }


def render_import(data: dict, decimals: int, symbol: str) -> str:
    counts = data["summary"]
    verb = "Would import" if data["dry_run"] else "Imported"
    summary = (f"{verb} {counts['imported']} transaction(s) into "
               f"{data['account']}")
    if counts["skipped"]:
        summary += (f" ({counts['skipped']} duplicate(s) skipped; "
                    "pass --no-dedupe to keep them)")
    if not data["dry_run"]:
        return summary
    table = Table(headers=["Date", "Description", "Counter-account",
                           "Amount"], align="lllr")
    for row in data["imported"]:
        table.add(row["date"], row["description"][:40], row["counter"],
                  money(row["amount"], decimals))
    return summary + "\n" + table.render()
