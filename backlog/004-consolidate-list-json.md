# 004 — List commands hand-roll JSON instead of using the `jsonify` pipeline

- **Lens:** Refactoring opportunity
- **Priority:** P2 (Impact: Medium · Effort: Medium)
- **Severity:** — (not a defect)
- **Confidence:** High

## Problem

Report commands route output through a single, well-factored path:
`_emit` → `reports.jsonify` (`beans/cli.py:74`, `beans/reports.py:30`), which
converts a report dict to JSON with consistent money-as-decimal-string handling
and known-count exceptions (`NON_MONEY_KEYS`).

The `*_list`-style commands ignore this and build JSON by hand, each
re-implementing money conversion inline:

- `cmd_account_list` — `beans/cli.py:159`
- `cmd_budget_list` — `beans/cli.py:554`
- `cmd_rule_list` — `beans/cli.py:756`
- `cmd_price_list` — `beans/cli.py:870`
- `cmd_currency_list` — `beans/cli.py:901`
- `cmd_currency_rates` — `beans/cli.py:938`

`cmd_currency_list` even carries a hand-written comment explaining a JPY-decimals
special case (`beans/cli.py:903`) — precisely the kind of subtle, per-call money
handling that a single serializer exists to get right once.

## Impact

Six divergent serialization sites mean six places to update when the JSON shape
or money-formatting rules change, and six chances for the human-readable and
`--json` outputs to drift. It also inflates `cli.py` (already 1585 lines, the
churniest file in the repo) with logic that belongs in the report/jsonify layer.

## Proposed fix

Give each list command a small data-builder that returns a plain dict (the way
`reports.balances_report` etc. already do), then render and serialize through the
existing `_emit`/`jsonify` path. Where a value is a count rather than money
(e.g. rule ids), extend `NON_MONEY_KEYS` or pass it through the existing
mechanism. The foreign-currency / JPY-decimals case may justify a small,
documented extension to `jsonify` (a per-field currency hint) rather than a
bespoke serializer — but it should live in one place.

This can be done incrementally, one command per commit, with the JSON output
asserted byte-for-byte unchanged.

## Acceptance criteria

- Each converted command produces identical `--json` output to today (golden
  test before/after).
- No `json.dumps` of a hand-built dict remains in the `cmd_*_list` handlers.
- `cli.py` shrinks; serialization rules live in the report/jsonify layer.

## Effort

Medium — mechanical but spread across six commands; guard with output-equality
tests so behavior cannot regress.
