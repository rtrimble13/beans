# 007 — Duplicated foreign-amount sign logic in CLI helpers

- **Lens:** Refactoring opportunity
- **Priority:** P3 (Impact: Low · Effort: Low)
- **Severity:** — (not a defect)
- **Confidence:** High

## Problem

The idiom "parse the foreign amount as a magnitude, then re-sign it to track the
base leg" is copy-pasted in two places:

```python
# beans/cli.py:266 (_parse_postings)
foreign = abs(parse_amount(spec[2], currency_decimals(account.currency)))
foreign = foreign if amount >= 0 else -foreign

# beans/cli.py:331 (_simple_transaction)
foreign = abs(parse_amount(foreign_text, currency_decimals(account.currency)))
posting.foreign_amount = foreign if posting.amount >= 0 else -foreign
```

Same rule ("the foreign amount always moves with the base amount"), two
implementations.

## Impact

Low — both copies are currently correct. But it is the kind of duplicated
money-sign logic where a future fix to one path silently misses the other, and
the rule is exactly the sort of thing that should be named once.

## Proposed fix

Extract a small helper, e.g.:

```python
def _signed_foreign(text: str, base_amount: int, code: str) -> int:
    mag = abs(parse_amount(text, currency_decimals(code)))
    return mag if base_amount >= 0 else -mag
```

Call it from both sites. Keep it near the other CLI helpers
(`beans/cli.py:45`+).

## Acceptance criteria

- Both call sites use the shared helper.
- Existing FX/transaction tests (`tests/test_fx.py`, `tests/test_cli.py`) pass
  unchanged.

## Effort

Low — pure extraction, no behavior change.
