# 003 — CSV and JSON exports disagree on voided transactions

- **Lens:** Hidden bug / Enhancement to existing feature
- **Priority:** P2 (Impact: Medium · Effort: Low)
- **Severity:** Medium
- **Confidence:** High — read both code paths

## Problem

The two export formats, both advertised as getting "your data out, whole",
disagree on what "whole" means:

```python
# beans/export.py:82  (export_json) — includes void, emits a "void" field
for t in led.transactions(include_void=True)

# beans/export.py:151 (export_csv) — default include_void=False, no void column
for txn in led.transactions():
```

`export_json` carries every transaction with an explicit `void` boolean.
`export_csv` silently drops voided transactions and has no `void` column at all
(header at `beans/export.py:148`).

## Impact

A user who exports to CSV for a spreadsheet or for archival believes they have a
complete record, but their voided history is gone with no warning. The two
formats are not round-trippable against each other, and "void" — which `beans`
treats as the audit-preserving alternative to deletion — is the one thing the
flat export erases.

## Proposed fix

Make CSV consistent with JSON:

1. `export_csv` should iterate `led.transactions(include_void=True)`.
2. Add a `void` column to the header and each row (`int(txn.void)`, matching the
   `cleared` column convention already used at `beans/export.py:166`).

The module docstring (`beans/export.py:1`) already promises the export is
"whole and consistent" — this brings the code in line with the contract.

## Acceptance criteria

- `export csv` includes voided transactions with a `void` column.
- `tests/test_export.py` asserts a voided transaction appears in both the JSON
  and CSV exports with the void flag set.

## Effort

Low — two lines plus a column, plus a test.
