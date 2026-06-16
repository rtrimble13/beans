# 002 — Closed-account guard is enforced inconsistently

- **Lens:** Hidden bug / Robustness of design
- **Priority:** P2 (Impact: Medium · Effort: Low)
- **Severity:** Medium
- **Confidence:** High — reproduced

## Problem

`tx add --post` rejects postings to closed accounts in the CLI layer:

```python
# beans/cli.py:246 (_parse_postings)
if account.closed:
    raise BeansError(f"account {account.name} is closed")
```

But this guard lives only in `_parse_postings`. Two other write paths skip it:

- **`spend` / `earn` / `transfer`** all flow through `_simple_transaction`
  (`beans/cli.py:305`), which resolves accounts with `find_account` (which
  includes closed accounts) and never checks `.closed`.
- **`tx add --like ID`** (`beans/cli.py:281`) clones a template's postings by
  `account_id` directly, bypassing `_parse_postings` entirely.

`Ledger.add_transaction` itself never checks for closed accounts, so the
invariant is only as strong as the one CLI helper that happens to enforce it.

## Evidence / reproduction

```python
led.initialize()
acct = led.find_account('Expenses:Entertainment')
led.close_account(acct)                      # zero balance, closes fine
deb = led.find_account('Entertainment')      # find_account returns it closed
led.add_transaction(date(2026,3,1), 'movie',
    [Posting(account_id=deb.id, amount=2000),
     Posting(account_id=cred.id, amount=-2000)])
# -> posts cleanly to the closed account; this is the exact path spend/earn/transfer use
```

## Impact

"Closed" stops meaning closed. Users reopen activity on accounts they
deliberately retired, the account list shows balances on accounts flagged
closed, and shortcuts behave differently from the canonical `tx add` for no
discoverable reason.

## Proposed fix

Move the guard down into the ledger so every write path inherits it. In
`Ledger.add_transaction` (after `_check_postings`), look up the involved
accounts and raise `BeansError` if any is closed. Then the CLI-layer check in
`_parse_postings` becomes redundant (keep it for an earlier/clearer message, or
remove it). Decide intentionally whether system-posted adjustments
(mark-to-market, FX revaluation) may ever target a closed account — currently
they resolve by name and would also be blocked, which is almost certainly
correct.

## Acceptance criteria

- `spend`/`earn`/`transfer`, `tx add --post`, and `tx add --like` all reject a
  closed account with the same error.
- A test asserts each shortcut path raises on a closed account.
- Existing tests still pass (no legitimate flow posts to a closed account).

## Effort

Low — one guard in `Ledger.add_transaction` plus tests.
