# 001 — CSV import silently drops distinct same-day/same-amount rows

- **Lens:** Robustness of design / Hidden bug
- **Priority:** P1 (Impact: High · Effort: Low–Medium)
- **Severity:** High (silent financial omission)
- **Confidence:** High — reproduced against a throwaway ledger

## Problem

`_is_duplicate` de-duplicates import rows by `(date, account_id, amount)` only,
querying the live database once per row:

```python
# beans/importer.py:24
def _is_duplicate(led, when, account, amount) -> bool:
    row = led.db.execute(
        "SELECT 1 FROM postings p JOIN transactions t ON t.id = p.txn_id "
        "WHERE t.void = 0 AND t.date = ? AND p.account_id = ? "
        "AND p.amount = ? LIMIT 1",
        (when.isoformat(), account.id, amount),
    ).fetchone()
    return row is not None
```

Because rows are imported one at a time and each row is checked against the
*current* DB state (`beans/importer.py:99`), two **legitimately distinct**
transactions that share a date, account, and amount collapse into one: the first
is written, the second then matches it and is silently skipped. Two $4.50
coffees on the same day become one $4.50 coffee on the books.

A second, related defect: `--dry-run` writes nothing, so intra-file duplicates
are never detected during a preview. The preview therefore disagrees with the
real run.

## Evidence / reproduction

CSV with two identical genuine rows:

```
date,description,amount,category
2026-03-01,Coffee,-4.50,Groceries
2026-03-01,Coffee,-4.50,Groceries
```

```
DRY  imported=2 skipped=0
REAL imported=1 skipped=1
transactions in ledger: 1
```

The dry run promises two; the real run silently keeps one. The behavior is
documented ("same date, account, and amount" — `beans/cli.py:1310`,
`beans/importer.py` module docstring), but documentation does not make silent
money-loss safe, and the dry-run/real mismatch is unambiguously a bug.

## Impact

For an accounting tool the books are the product. A user re-categorising a real
duplicate-looking expense will under-record spending and their balance sheet
will quietly drift from reality, with no error and a misleading preview.

## Proposed fix

De-dupe by *count within the batch* against the ledger, not by mere existence:

1. Before the row loop, fetch existing posting counts grouped by
   `(date, account_id, amount)` for the file's date range (one query).
2. Maintain an in-memory `Counter` of `(date, account_id, amount)` seen so far
   in this import. A row is a duplicate only when the running count for its key
   has caught up to the count already in the ledger.
3. Apply the identical counting logic in `--dry-run` (seed the counter from the
   ledger but increment it as rows are previewed) so preview == real run.

Optionally include `description` in the key, or add an `--allow-duplicates`
note in the summary line ("N rows looked like duplicates and were skipped — pass
`--no-dedupe` to keep them"). The summary already reports skipped count; make it
actionable.

## Acceptance criteria

- Two identical genuine rows in one file import as two transactions by default
  (count-aware), while re-importing the same file remains a no-op.
- `--dry-run` and the real run report identical imported/skipped counts for the
  same input.
- New tests in `tests/test_importer.py` cover: (a) two identical rows in one
  file, (b) dry-run vs real parity, (c) the existing "skip rows already in the
  ledger" case still passes.

## Effort

Low–Medium — localized to `beans/importer.py` plus tests. No schema change.
