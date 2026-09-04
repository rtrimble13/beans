# Command reference

Only the commands this workflow uses. `beans <command> -h` is authoritative;
`docs/MANUAL.md` in the beans repo has the full prose.

Global: `beans -f PATH ...` or `export BEANS_LEDGER=...` selects the ledger
(default `~/.beans/ledger.db`). `--json` is available on everything below
except `rule add`/`rule remove`, `recur show` and `tx void`.

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

Dedupe is count-aware on `(date, account, amount)` over **non-void** postings:
re-importing a file is a no-op, but two distinct same-day same-amount rows both
import. It does not know about recurring rules — a rule-posted instance whose
date or amount differs from the statement's is not a duplicate by this key. See
`recurring-overlap.md`.

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

## `beans recur` — rules that post transactions on a schedule

Read-only introspection, which is all this workflow needs:

```
beans recur list [--json]                    # cadence, next_due, status, count
beans recur show NAME                        # postings — no --json
beans recur run --dry-run [--to DATE] [--json]   # instances still owed
beans search recurring --json                # instances already posted
```

| Command | Notes |
|---|---|
| `recur list --json` | `rules[]` with `name`, `frequency`, `start`, `end`, `next_due`, `status` (`due`/`scheduled`/`paused`/`ended`), `posted_count`, `amount`. **No accounts** — and `amount` is the positive (expense) leg, not the sign an asset statement shows. |
| `recur show NAME` | The only place a rule's accounts appear. Text only; the posting block is `    ACCOUNT   AMOUNT` per line, account names may contain spaces. |
| `recur run --dry-run --to DATE --json` | `posted[]` with `rule`, `date`, `description`, `amount` for every occurrence due through DATE. Writes nothing. |
| `search recurring --json` | Instances already posted, tagged `recurring`. Search is a LIKE over description/payee/tags, so re-check `tags` rather than trusting the hit. |

**Writes — never run as part of an import without explicit approval:**

```
beans recur run [--to DATE]        # posts every due occurrence
beans recur pause NAME             # suspends a rule
beans recur remove NAME            # deletes it (history kept, counter lost)
```

`recur` has no edit: changing a rule's amount is `remove` then `add`, which
resets its occurrence counter. There is also no way to mark an occurrence
posted without posting it.

## `beans tx void` — retract a transaction

```
beans tx void ID
```

**One-way. There is no unvoid.** The transaction is kept for history and
filtered out of every query, including import's dedupe — which is what makes it
the tool for replacing a rule-posted instance with the statement's own row.
Requires an open period. Propose it with the id; never run it unasked.

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
beans tx show ID
beans status
beans balances [--json]
beans config list
beans period status
beans period close YYYY-MM-DD       # only when the user asks
```
