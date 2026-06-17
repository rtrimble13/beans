# Project review — beans

**Date:** 2026-06-16
**Reviewer:** senior-staff engineering health-check (project-review)
**Commit/branch:** `claude/keen-bell-vxmsnl`

## Verdict & summary

`beans` is a genuinely well-built project: a pure-stdlib, double-entry
personal-accounting CLI backed by a single SQLite file, with corporate-style
statements (income statement, balance sheet, direct-method cash flows),
budgeting, forecasting, investments (FIFO lots + mark-to-market), multi-currency
with FX revaluation, reconciliation, goals, period close, CSV import, and export.
The code is clean, consistently styled, well-commented at the "why" level, and
backed by 125 tests across 12 files plus a 3-version CI matrix. The core
invariant — postings sum to zero, balances tie — is enforced in one place and
respected throughout. This is healthy code, not a rescue job.

The findings below are therefore mostly sharpening, not firefighting. The one
item that rises to a real correctness concern is the **CSV import de-duplicator,
which silently drops legitimately distinct transactions** that happen to share a
date, account, and amount (two $4.50 coffees on the same day), and whose
`--dry-run` preview disagrees with the real run. For an accounting tool, silently
omitting money from the books is the highest-impact defect on the board even
though the de-dupe *behavior* is documented.

Counts: 7 actionable findings (1× P1, 4× P2, 2× P3). No P0 — there is no
data-corruption or crash-on-normal-use defect. New-feature ideas are quarantined
below and carry no backlog docs.

## How this review was scoped

**Read in full:** `beans/ledger.py` (persistence + all aggregates),
`beans/cli.py` (entire 1585-line command surface + arg tree),
`beans/utils.py`, `beans/models.py`, `beans/reports.py`, `beans/forecast.py`,
`beans/recurring.py`, `beans/importer.py`, `beans/render.py`, `beans/invest.py`,
`beans/fx.py`, `beans/analysis.py`, `beans/budget.py`, `beans/goals.py`,
`beans/export.py`, `beans/status.py`, `beans/reconcile.py`,
`beans/completions.py`. `pyproject.toml` and the CI workflow.

**Sampled:** the test suite — counted and indexed all 12 files (125 tests),
read `tests/test_importer.py` in full and grepped the rest for coverage of
forecast/analysis/budget/completions. Two suspected defects (F1, F2) were
**reproduced empirically** against a throwaway ledger before being written up.

**Skipped / shallow:** the prose vignettes under `docs/vignettes/`, the
`.claude/skills/` tooling (not product code), and the line-by-line internals of
the renderer's ANSI padding (sampled, looked correct). Multi-currency rounding
was read but not exhaustively fuzzed.

**Confidence:** high on the persistence, CLI, import, and reporting layers
(deep-read + repro); medium on the forecast trend math and FX rounding edges
(read but not numerically fuzzed).

## Findings (ranked by impact × effort, then severity)

Backlog delivered as GitHub issues (issue-mode); links point to
`rtrimble13/beans`.

| # | Finding | Lens | Priority | Severity | Confidence |
|---|---------|------|----------|----------|------------|
| [#7](https://github.com/rtrimble13/beans/issues/7) | CSV import silently drops distinct same-day/same-amount rows; `--dry-run` disagrees with the real run | Robustness / Bug | **P1** | High | High (reproduced) |
| [#8](https://github.com/rtrimble13/beans/issues/8) | `spend`/`earn`/`transfer` and `tx add --like` post to closed accounts that `tx add --post` rejects | Bug / Robustness | **P2** | Medium | High (reproduced) |
| [#9](https://github.com/rtrimble13/beans/issues/9) | `export csv` omits voided transactions and the void column; `export json` includes them — the two "whole ledger" exports disagree | Bug / Enhancement | **P2** | Medium | High |
| [#10](https://github.com/rtrimble13/beans/issues/10) | Six `cmd_*_list` handlers hand-roll JSON instead of the `jsonify` path, duplicating serialization and risking drift | Refactoring | **P2** | — | High |
| [#11](https://github.com/rtrimble13/beans/issues/11) | Forecast `trend` (least-squares) and analysis ratios have no numeric assertions — only smoke tests | Refactoring / Testability | **P2** | — | Medium |
| [#12](https://github.com/rtrimble13/beans/issues/12) | `report income --period all --compare` hard-errors instead of degrading gracefully | Robustness / Enhancement | **P3** | Low | High |
| [#13](https://github.com/rtrimble13/beans/issues/13) | Foreign-amount sign logic is duplicated in two CLI helpers | Refactoring | **P3** | — | High |

### P1

**[#7] CSV import silently drops legitimately distinct transactions.**
`_is_duplicate` (`beans/importer.py:24`) matches on `(date, account_id, amount)`
only, and is queried per-row against the live DB. Two genuine identical rows in
one file — `2026-03-01,Coffee,-4.50` twice — import as **one** transaction: row 1
is written, row 2 then matches it and is skipped. Worse, `--dry-run` writes
nothing, so both rows pass the check and the preview reports **2 imported** while
the real run imports **1**. Reproduced: `DRY imported=2 skipped=0` vs
`REAL imported=1 skipped=1`, one transaction in the ledger. For an accounting
tool this is silent financial omission. See the issue for the count-based fix.

### P2

**[#8] Closed-account guard is enforced inconsistently.** `tx add --post`
rejects postings to closed accounts (`beans/cli.py:246`), but
`_simple_transaction` (`spend`/`earn`/`transfer`, `beans/cli.py:305`) and the
`tx add --like` clone path (`beans/cli.py:281`) never check `.closed`.
Reproduced: a transaction posts cleanly to a closed account through the
shortcut path. The guard belongs in `Ledger.add_transaction`, not the CLI.

**[#9] The two export formats disagree on what "the whole ledger" is.**
`export_json` reads `transactions(include_void=True)` and emits a `void` field
(`beans/export.py:82`); `export_csv` reads `transactions()` — void excluded —
and has no void column (`beans/export.py:151`). A user exporting "everything" to
CSV silently loses their voided history.

**[#10] List commands bypass the `jsonify` pipeline.** `cmd_account_list`,
`cmd_budget_list`, `cmd_rule_list`, `cmd_price_list`, `cmd_currency_list`,
`cmd_currency_rates` each hand-build their JSON (`beans/cli.py:159`, `554`,
`756`, `870`, `901`, `938`), while every report command routes through
`_emit`/`reports.jsonify`. The hand-rolled `currency list` block already carries
a special-case comment about JPY decimals — exactly the drift this duplication
invites.

**[#11] The riskiest math is the least asserted.** `forecast._project`'s
least-squares `trend` branch (`beans/forecast.py:27`) and `analysis.analyze`'s
ratios (`beans/analysis.py:42`) are exercised only by smoke tests
(`test_forecast_runs`, `test_analyze_runs`) that assert the command runs, not
that the numbers are right. A sign error in the slope or a ratio would ship
green.

### P3

**[#12] `--compare` against an unbounded period throws.** `report income
--period all --compare` calls `prior_period(None, end)`, which raises
`BeansError` (`beans/utils.py:246`). It's a handled error, but the flag combo is
silently incompatible; prefer degrading (skip the comparison with a note).

**[#13] Duplicated foreign-sign logic.** The "abs then re-sign to match the base
leg" idiom is copy-pasted in `_parse_postings` (`beans/cli.py:266`) and
`_simple_transaction` (`beans/cli.py:331`). Extract a one-line helper.

## New feature ideas (quarantined — no backlog docs)

Evidence-backed only; capped and low-priority.

- **`import --commit-from-dry-run` / batch-aware de-dupe** (P2): motivated
  directly by finding 001 — once intra-batch counting exists, surfacing "N
  apparent duplicates, keep all?" would make import trustworthy.
- **Account merge/rename-into** (P3): `update_account` already supports rename
  but there is no way to fold one account's postings into another; the fuzzy
  matcher and `find_account` ambiguity errors suggest users will create
  near-duplicate accounts.
- **Scheduled-transaction "catch-up" summary** (P3): `recur run` and the
  due-reminder plumbing (`due_names`, `_due_reminder`) already exist; a
  `recur status --upcoming 30d` projection would reuse `pending_occurrences`.

## What's done well (preserve these)

- **One source of truth for the sign convention.** `AccountType.natural_sign`
  (`beans/models.py:17`) plus `Ledger.type_totals` (`beans/ledger.py:672`) keep
  debit/credit polarity in exactly one place; every report reuses it instead of
  re-deriving signs. This is why the statements stay consistent.
- **Atomic recurring posting.** `post_recurring_instance` bumps the occurrence
  counter inside the same `with self.db` block as the insert
  (`beans/ledger.py:910`), so an interrupted `recur run` can never repost a
  committed instance. The `MAX_RUN_PER_RULE` runaway guard
  (`beans/recurring.py:24`) is a thoughtful belt-and-suspenders.
- **Batched posting loads.** `_build_transactions` chunks the postings query
  500 ids at a time (`beans/ledger.py:574`) instead of N+1 per transaction, and
  `net_worth_trend` accumulates from a single grouped scan
  (`beans/reports.py:357`). Performance was considered, not bolted on.
- **Real online backup.** `export.backup` uses SQLite's backup API with
  overwrite/self-destination guards (`beans/export.py:171`) — correct under
  concurrent writes, not a naive file copy.
- **Generated shell completions.** `completions.generate` reads the live
  argparse tree (`beans/cli.py:987`) so the command list cannot drift from the
  implementation.
- **Honest invariant reporting.** Statements print explicit warnings when the
  balance sheet doesn't balance or the trial balance doesn't tie
  (`beans/reports.py:204`, `321`) rather than hiding corruption.
