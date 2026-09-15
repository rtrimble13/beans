# Evaluation — forecasted financial statements (`beans forecast --report bs`)

**Date:** 2026-09-15
**Question:** Should `beans forecast` be able to produce a forecasted balance
sheet, income statement and statement of cash flows — e.g.
`beans forecast -n 1 --report bs` for a one-month-ahead balance sheet — in the
same format `beans report` uses?
**Branch:** `claude/cool-turing-6x3i8b`
**Related:** [`archival_evaluation_20260907.md`](archival_evaluation_20260907.md),
[`project_review_20260616.md`](project_review_20260616.md)
**Method:** read `forecast.py`, `reports.py`, `ledger.py`, `loans.py`,
`recurring.py`, `archive.py` and `economic.py`; then built a working
prototype — a projection engine and a read-only ledger overlay — and ran the
**real, unmodified** `reports.balance_sheet`, `reports.income_statement` and
`reports.cash_flow_statement` against it on three synthetic ledgers
(an 18-month household with a mortgage, a card cycle, a savings sweep and a
brokerage contribution; an archived copy of it; and a recurring-driven
ledger), measuring every number against the ledger's own actuals.

---

## Verdict

**Build it. The feature is worth more than it looks, it is cheaper than it
looks, and it exposes a live defect in the existing forecast that ought to be
fixed anyway.**

Three findings drive the recommendation:

| Claim | Verdict |
|---|---|
| `beans forecast` can be extended to emit the three statements | **Yes** — and with **zero changes to `reports.py`'s statement math**. The prototype runs the real, unmodified report builders. |
| The current engine already has the data it needs | **No.** `forecast` models only the *income statement*. It never looks at the asset/liability legs of a transaction, so it cannot say where the money lands, and it is structurally blind to savings sweeps, brokerage contributions, card payoffs and loan principal — of which the pure transfers alone are **$2,680/month of cash movement** in the test household. |
| The current `Proj. Cash` column is sound | **No.** It assumes every dollar of net income accumulates as cash. On the test ledger that overstates 12-month cash by **$14,955.60 (23%)** — and the household's own measured cash run-rate agrees with the pro-forma, not with the column. Building the balance sheet fixes it. |

The one-sentence version: **a forecasted balance sheet cannot be assembled
from forecasted totals — it has to be assembled from forecasted
*transactions*.** Project balanced double entries instead of two aggregate
columns, overlay them on the ledger read-only, and the existing statement
builders do the rest — correctly classified, balancing to the cent, in
exactly the format `beans report` prints today.

---

## 1. What the ask actually requires

`forecast()` projects one number per income/expense account, sums them into
`income` / `expenses` / `net`, and then does this:

```python
cumulative += row["net"]
row["projected_cash"] = cash_now + cumulative
row["projected_net_worth"] = net_worth_now + cumulative
```

That is the whole balance-sheet model: **one accumulator, applied to both
cash and net worth.** It is enough for a two-column summary and nowhere near
enough for a balance sheet, which needs a figure for *every* asset and
liability account, a retained-earnings roll-forward, a current/non-current
split, and `assets == liabilities + equity`.

The gap is not arithmetic, it is *structural*. Of the 72 transactions in the
test ledger's six-month lookback window:

| | count | what the current engine sees |
|---|---:|---|
| Transactions with an income/expense leg | 54 | only the income/expense legs; the funding side is discarded |
| Transactions with **no** income/expense leg at all | 18 | **nothing** — invisible |

Those 18 are the savings sweep, the brokerage contribution and the credit-card
payoff: **$2,680 a month of cash leaving the checking account** that the
forecast does not know exists. They never touch the income statement, so they
never reach the projection — but they are most of what determines what the
balance sheet looks like next month.

## 2. The defect this surfaces: `Proj. Cash` is wrong today

The test household earns $7,618 and spends $5,227.53 a month, netting
$2,390.47. `beans forecast -n 12` therefore claims cash grows by $2,390.47 a
month. The ledger's own month-end cash says otherwise:

| month-end | cash | Δ |
|---|---:|---:|
| 2026-03 | 45,018.00 | +1,126.00 |
| 2026-04 | 46,170.00 | +1,152.00 |
| 2026-05 | 47,340.00 | +1,170.00 |
| 2026-06 | 48,459.00 | +1,119.00 |
| 2026-07 | 49,630.00 | +1,171.00 |
| 2026-08 | 50,757.00 | +1,127.00 |

**$1,144 a month, not $2,390** — because $900 goes to the brokerage and ~$503
pays down mortgage principal. Neither reduces net worth, so the
`Proj. Net Worth` column is fine; both reduce *cash*, so the `Proj. Cash`
column is not:

| horizon | `forecast` says | pro-forma says | overstatement |
|---|---:|---:|---:|
| 12 months | **79,442.64** | **64,487.04** | **+14,955.60 (23.2%)** |

A liquidity number that is 23% high is worse than no liquidity number, and
this is the column a user consults before deciding whether next year's plan is
affordable. The prototype's figure lands within $206 of a naive extrapolation
of the household's measured cash run-rate ($64,281).

Meanwhile the pro-forma reproduces the existing `Proj. Net Worth` column
**to the cent** at every horizon tested (n=1: 244,298.20; n=6: 256,250.55;
n=12: 270,593.37) — so this is a strict improvement, not a different answer.

## 3. The design: project transactions, not aggregates

Three pieces, all prototyped and measured.

### 3.1 The funding mix — where the money comes from

For every transaction in the lookback window, split the postings into
income/expense legs and balance-sheet legs, and attribute each balance-sheet
leg to the income/expense legs in proportion to their share of the
transaction. Normalize by the account's own flow and you get, per account, the
balance-sheet accounts that historically funded it. Run on the test ledger it
recovers the household's real plumbing exactly:

```
Expenses:Food:Dining          Liabilities:Credit Card -1.00
Expenses:Food:Groceries       Liabilities:Credit Card -1.00
Expenses:Housing:Utilities    Assets:Checking -1.00
Expenses:Insurance            Assets:Checking -1.00
Expenses:Interest             Assets:Checking -1.35, Liabilities:Mortgage +0.35
Expenses:Shopping             Liabilities:Credit Card -1.00
Expenses:Taxes                Assets:Checking -1.00
Expenses:Transportation       Liabilities:Credit Card -1.00
Income:Interest               Assets:Savings -1.00
Income:Salary                 Assets:Checking -1.00
```

It found, with no configuration: that groceries, dining, shopping and transport
go on the card; that salary and withheld tax move through checking; that
savings interest accrues in savings; and that the mortgage payment is 135% of
its interest charge in cash, of which 35% retires principal. That last row is
the amortization split, learned from history.

### 3.2 Pure balance-sheet transfers — the invisible half

Transactions with no income/expense leg are projected separately, as a
per-account monthly run-rate. On the test ledger:

```
Assets:Checking                 -2,680.00 / month
Assets:Investments:Brokerage       900.00
Assets:Savings                     600.00
Liabilities:Credit Card          1,180.00
```

These sum to zero by construction (each source transaction balanced), so they
add no plug.

### 3.3 The overlay — read-only, no copy, no write

The statement builders touch only five `Ledger` methods: `accounts`,
`balances`, `flows`, `transactions` and `loans`. A ~40-line wrapper that adds
the projected transactions to the last three is all the integration needed.

Rejected alternatives, for the record: **copying the database** (wasteful, and
`archive.py` already shows how much ceremony a second file needs) and
**inserting inside a rolled-back SQLite transaction** (elegant, but it demands
write access and would break the MCP server's read-only guarantee). The
overlay works on a read-only file and cannot mutate the ledger even by
accident.

### 3.4 One projected transaction per driver, not one per month

The first prototype bundled each future month into a single transaction. The
balance sheet was fine; the cash-flow statement was not. `cash_flow_statement`
skips transactions with no cash leg — that is how a credit-card purchase
correctly stays out of operating cash until the card is paid. A bundled
monthly transaction touches cash, so **every** card charge got counted as an
operating cash outflow:

| section (one projected month) | bundled | per-driver | actual Aug 2026 |
|---|---:|---:|---:|
| operating | 2,390.47 | **3,727.47** | 3,716.34 |
| investing | -900.00 | -900.00 | -900.00 |
| financing | -346.30 | **-1,683.30** | -1,689.34 |
| net change in cash | 1,144.17 | 1,144.17 | 1,127.00 |

**$1,337.00 a month misclassified** — exactly the card-funded spend. Emitting
one balanced transaction per driver fixes it, and the projected October
statement then comes out line-for-line congruent with the household's actual
August statement. *This is load-bearing: the projection's grain has to be the
grain the classifier reads.*

## 4. Prototype results

All three statements, produced by the **unmodified** `reports.py` builders and
renderers, in the `beans report` format:

```
BALANCE SHEET                                 STATEMENT OF CASH FLOWS
As of: 2026-10-31                             For the period: 2026-10 (projected)

Assets                                        Cash Flows from Operating Activities
  Current Assets                                Expenses:Housing:Utilities    -165.83
    Checking                 16,159.17          Expenses:Insurance            -145.00
    Savings                  35,742.00          Expenses:Interest           -1,451.70
  Current Assets subtotal   $51,901.17          Expenses:Taxes              -2,128.00
  Non-current Assets                            Income:Interest                 18.00
    Home                    420,000.00          Income:Salary                7,600.00
    Investments                               ---------------------------------------
      Brokerage              77,100.00        Net Cash from Operating       $3,727.47
  Non-current subtotal     $497,100.00
-------------------------------------         Cash Flows from Investing Activities
Total Assets               $549,001.17          Assets:Investments:Brokerage  -900.00
                                              Net Cash from Investing         -$900.00
Liabilities
  Current Liabilities                         Cash Flows from Financing Activities
    Credit Card               4,012.00          Liabilities:Credit Card     -1,180.00
    Mortgage                  6,366.38   (a)    Liabilities:Mortgage          -503.30
  Non-current Liabilities                     Net Cash from Financing       -$1,683.30
    Mortgage                294,324.59
-------------------------------------         ---------------------------------------
Total Liabilities          $304,702.97        Net Change in Cash            $1,144.17
                                              Cash at Beginning of Period  $50,757.00
Equity                                        Cash at End of Period        $51,901.17
  Opening Balances          200,800.00
  Retained Earnings          43,498.20   (b)
-------------------------------------
Total Equity               $244,298.20
Liabilities + Equity       $549,001.17
Net Worth                  $244,298.20
```

*(a)* the projected mortgage balance, split into its current and non-current
portions by the amortization schedule — `classified_liability_split` does this
for free, because it is handed a balance and does not care that the balance is
a projection. *(b)* retained earnings, rolled forward by projected net income.

Measured properties:

- **It balances.** `balanced == True` at horizons of 1, 6, 12 and 60 months,
  on both methods, on the full and archived ledgers, and on an empty ledger.
- **It articulates.** Projected net change in cash ($1,144.17) equals ending
  minus opening cash ($51,901.17 − $50,757.00), and retained earnings advance
  by exactly projected net income.
- **It is fast.** 3.5–6.7 ms end to end for horizons of 1 to 60 months —
  a fraction of the ~42 ms Python interpreter startup that precedes every
  invocation, and flat in the horizon.
- **It degrades.** An empty ledger yields a balanced, all-zero statement
  rather than an exception.

## 5. Five things the implementation must decide

### 5.1 The stub month is a real gap — close it

`forecast` projects from *next* month (`_month_keys(this_month, months+1)[1:]`)
but anchors on `position(as_of=today)`. The remainder of the current month is
therefore in neither history nor projection. In a summary of monthly nets that
is merely untidy; on a statement dated 2026-10-31 it is a missing month. On
the recurring test ledger (last actual 2026-08-31, today 2026-09-15) the
projected 31 October checking balance came out **55,800 instead of 58,400** —
September silently skipped.

**Recommendation:** define the projection window as `(base_date, horizon_end]`
where `base_date = today` and `horizon_end` is the end of the month `N` months
out, and fill the stub — `today+1` through the end of the current month — at
the monthly run-rate pro-rated by remaining days. Disclose it in the header.
**Constraint:** `economic.py` reads `data["months"][0]["income"]` as a *full*
month's run-rate, so the stub must live under a separate key, never as
`months[0]`.

### 5.2 Period semantics for `is` and `cf`

A balance sheet is a point in time (`as_of = horizon_end`). The two flow
statements need a window, and the choice matters: only the **cumulative
horizon window** makes the three statements articulate with each other. Use
it, label it `"2026-10 – 2027-09 (projected)"`, and assert the articulation in
tests.

### 5.3 Recurring rules must not be counted twice

`--use-recurring` today overrides *history* for the income/expense accounts a
rule covers. In the pro-forma world a rule supplies the whole transaction,
including its balance-sheet legs — and those legs also sit in the historical
run-rate, because `recur run` posted them. Measured on the recurring test
ledger (rent $1,800 and a $600 sweep, both rules, both posted):

| basis | projected checking |
|---|---:|
| history only | 55,800.00 |
| history **+ rule templates** (naive) | 51,000.00 — **$4,800 double-counted** |
| `recurring`-tagged history excluded, + rule templates | 53,400.00 |

**Recommendation:** when `--use-recurring` is on, exclude transactions tagged
`recurring` from the lookback basis, then add the rules' pending occurrences
from `pending_occurrences` (which already carries the runaway guard). This is
also *strictly better* than today's account-level override, which throws away
the non-recurring part of a covered account's history — an extra insurance
payment made by hand currently vanishes from the projection.

### 5.4 Loans: prefer the schedule where one is attached

The funding mix holds the interest/principal split at its historical average,
so an amortizing loan never amortizes. Measured against `loans.schedule()` on
the test mortgage ($301,194 at 5.75%):

| months out | run-rate balance | schedule balance | error |
|---:|---:|---:|---:|
| 1 | 300,690.97 | 300,682.49 | 8.48 |
| 12 | 295,154.67 | 294,888.46 | 266.21 (0.09%) |
| 24 | 289,115.07 | 288,210.38 | 904.69 |
| 36 | 283,075.47 | 281,138.02 | 1,937.45 (0.7%) |

Tolerable at a year, sloppy at three. `loans.py` already computes the exact
split and `classified_liability_split` already uses the schedule to split the
*projected* balance into current and non-current — so driving the projection
from the schedule too is a few lines and removes the drift entirely.

### 5.5 What the forecast must not pretend to know

The projected balance sheet carries investments at **last mark plus projected
contributions** — no market return — and foreign-denominated accounts at the
**last known rate**, with no FX revaluation. Both are the honest default (a
forecast should not invent a return assumption), and both must be said out
loud in the header and in `--json`, not left for the user to discover.

## 6. Interaction with `beans archive`

`beans archive` replaces each archived month with one summary transaction —
which is precisely the bundling that §3.4 showed breaks cash-flow
classification. Archiving the test ledger through 2026-06 (so four of the six
lookback months are summaries) and re-running the prototype:

| | full detail | archived | effect |
|---|---:|---:|---|
| funding-mix entries | 11 | 50 | every expense "funded by" every account |
| projected per-account balances (`average`) | — | — | **identical to the cent** |
| projected per-account balances (`trend`) | — | — | drift up to **$13.06** in one month |
| projected operating cash flow | 3,727.47 | 2,390.47 | **$1,337.00 misclassified** |

So the archive promise — *every period report returns the same figures* —
holds for the forecasted **balance sheet** under `average` (the proportional
allocation conserves aggregate flows) and **does not hold** for the forecasted
**cash-flow statement**, nor exactly for `trend`.

**Recommendation:** clamp the funding-mix window to `Ledger.detail_begins` and
warn when the requested window is partly compacted — the same pattern
`beans archive` already established for `history_begins` in `forecast`,
`networth`, `trend`, `analyze` and `status`. `detail_begins` exists and is
currently read in exactly one place (`cli.py:893`); this is its second
legitimate consumer.

## 7. CLI surface

Take the ask as written — a flag, not a subcommand tree:

```
beans forecast [-n N] [--method …] [--lookback N] [--use-budget]
               [--use-recurring] [--report {summary,is,bs,cf,all}] [--json]
```

- `--report` accepts the **same tokens `beans report` accepts** (`income`/`is`,
  `balance`/`bs`, `cashflow`/`cf`), so `forecast --report bs` and `report bs`
  read alike.
- `summary` is the default and is today's output, so **nothing existing
  changes shape** (the `Proj. Cash` figures do change — see §2 — which is the
  point, and belongs in the release notes).
- `all` prints income statement, balance sheet and cash flows in sequence.
- Shell completions are generated from the live argparse tree and complete
  subcommands, not flags, so `completions.py` needs no change.

**Format.** Reuse `reports.render_*` verbatim, with one two-line change per
renderer: honour an optional `data["title"]` and an optional basis note. The
statement then prints as `PROJECTED BALANCE SHEET` over the identical table.

**JSON.** The dict is the `reports.*` dict plus a `forecast` block
(`{"projected": true, "basis": …, "horizon_months": N, "window": …,
"warnings": [...]}`). `jsonify` needs no new `NON_MONEY_KEYS` entries —
`horizon_months`, `lookback_months` and `lookback_requested` are already
listed. A machine consumer must never be able to mistake a projection for an
actual.

**MCP.** `_toolcore/tools.py` exposes `get_forecast`; add the `report`
argument there so Claude can ask for a projected statement — or leave it for a
follow-up, since the three statement tools already exist for actuals.

## 8. Implementation plan

**Phase 1 — the engine (new `beans/proforma.py`, ~350 lines).**
`funding_mix()`, `transfer_run_rates()`, `project()` returning projected
`Transaction` objects, and the `ProForma` read-only overlay. Loan schedules
(§5.4), the `recurring` tag filter (§5.3), the `detail_begins` clamp (§6) and
the stub month (§5.1) all land here.

**Phase 2 — the statements (`beans/forecast.py`, ~120 lines).**
`forecast_statement(led, kind, months, …)` builds the overlay, calls the
existing `reports.*` builder, and attaches the `forecast` block.
`forecast()`'s existing return contract is **unchanged** — `economic.py`
depends on it — except that `projected_cash` is now taken from the pro-forma
(§2).

**Phase 3 — renderers (`beans/reports.py`, ~10 lines).**
Optional `title` / note in the three statement renderers. No change to any
statement's arithmetic.

**Phase 4 — CLI (`beans/cli.py`, ~30 lines).** `--report`, dispatch, `all`.

**Phase 5 — tests (`tests/test_proforma.py`, ~400 lines).** Twelve properties,
each of which the prototype already demonstrates: it balances at every
horizon/method; the three statements articulate; the funding mix recovers a
known card/cash split; pure transfers appear; recurring rules are not
double-counted; the net-worth column stays identical to today's, to the cent;
`projected_cash` matches the pro-forma; empty and single-month ledgers degrade
without exceptions; loans follow the schedule; `average` figures survive
`beans archive` and a compacted window warns; `--report bs --json` is
self-identifying; and `forecast()`'s dict keeps every key `economic.py` reads.

**Phase 6 — docs.** A `--report` row and a statements subsection in the
MANUAL's `forecast` chapter, four lines in the README's Forecasting block, and
a note in the archival section that the forecasted cash-flow statement is the
one figure a compacted lookback window changes.

Baseline for the work: `575 passed, 11 skipped` on `main` at `ca04871`.

## 9. Risks and non-goals

- **The funding mix is a historical inference, not a plan.** A household that
  is about to stop putting groceries on the card will be projected as if it
  hasn't. This is the same class of assumption `--method average` already
  makes about amounts; the fix is `--use-recurring` and budgets, not cleverness.
- **Rounding.** Per-driver transactions need a residual plug into the largest
  funder to stay balanced to the cent. Prototyped; the plug never exceeded one
  cent per transaction.
- **Not in scope:** market returns on investments, FX revaluation, tax
  modelling, scenario comparison (`--what-if`), and projecting *equity*
  accounts other than retained earnings.
- **Nothing is ever written.** The overlay is read-only by construction, so
  the MCP server's read-only guarantee and `beans period close` are both
  untouched.

## 10. Recommendation

Build it, in the shape above: **a pro-forma transaction generator plus a
read-only ledger overlay, feeding the existing statement builders unmodified.**
It gives the user exactly what was asked for — `beans forecast -n 1 --report
bs`, in `beans report`'s format — while repairing a 23% error in the cash
column the tool already prints, and it does so without touching a line of
statement arithmetic.
