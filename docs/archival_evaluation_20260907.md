# Evaluation — periodic ledger archival ("roll forward into a fresh file")

**Date:** 2026-09-07
**Question:** Should `beans` be able to periodically (say annually) create a new
database file that carries no transactions but retains open balances and
average spending rates, so the register does not grow without bound?
**Branch:** `claude/beans-database-archival-9bwmoo`
**Related:** [`project_review_20260616.md`](project_review_20260616.md)
**Method:** read the schema, `Ledger`'s query surface, and every history
consumer (`reports.py`, `analysis.py`, `forecast.py`, `classify.py`,
`status.py`, `budget.py`, `restore.py`); then built the thing — a throwaway
archiver and a throwaway compactor — and ran the real reports against real
ledgers of 1, 5, 10 and 25 synthetic years to see which numbers survive and
which quietly change.

---

## Status — accepted and built

Built on this branch as `beans archive`, scoped as recommended: compaction
is the default, `--drop-detail` is the explicit opt-out, and the
`history_begins` prerequisite (§5) landed with it. `beans/archive.py` plus
`Ledger.history_begins` / `Ledger.detail_begins`, clamping in `networth`,
`report trend`, `forecast`, `analyze` and `status`, 39 tests in
`tests/test_archive.py`, a MANUAL section and a README section.

Measured on the same 25-year ledger this evaluation used, the shipped
command reproduces §4 exactly: **28,564 transactions → 300, 4.57 MB → 0.46
MB**, with `report bs`, `report is`, `report cf`, `report trial`,
`report trend`, `networth`, `analyze` and `forecast` byte-for-byte
identical before and after.

Three deviations from the recommendation, each deliberate:

- **No backup gate.** The recommendation said refuse without a fresh
  `backup`/`export json`. That requirement came from an in-place framing.
  The command writes out-of-place and never touches the source, so the
  source *is* the full-fidelity archive of record — a gate would have been
  ceremony around a guarantee already held. The output says so instead.
- **The archive closes the books through the cutover.** Not in the original
  list, but it follows: the detail that would justify editing an archived
  month no longer exists in that file. A close already standing past the
  cutover is preserved rather than reset.
- **The merchant warning is computed the classifier's way** — same two-leg
  filter, same `merchant_key` normalization — rather than by raw
  description, and skips the descriptions `beans` generates itself
  (`Spending: Rent` is an account restated, not a merchant). On the §4
  fixture it names `COUNTY TAX COLLECTOR` and nothing else.

**Still open:** default row limits on `register`, `tx list` and `search`
(§1a), and the `beans restore` commit-per-transaction problem (Findings,
below). Both are independent of archival and neither is affected by it.

---

## Verdict

**The problem is real, the proposed shape of the fix is not, and there is a
version that gets everything the ask wants at no cost to the books.**

Three separate claims are bundled in the request. They do not stand or fall
together:

| Claim | Verdict |
|---|---|
| The register grows unboundedly | **True**, and it will keep growing. |
| A large register makes `beans` slow or unwieldy | **Mostly false.** 25 years is 4.6 MB and every report runs in under 80 ms. The two commands that genuinely degrade do so because they *print* 28,000 rows, not because they read them. |
| The fix is a new file with balances but no transactions | **No.** It is arithmetically sound and behaviourally disastrous: the balance sheet ties to the cent, and `status`, `forecast`, `networth`, `analyze` and `report trend` all start reporting confident falsehoods with no warning. |

The one-sentence version: **`beans` derives every number from postings, so
deleting postings does not shrink the ledger — it silently changes the
answers.** But nearly every report that matters consumes the register *at
monthly grain already*, which means the register can be **compressed instead of
discarded**. Replacing each archived month with one summary transaction of that
month's per-account totals cuts a 25-year ledger by 93% (4.6 MB → 0.336 MB,
28,564 transactions → 300) and — for any period-aligned query, which is every
default in the tool — **every** figure in the balance sheet, income statement,
cash-flow statement, trend series, net-worth series, forecast and ratio
analysis comes back **bit-for-bit identical**.

Recommendation: **build `beans archive`, but as a compactor, not an eraser** —
and only after the ledger learns to say where its history begins.

---

## 1. The premise, measured: the register is not the problem

A synthetic household — salary with annual raises, a mortgage amortising, a
savings sweep, a brokerage contribution, and 2–4 discretionary transactions a
day — seeded at four horizons and timed in-process (query + render; the ~42 ms
Python interpreter and import cost is excluded and is a constant on every real
invocation):

| | 1 year | 5 years | 10 years | 25 years |
|---|---:|---:|---:|---:|
| transactions | 1,136 | 5,706 | 11,400 | **28,564** |
| postings | 2,286 | 11,473 | 22,921 | **57,429** |
| file size | 0.3 MB | 1.0 MB | 1.9 MB | **4.6 MB** |
| `status` | 15 ms | 19 ms | 28 ms | 75 ms |
| `report bs` | 13 ms | 16 ms | 18 ms | 54 ms |
| `report cf` | 20 ms | 34 ms | 36 ms | 76 ms |
| `networth` | 12 ms | 18 ms | 24 ms | 43 ms |
| `analyze` | 13 ms | 17 ms | 21 ms | 40 ms |
| `forecast` | 13 ms | 18 ms | 24 ms | 54 ms |

**Twenty-five years of daily household activity is 4.6 MB and no report exceeds
80 ms.** Growth is linear, the indices (`idx_postings_txn`,
`idx_postings_account`, `idx_transactions_date`) are the right ones, and the
slowest command in the table costs less than twice the interpreter startup that
precedes it. A user would have to keep books for roughly two centuries before
any of these crossed a second.

So "the register becomes too large" cannot be defended as a *storage* or *query*
problem. It is defensible as two other things.

### 1a. It is an output-volume problem — and that has a cheaper fix

The commands that actually degrade are exactly the ones with no default window:

| | full 25y | monthly roll-up |
|---|---:|---:|
| `register Assets:Checking` | **844 ms** (28,568 lines) | 29 ms (304 lines) |
| `tx list` | **1,123 ms** (85,993 lines) | 75 ms (5,098 lines) |
| `search <term>` | up to **1,471 ms** (95,676 lines) | — |

Nobody reads 86,000 lines. The cost here is rendering and scrollback, not
SQLite. `tx list` and `search` both accept `--limit/-n` but neither *defaults*
to one; `register` has period flags but no limit at all. **A default window on
the three row-listing commands recovers all of this** and costs nothing but a
few lines of argparse — no data is destroyed, and `--limit 0` or an explicit
period still gets the full history. That change is worth making whether or not
archival ever ships, and it addresses the ergonomic complaint directly.

### 1b. It is a legibility problem, which archival does not actually solve

"I don't want to scroll past 2009" is a real feeling. But it is answered by
scoping a view, not by deleting the years — and `beans` already has the
vocabulary: `--period`, `--from/--to`, `--since` on `categorize`, `--limit`.

---

## 2. What the literal proposal does, built and measured

A ~40-line prototype: copy the file, delete `transactions` and `postings`, and
post one opening entry dated the cutover for every non-zero
asset/liability/equity balance. Every other table (accounts, budgets,
recurring, import rules, goals, loans, lots, prices, FX rates, meta) comes
along verbatim — a genuine and underappreciated point in the feature's favour,
covered in §4.

### The balance sheet survives perfectly

Same ledger, as of 2026-09-01, before and after:

| | full register | after archival |
|---|---:|---:|
| Total Assets | $1,384,134.43 | $1,384,134.43 |
| Total Liabilities | $10,900.00 | $10,900.00 |
| **Net Worth** | **$1,373,234.43** | **$1,373,234.43** |
| Equity — Opening Balances | −$247,000.00 | $1,373,234.43 |
| Equity — Retained Earnings | $1,620,234.43 | $0.00 |

Assets, liabilities and net worth are exact. The books balance. What changed is
the *composition* of equity: `balance_sheet()` computes retained earnings on
the fly as cumulative income less expenses (`reports.py:201`), so wiping the
flows folds a lifetime of retained earnings into contributed capital. That is
exactly what a corporate year-end close does, and it is defensible — but it is
worth naming, because `beans` has deliberately *never* closed to equity, and
after the first archive the line "Retained Earnings" no longer means what the
manual says it means.

### Everything time-based starts lying, with no warning

The same archived ledger, no flags, nothing to indicate anything is unusual:

```
$ beans status
Net worth       $1,373,234.43  (+$1,373,234.43 over 30 days)
This month (September 2026)
  Income                              $0.00
  Expenses                            $0.00
```

```
$ beans forecast
Month    Income  Expenses    Net  Proj. Cash  Proj. Net Worth
2026-10    0.00      0.00   0.00  935,634.43     1,373,234.43
2026-11    0.00      0.00   0.00  935,634.43     1,373,234.43
   ... six months of a household that earns nothing and spends nothing
```

```
$ beans networth
2025-10  0.00  0.00  0.00  0.00
2025-11  0.00  0.00  0.00  0.00
   ... twelve months of a household with no assets
```

```
$ beans analyze
  Savings Rate                    n/a
  Liquidity Runway                n/a
```

`report trend` prints six months of zeros the same way.

These are not degradations, they are **false statements presented in the same
format as true ones**. `status` reports the archive itself as a **$1.37 million
gain in thirty days**. `forecast` projects a flat line for a household that in
fact saves 56% of its income. Nothing in the output distinguishes "you earned
nothing" from "this ledger cannot see that far back", because nothing in the
schema records that a horizon exists.

For a tool whose stated contract is that every number ties to postings and the
trial balance always ties, shipping a supported operation that produces these
outputs by design would be the most damaging thing in the codebase.

---

## 3. "Average spending rates" is the load-bearing half — and storing an average is the wrong shape

The ask already anticipates §2: retaining spending rates is what is supposed to
keep the analysis alive. It is the right instinct, and the naive
implementation makes things worse rather than better.

Suppose archival writes a per-account average into a new table. Then:

- **It is not derived from postings.** Every number `beans` prints today is
  traceable to a balanced entry. A stored average is an assertion — the same
  category of input as the economic balance sheet's assumptions, which
  `beans economic` is careful to keep in a config file *outside* the ledger and
  never post. Putting assertions in the ledger and reporting them through the
  same commands as facts erases a distinction the whole design rests on.
- **A scalar cannot serve the consumers.** `forecast --method trend` fits a
  least-squares line over a monthly series (`forecast.py:36–43`); a single
  average has no slope and silently collapses `trend` into `average`.
  `report trend` and `networth` need per-month values. `budget report` needs
  in-period actuals. `analyze` needs the period's own totals to divide by
  `months_in_range`. One number per account satisfies none of them properly and
  would have to be special-cased into six modules.
- **Every consumer would need to learn about it**, and each would have to decide
  what to do when stored averages and real postings overlap in the same window.
  That is a second source of truth for flows, in a codebase that currently has
  exactly one.

The monthly series *is* the average spending rate, at the grain every consumer
already wants — and it can be stored as what it actually is: postings.

---

## 4. The version that works: compress the register, don't discard it

Second prototype. Replace every transaction on or before the cutover with **one
summary transaction per month**, whose postings are that month's per-account
totals, dated the month's last day and tagged `archived`. Then `VACUUM`.

**25 years: 28,564 transactions → 300. 4.6 MB → 0.336 MB (a 93% reduction).**

Running the real reports against both files and diffing the `--json` output
field by field:

| report | field | full register | monthly roll-up | same |
|---|---|---:|---:|:--:|
| `report bs -d 2026-09-01` | net worth | 1,373,234.43 | 1,373,234.43 | ✓ |
| | total assets | 1,384,134.43 | 1,384,134.43 | ✓ |
| | total liabilities | 10,900.00 | 10,900.00 | ✓ |
| | **retained earnings** | 1,620,234.43 | 1,620,234.43 | ✓ |
| `report is --period 2025` | total income | 159,390.00 | 159,390.00 | ✓ |
| | total expenses | 69,438.98 | 69,438.98 | ✓ |
| | net income | 89,951.02 | 89,951.02 | ✓ |
| `report cf --period 2025` | every line | — | — | ✓ |
| `report trend --periods 24` | whole 24-period series | — | — | ✓ |
| `networth` | whole 12-month series | — | — | ✓ |
| `analyze --period 2025` | savings rate | 56.4% | 56.4% | ✓ |
| | **liquidity runway** | 154.5 months | 154.5 months | ✓ |
| `forecast` | whole 6-month projection | — | — | ✓ |

Not "close enough" — identical, including retained earnings, the direct-method
cash-flow classification, and the ratios that went to `n/a` under §2. The
reason is structural rather than lucky: `balances()`, `flows()`,
`monthly_flows()` and `monthly_type_totals()` are all `SUM(...) GROUP BY`, and a
sum of monthly sums is the monthly sum. Any report built on those four methods
is invariant under this transformation, and that is every report except the ones
that print individual rows.

**The exact boundary of that claim: monthly grain.** A window that starts or
ends mid-month no longer ties, because the month's activity now sits on a single
day. Same ledger:

| query | full register | monthly roll-up |
|---|---:|---:|
| `report bs -d 2025-06-30` (month end) | $1,267,802.17 | $1,267,802.17 |
| `report bs -d 2025-06-15` (mid-month) | $1,270,448.13 | **$1,260,342.07** |
| `report is --from 2025-06-15 --to 2025-07-15` — net income | $6,441.85 | **$7,460.10** |

Every default in `beans` is already period-aligned — `--period`, `networth`,
`report trend`, `forecast`, `analyze`, `status` — so this does not fire in
ordinary use. But it is a real edge, and `archive` should say so plainly rather
than leave it to be discovered: after compaction the pre-cutover register
answers month-boundary questions exactly and mid-month questions approximately.
A finer grain narrows that window but is **not** a free improvement, which is
worth knowing before someone offers it as a `--grain` flag. Re-running the
compactor at weekly grain gives 1,327 transactions and 0.815 MB — still an 82%
reduction — but `report trend`, `networth` and `forecast` all stop matching the
full register, because ISO weeks straddle month boundaries and the summary
lands wholly in one month. **The roll-up grain must divide the coarsest period
any report groups by**, which in `beans` is the month. If sub-monthly detail is
ever wanted, the buckets have to be clipped at month ends rather than run on
their own calendar.

It also captures nearly all of the speed win that motivated the request —
`status` 75 ms → 16 ms, `report cf` 76 ms → 18 ms, `register` 844 ms → 29 ms —
while `beans report bs` still reconciles to the same cent.

### What compaction still costs

Honest list, because these are real:

- **Line-item detail is gone**: payees, descriptions, individual amounts,
  `cleared` flags, void history, and the ability to `search`, `tx show`,
  `register` or `reconcile` an archived month.
- **The classifier loses its training data.** `counter_account_history`
  deliberately returns only two-legged transactions (`ledger.py:1212`), and a
  monthly roll-up has many legs — so `beans categorize` sees a history size of
  0 after either form of archival. Measured on a 10-year ledger with realistic
  recurring merchants, keeping only the last 12 months:

  | merchant | full history | after a 1-year archive |
  |---|---|---|
  | WHOLE FOODS MKT | Groceries 1.00 (480 prior) | Groceries 0.96 (48 prior) |
  | NETFLIX.COM | Entertainment 0.98 (120 prior) | Entertainment 0.86 (12 prior) |
  | STATE FARM AUTO | Insurance 0.96 (49 prior) | Insurance 0.60 (3 prior) |
  | HVAC SERVICE CO | Utilities 0.87 (13 prior) | Utilities 0.33 (1 prior) |
  | **COUNTY TAX COLLECTOR** | Taxes 0.82 (9 prior) | **no suggestion at all** |

  The pattern is the point: everyday merchants degrade gracefully, and the
  **annual** ones fall off a cliff — and an *annual* archive is precisely the
  cadence the request proposes. The mitigation already exists and needs no new
  code: `import_rules` is a side table, untouched by any archival, and the
  classifier's own docstring calls a rule "a hand-maintained cache of a decision
  your books already record". `beans archive` should offer to mint rules for the
  merchants it is about to forget.
- **Mid-period queries become approximate** (table above).
- **Tax and audit substantiation.** Most jurisdictions want line-level records
  for three to seven years. Any archive command must refuse to run without a
  full-fidelity `beans backup` or `beans export json` beside it, and should
  print where it landed.

Everything else survives untouched, because `beans` keeps it in side tables
already: accounts, budgets, recurring rules and their postings, import rules,
goals, loans, FIFO `lots`, `prices`, `fx_rates`, and `meta`. This is the
strongest argument that the feature is *feasible*: only one of thirteen tables
is actually being archived.

---

## 5. Prerequisite: the ledger has to know where its history begins

The zero-padding in §2 is **not caused by archival**. A ledger created today
does it too:

```
$ beans init && beans tx add --date 2026-09-01 --desc "Opening balances" \
      --post Assets:Checking 5000 --post "Equity:Opening Balances"
$ beans networth
2025-10  0.00  0.00  0.00  0.00
2025-11  0.00  0.00  0.00  0.00
   ...
$ beans forecast
2026-10    0.00      0.00   0.00    5,000.00   5,000.00
```

Every new `beans` user sees this on day one. `networth`, `forecast`,
`report trend` and `analyze` all treat "before the register starts" as
"zero" rather than "unknown", and none of them says so.

This is worth fixing on its own merits, and it is a **hard prerequisite** for
archival: the difference between a defensible archive and a dangerous one is
whether the reports can tell the user their window predates the data. Concretely:

- record `history_begins` in `meta` (set by `init` from the first transaction,
  and by `archive` to the cutover);
- have the series reports clamp their window to it and print one line —
  `History begins 2026-09-01; 11 earlier months omitted` — instead of zeros;
- have `forecast` and `analyze` report `n/a` with that reason rather than
  projecting a flat line, and have `status` suppress the "over 30 days" delta
  when the comparison point predates the history.

Under compaction (§4) this rarely fires, because the monthly series survives.
It fires exactly when it should: on a young ledger, and on the pre-cutover
window of a hard-truncated one.

---

## 6. Recommendation

**Build it, scoped like this:**

1. **First, and independently of archival:**
   - `history_begins` in `meta` plus honest "before the register" handling in
     `networth`, `forecast`, `report trend`, `analyze` and `status` (§5). This
     is a bug fix that today's users are already hitting.
   - Default row limits on `register`, `tx list` and `search` (§1a). This is
     most of the ergonomic complaint, for a few lines of argparse.

   If these two land and the user's actual pain was legibility, archival may
   turn out to be unnecessary — which is a good reason to do them first.

2. **Then `beans archive --through DATE`**, defaulting to **compaction**, not
   deletion:
   - refuse without a fresh `backup`/`export json`, and say where it is;
   - `--dry-run` showing transaction count, projected file size, and an explicit
     before/after balance-sheet and trial-balance comparison — the invariant
     being that both must be unchanged, which is checkable and worth asserting
     in code, not just in tests;
   - write one tagged `archived` summary transaction per **month** — the grain
     is not a knob, it is the coarsest period any report groups by (§4) — then
     `VACUUM` and set `history_begins`;
   - offer to mint `import_rules` for merchants whose classification history is
     about to disappear (§4);
   - interact sanely with `period close` — archiving should imply closing the
     books through the cutover, since the detail backing them is gone.
   - Write to a **new file** (`--out`) rather than in place, matching the ask
     and keeping the operation trivially reversible.

3. **Offer `--drop-detail` as the explicit, non-default hard truncation** for
   someone who genuinely wants balances only and accepts blind analytics. With
   `history_begins` in place it degrades honestly instead of lying.

**Do not build:** a `--grain` flag finer than monthly (§4), and a
stored-averages table. The monthly series is the average
spending rate, it is expressible as postings, and keeping it that way is what
lets §4's numbers come back identical instead of approximately right.

---

## Findings spun out of this evaluation

Neither is caused by archival; both were found while measuring it.

1. **`beans restore` is O(n) with a very large constant — 28 seconds for a
   25-year ledger.** `restore.py:109` calls `led.add_transaction` per
   transaction, and `add_transaction` wraps each insert in `with self.db:` —
   one commit, and one fsync, per transaction. 28,564 transactions took 27.7 s
   wall against 10.7 s of CPU; the rest is disk sync. Batching the restore into
   a single transaction should make it near-instant. **This is the only
   operation in `beans` that is genuinely slow on a large ledger, and archival
   does not fix it — fixing `restore` does.**

2. **`register`, `tx list` and `search` have no default limit** (§1a), so they
   print the entire register: 86,000 lines and 1.1 s for `tx list` at 25 years.
   `tx list` and `search` accept `-n`; `register` has no limit flag at all.

---

## Appendix — reproducing this

Prototypes and benchmarks were throwaway scripts, not committed: a seeder
(salary with raises, mortgage amortisation, savings sweep, brokerage
contribution, 2–4 daily discretionary transactions, `random.seed(7)`), a
40-line archiver (§2), a 45-line compactor (§4), and a comparator that runs the
real CLI with `--json` against both files and diffs the fields. All timings are
in-process on one machine and are meant as orders of magnitude, not benchmarks;
the conclusions rest on the ratios and on the exact-equality results, neither of
which is machine-dependent. The classifier table in §4 uses a separately seeded
10-year ledger with ten realistic recurring merchants (`random.seed(11)`).
