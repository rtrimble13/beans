# Command reference

Only the commands this workflow uses. `beans <command> -h` is authoritative;
`docs/MANUAL.md` in the beans repo has the full prose.

Global: `beans -f PATH ...` or `export BEANS_LEDGER=...` selects the ledger
(default `~/.beans/ledger.db`). `--json` is available on everything below
except `rule add`/`rule remove`.

## `beans categorize` — suggest accounts (read-only)

```
beans categorize CSVFILE --account ACCOUNT [-o PATH] [--since DATE]
                 [--invert] [--force] [--date-col NAME] [--desc-col NAME]
                 [--amount-col NAME] [--category-col NAME] [--json]
```

| Flag | Notes |
|---|---|
| `-a, --account` (required) | The account the export belongs to. |
| `-o, --output PATH` | Write suggestions as an editable CSV ready for `import`. Without it: preview only, nothing written. |
| `--since DATE` | Only learn from transactions on or after DATE. Use after reorganizing the chart of accounts so retired accounts stop being proposed. |
| `--invert` | Flip every amount. For card exports reporting purchases as positive. |
| `--force` | Overwrite an existing `-o` file. **Avoid** — the file is meant to be edited between writing and importing. |

Never writes to the ledger. Output columns: `date,description,amount,category,
confidence,basis`. Re-runnable over its own output — keeps filled categories,
fills only blanks.

JSON shape: `summary` (`rows`, `column`, `rule`, `history`, `unresolved`),
`history_size`, and `rows[]` each with `line`, `date`, `description`, `amount`,
`category`, `confidence`, `source`, `basis`.

## `beans import` — write to the ledger

```
beans import CSVFILE --account ACCOUNT [--category ACCOUNT]
             [--date-col NAME] [--desc-col NAME] [--amount-col NAME]
             [--category-col NAME] [--dry-run] [--no-dedupe] [--learn] [--json]
```

| Flag | Notes |
|---|---|
| `-a, --account` (required) | Target account. |
| `--category ACCOUNT` | Fallback counter-account for rows nothing else resolves. A blanket fallback hides uncategorized rows in a bucket — prefer resolving them in Phase 3. |
| `--dry-run` | Parse and report, write nothing. **Always run this first.** |
| `--no-dedupe` | Prohibited unless the user says a duplicate is intended. |
| `--learn` | **Prohibited by this skill.** Writes history-inferred accounts nobody reviewed. |

Counter-account resolution order: row's category column → saved rule →
(`--learn` only) history → `--category`. Unrecognized columns are ignored, so
`confidence` and `basis` ride along harmlessly.

Dedupe is count-aware on `(date, account, amount)`: re-importing a file is a
no-op, but two distinct same-day same-amount rows both import.

JSON shape: `summary` (`rows`, `imported`, `skipped`), `dry_run`, plus
`imported[]` and `skipped[]` with `id` (null on a dry run), `date`,
`description`, `amount`, `counter`.

## `beans rule` — standing categorization intent

```
beans rule add PATTERN ACCOUNT      # case-insensitive substring on the description
beans rule list [--json]
beans rule remove PATTERN
```

Longest matching pattern wins, regardless of insertion order — so
`"AMAZON WEB SERVICES" -> Cloud` correctly beats `"AMAZON" -> Shopping`.

Rules always beat inference. Reserve them for what history cannot know: a
brand-new merchant whose account is already known, or a deliberate change of
mind going forward.

## `beans reconcile` — prove the ledger matches the bank

```
beans reconcile ACCOUNT --balance AMOUNT [--date DATE]
beans reconcile ACCOUNT --statement CSV [--window DAYS] [--invert]
                [--unmatched-out PATH] [--force] [--json]
```

Read-only: nothing is cleared or posted.

- `--balance` compares the account's computed balance to the statement's ending
  balance as of a date.
- `--statement` matches line by line. **Amounts must be equal** to pair — an
  amount difference is a finding, never absorbed as fuzz. Dates are given
  ±`--window` days (default 5), and descriptions are matched fuzzily.
- Result buckets: `matched`, `date_drift`, `amount_mismatch`, `bank_only`
  (in the bank, not in the ledger), `outstanding` (in the ledger, not in
  the bank) and `cleared_missing`. Every non-matched row is a real finding;
  walk each one. Equal `bank_only` and `outstanding` totals usually mean
  one transaction was recorded with the wrong date or description.
- `--unmatched-out PATH` writes the bank-only rows as another prepared CSV,
  categorized by the same classifier.

## `beans clear` — mark postings cleared

```
beans clear ACCOUNT [ID ...] [--through DATE] [--undo]
```

## Supporting commands

```
beans account list --names          # bare account names, for validation
beans account add NAME --type TYPE  # e.g. --type expense; needs explicit approval
beans search "TEXT" [--limit N] [--json]
beans register ACCOUNT [--period P] [--json]
beans status
beans balances [--json]
beans config list
beans period status
beans period close YYYY-MM-DD       # only when the user asks
```
