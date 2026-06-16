# 006 — `report income --period all --compare` hard-errors

- **Lens:** Robustness of design / Enhancement
- **Priority:** P3 (Impact: Low · Effort: Low)
- **Severity:** Low
- **Confidence:** High

## Problem

`income_statement(..., compare=True)` calls `prior_period(start, end)`, which
raises when the period has no start date:

```python
# beans/utils.py:243
def prior_period(start, end):
    if start is None:
        raise BeansError("cannot compare against a period with no start date")
```

`--period all` (and `--from` omitted) resolves `start = None`
(`beans/utils.py:186`), so `beans report income --period all --compare` fails
with a hard error. The two flags are silently incompatible; nothing at parse
time signals it.

## Impact

Minor but papercut-y: a reasonable flag combination errors out mid-report
instead of doing the sensible thing. It is a handled `BeansError` (non-zero
exit, clean message), so no crash — purely UX.

## Proposed fix

Degrade gracefully rather than throw. In `income_statement`, when `compare` is
requested but `start is None`, skip the comparison and surface a one-line note
in the rendered output ("comparison unavailable for an unbounded period"),
leaving `--json` without a `compare` key. Alternatively, validate at the command
layer (`cmd_report_income`) and emit the note there. Prefer the former so the
JSON and text paths stay consistent.

## Acceptance criteria

- `report income --period all --compare` exits 0 and prints the statement plus a
  note, with no `compare` block.
- Bounded-period `--compare` is unchanged.
- A test covers the unbounded-period + compare combination.

## Effort

Low — a guard in `income_statement` plus a test.
