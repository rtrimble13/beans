# beans

**Professional-grade double-entry accounting for personal finance, from the command line.**

`beans` lets you keep your household books the way a company keeps theirs: every
transaction is a balanced set of debits and credits, and your finances roll up
into the same three statements analysts use to evaluate public companies — an
income statement, a balance sheet, and a statement of cash flows. On top of the
ledger it layers budgeting, forecasting, and ratio analysis tailored to
personal finance.

- **True double-entry** — transactions must balance to the cent; the trial
  balance always ties.
- **Corporate-style statements** — income statement (with common-size % and
  prior-period comparison), balance sheet (with computed retained earnings),
  and a direct-method statement of cash flows classified into operating,
  investing, and financing activities.
- **Budgeting** — per-account budgets at weekly/monthly/quarterly/yearly
  cadence, with budget-vs-actual variance reports over any period.
- **Forecasting** — project income, expenses, cash, and net worth forward from
  historical averages, a linear trend, or your budgets.
- **Analysis** — savings rate, liquidity runway, debt-to-assets,
  debt-to-income, and expense composition.
- **Reconciliation** — clear postings against bank statements and reconcile
  to the cent, the way errors actually get caught.
- **Investments** — FIFO lots, price history, realized gains on sale, and
  mark-to-market adjustments so the balance sheet carries market value.
- **Multi-currency** — foreign-denominated accounts with parallel foreign
  balances, exchange-rate history, and FX revaluation, while the books and
  statements stay in your base (functional) currency.
- **Export & backup** — the whole ledger as JSON or flat CSV, and
  consistent point-in-time SQLite snapshots.
- **Goals** — savings targets and debt payoff dates with required-monthly
  math, plus period close to lock historical books.
- **Ease of use** — a `beans status` dashboard, `spend` / `earn` / `transfer`
  shortcuts with instant budget feedback, fuzzy account matching
  (`groceries` → `Expenses:Food:Groceries`), full-text search, undo,
  deduplicating CSV import with auto-categorization rules, shell
  completions, and `--json` output on every report for scripting.
- **No dependencies** — pure Python standard library; data lives in a single
  SQLite file you own.

## Installation

From PyPI:

```sh
pip install beans-ledger
```

The package is published on PyPI as **`beans-ledger`** (the name `beans` was
already taken), but it still installs the `beans` command and is imported as
`beans`. Or install from a checkout:

```sh
pip install .
```

Requires Python 3.10+. This installs the `beans` command.

## Quick start

```sh
# Create a ledger (default: ~/.beans/ledger.db; override with -f or $BEANS_LEDGER)
beans init

# Record opening balances against equity, like a company's opening entry
beans tx add --date 2026-01-01 --desc "Opening balances" \
    --post Assets:Checking 5000 \
    --post Assets:Savings 10000 \
    --post "Liabilities:Credit Card" -1200 \
    --post "Equity:Opening Balances"        # omitted amount auto-balances

# Day-to-day entries — fuzzy account names, defaults to your checking account
beans earn 6000 Salary --date 2026-01-15 --desc "January paycheck"
beans spend 1800 Rent --date 2026-02-01
beans spend 450.25 Groceries --payee "Market"
beans transfer 1000 Checking Savings

# The three statements
beans report income --period ytd
beans report balance
beans report cashflow --period ytd

# Or just run `beans` for the dashboard: cash, net worth, month vs budget,
# due recurring rules, and goal progress on one screen.
beans
```

## Walkthroughs

New here? The [`docs/vignettes/`](docs/vignettes/) directory has guided,
task-oriented walkthroughs that take a workflow from start to finish with real
captured output:

1. [Getting started](docs/vignettes/01-getting-started.md) — set up a ledger and
   read your first statements.
2. [Budgeting a month](docs/vignettes/02-budgeting-a-month.md) — set targets and
   track spending against them.
3. [Import & reconcile](docs/vignettes/03-import-and-reconcile.md) — import a
   bank CSV and tie out to your statement.
4. [Recurring, goals & investing](docs/vignettes/04-recurring-goals-investing.md)
   — automate bills, set goals, and track investments.
5. [Loans & liquidity](docs/vignettes/05-loans-and-liquidity.md) — classify
   current vs non-current, finance a loan, and read a classified balance sheet
   with liquidity ratios.
6. [The economic balance sheet](docs/vignettes/06-economic-balance-sheet.md) —
   value human capital and future consumption to see lifetime net worth
   alongside the accounting balance sheet.

The rest of this README is the command reference. For the full instruction
manual — every command, every flag, with parameter tables and best practices
for each — see [`docs/MANUAL.md`](docs/MANUAL.md).

## Concepts

### Accounts

Accounts are hierarchical (`Expenses:Food:Groceries`) and typed: `asset`,
`liability`, `equity`, `income`, or `expense`. `beans init` creates a starter
chart of ~23 accounts; reshape it freely:

```sh
beans account add Expenses:Pets --type expense
beans account add Assets:HSA --type asset --cash
beans account modify Liabilities:Loans --rename Liabilities:Mortgage
beans account list                # with balances; --type expense to filter
beans account close Assets:HSA    # requires a zero balance
```

Two flags drive the statement of cash flows:

- `--cash` marks an asset as cash or a cash equivalent (checking, savings,
  wallet). The cash flow statement explains the change in these accounts.
- `--cashflow operating|investing|financing` overrides the activity an
  account's flows are classified under. Defaults follow corporate convention:
  income/expense → operating, non-cash assets → investing,
  liabilities/equity → financing.

Assets and liabilities also carry a **liquidity** classification —
`current` (realizable or due within a year) or `noncurrent` (beyond a year) —
that drives the classified balance sheet and the working-capital ratios.
Everything defaults to `current`; mark the long-term ones:

```sh
beans account add Assets:Prepaid:Insurance --type asset          # current
beans account modify Retirement --noncurrent                     # long-term
beans account add "Liabilities:Mortgage" --type liability --noncurrent
beans account modify "Credit Card" --current
```

For an amortizing debt (mortgage, auto, student loan), don't classify by hand —
attach a loan and let the amortization schedule split it (see **Loans** below).

### Transactions

Every transaction is a list of postings that sum to zero (debits positive,
credits negative). The general form handles any complexity — a paycheck with a
401(k) deduction, for example:

```sh
beans tx add --desc "Paycheck" --date 2026-02-15 \
    --post Assets:Checking 4000 \
    --post Assets:Investments:Retirement 1000 \
    --post Income:Salary              # balances to -5000
```

For the common cases there are shortcuts, each a balanced two-leg entry:

```sh
beans spend 54.20 Dining --from "Credit Card" -m "Pizza night"
beans earn 120 Interest --to Savings
beans transfer 500 Checking Savings
```

`spend`/`earn` default the cash side to your checking account; change it with
`beans config set default_account Savings`. Inspect and correct history with:

```sh
beans tx list --period this-month
beans tx show 42
beans tx void 42        # voids keep the audit trail; nothing is deleted
beans undo              # void the most recent transaction (typo insurance)
beans search "whole foods"             # full-text over descriptions/payees
beans tx add --like 42 --date today    # clone a prior transaction
beans register Checking --period ytd   # running-balance view of one account
beans balances          # everything, grouped by type
beans report trial      # the accountant's sanity check
```

After `beans spend` against a budgeted category, you get instant feedback
("Groceries: 92% of June budget used"), and any command reminds you (on
stderr) when recurring rules are due.

### Recurring transactions

Bills, paychecks, subscriptions — define them once and post them on demand:

```sh
beans recur add rent --freq monthly --start 2026-07-01 \
    --post Expenses:Housing:Rent 1800 --post Assets:Checking
beans recur add paycheck --freq biweekly --start 2026-07-03 \
    --desc "Salary deposit" --post Assets:Checking 2500 --post Income:Salary

beans recur list            # shows which rules are due
beans recur run --dry-run   # preview everything due through today
beans recur run             # post it (idempotent — run as often as you like)
beans recur run --to 2026-12-31   # post ahead, e.g. for planning
```

Frequencies: `daily`, `weekly`, `biweekly`, `monthly`, `quarterly`,
`yearly`. Monthly-style rules anchor to the start date's day-of-month and
clamp to short months (a rule started Jan 31 posts Feb 28, then Mar 31).
Rules can have an `--end` date, be `pause`d/`resume`d, and `remove`d —
already-posted transactions always stay in the ledger, tagged `recurring`.

### Periods

Reports accept `--period` with: `ytd`, `all`, `this-month`, `last-month`,
`this-quarter`, `last-quarter`, `this-year`, `last-year`, `2026`, `2026-06`,
`2026-Q2` — or explicit `--from`/`--to` dates.

## Financial statements

```sh
beans report income --period 2026-Q1 --compare   # with prior-quarter deltas
beans report balance --date 2026-03-31
beans report cashflow --period 2026
```

The income statement shows each line as a % of total income (a common-size
view). The balance sheet is **classified** — assets and liabilities are split
into current and non-current sections (use `--flat` for a by-type-only listing).
It computes **retained earnings** on the fly —
cumulative net income that was never formally closed — so
Assets = Liabilities + Equity always holds. The cash flow statement uses the
direct method: every transaction that moves cash is classified by the
counter-account's activity, and the net change reconciles to beginning and
ending cash. Transactions that move no cash (e.g. groceries charged to a
credit card) correctly appear in the income statement but not the cash flow
statement until the card is paid.

Add `--json` to any report for machine-readable output:

```sh
beans report balance --json | jq .net_worth
```

## Budgeting

```sh
beans budget set Groceries 600                  # monthly by default
beans budget set Insurance 1200 --period yearly # normalized automatically
beans budget set Salary 6000                    # income targets work too
beans budget report                             # this month, budget vs actual
beans budget report --period 2026-Q1            # scaled to any period
beans budget list
beans budget remove Insurance
```

Budgets are normalized to the report period — a $600/month grocery budget shows
as $1,800 for a quarter and is pro-rated for partial periods.

## Reconciliation

Check the ledger against reality — your bank statement:

```sh
beans reconcile Checking --balance 4512.33   # where do we stand?
beans clear Checking 12 14 15                # mark matched entries cleared
beans clear Checking --through 2026-05-31    # or sweep a whole statement
beans reconcile Checking --balance 4512.33   # difference -> $0.00
```

The register shows a `*` next to cleared entries, and a nonzero difference
with no uncleared postings points straight at a missing or duplicated
transaction. Once a statement is reconciled, lock it:

```sh
beans period close 2026-05-31   # transactions on/before can't change
beans period status
beans period reopen
```

## Forecasting

```sh
beans forecast                          # 6 months from 6-month averages
beans forecast --months 12 --method trend --lookback 12
beans forecast --use-budget             # budgets drive accounts that have them
beans forecast --use-recurring          # scheduled txns at exact amounts/dates
```

Source priority per account: recurring schedule > budget > history.

## Goals

```sh
beans goal add house --account Savings --target 20000 --by 2028-01-01
beans goal add debt-free --account "Credit Card" --by 2027-06-01  # payoff
beans goal list    # progress bars + required monthly contribution
```

## Investments

Hold securities as FIFO lots with a price history; everything stays
balanced double-entry:

```sh
beans invest buy VTI 10 --price 280 --account Brokerage   # cash -> lots
beans price set VTI 295
beans invest list                       # qty, cost basis, market, unrealized
beans invest mark                       # post mark-to-market vs Income:Unrealized Gains
beans invest sell VTI 5 --price 300 --account Brokerage   # FIFO, books realized gain
```

`mark` adjusts each investment account's book value to market (assumes the
account is driven by `invest` commands), so the balance sheet reads like a
brokerage statement while Assets = Liabilities + Equity still holds.

## Loans

Attach amortization terms to a liability account and beans derives the payment
schedule, the split between principal and interest, and — for the balance
sheet — the **current portion of long-term debt** (principal scheduled to come
due within the next twelve months):

```sh
beans account add "Liabilities:Auto Loan" --type liability
beans loan add --account "Auto Loan" --principal 30000 --rate 6.25 --term 60 \
    --start 2026-01-01           # payment derived: 583.48/month
beans loan show "Auto Loan"      # the full amortization schedule
beans loan list                  # balance, current portion, non-current, rate
beans loan pay "Auto Loan"       # post one payment: principal + interest + cash out
```

Give `--payment` instead of `--term` to solve for the number of payments. On a
classified balance sheet the loan's *ledger* balance is split into current and
non-current buckets using the schedule; the balance itself always comes from the
ledger, so the two buckets sum to the real balance and the sheet still balances.
`beans loan pay` computes interest on the actual outstanding balance and posts it
to `Expenses:Interest`, so extra or missed payments stay accurate. (A variable
rate or extra principal makes only the *split point* approximate, never the
totals.)

## Multi-currency

beans keeps its books in one base currency — the "functional currency", as
a company would — so every transaction balances and every statement stays
consistent. Asset and liability accounts can be denominated in a foreign
currency; their postings carry both the base amount and the foreign amount:

```sh
beans account add "Assets:EUR Savings" --type asset --currency EUR
beans currency set EUR 1.0832            # base units per 1 EUR
beans transfer 1100 Checking "EUR Savings" --foreign 1000   # exact EUR
beans transfer 550 Checking "EUR Savings"    # EUR derived from the rate
```

The foreign amount comes from the latest rate on or before the transaction
date unless given explicitly (`--foreign` on spend/earn/transfer, or a
third value on `tx add --post ACCOUNT AMOUNT FOREIGN`). Then:

```sh
beans currency list      # foreign balances, rates, unrealized FX
beans currency rates     # rate history
beans currency revalue   # post FX gains/losses vs Income:FX Gains
```

`revalue` is the FX twin of `invest mark`: it trues each foreign account's
base value up to the current rate, so the balance sheet reflects today's
rates while remaining balanced.

## Export & backup

```sh
beans export json -o ledger.json   # everything: accounts, transactions,
                                   # budgets, rules, goals, lots, rates
beans export csv                   # one row per posting, for spreadsheets
beans -f new.db restore ledger.json  # rebuild a ledger from a JSON export
beans backup                       # timestamped copy next to the ledger
beans backup ~/backups/            # ...or wherever you keep them
```

Both exports are complete: voided transactions are included (the CSV carries
a `void` column, `1` for voided rows, alongside `cleared`), so your archived
data matches the ledger rather than silently dropping voids.

The JSON export round-trips: `beans -f new.db restore ledger.json` rebuilds a
fresh ledger from it — accounts, transactions (with void/cleared flags and
foreign amounts), budgets, rules, goals, lots, prices, and FX rates — by
replaying them through the normal write path, so every transaction is
re-validated to balance. It restores into an empty ledger only (it won't
overwrite an initialized one), which makes it handy for moving a ledger
between machines or restoring from a text backup.

Backups use SQLite's online backup API, so they're consistent even if
taken mid-write. Restore the binary snapshot by just pointing at it
(`beans -f backup.db`); use `restore` for the portable JSON form.

Projects monthly income, expenses, net savings, cash position, and net worth,
with a breakdown of which accounts drive the projection and from what basis
(history vs budget).

## Analysis

```sh
beans analyze --period ytd
beans networth --months 12     # month-end net worth trend with deltas
```

Reports the ratios you would compute for a company, adapted to a household:
savings rate (margin), working capital and the current & quick ratios (from the
current vs non-current split), liquidity runway in months of expenses,
debt-to-assets, debt-to-annual-income, and your top expense categories as a % of
income.

## Economic balance sheet

The accounting balance sheet shows what you own and owe today. The **economic
balance sheet** adds the present value of the future: your **human capital** (the
discounted value of income you expect to earn) as an asset, and your **future
consumption** (the discounted value of your lifetime spending) as a liability,
plus optional pensions, expected inheritances, and planned bequests.

```sh
beans economic bs --rate 3 --work-years 25 --live-years 40   # quick estimate
beans economic npv                                           # just the headline
beans economic create-template -o economic.md                # a config to edit
beans economic bs --file economic.md                         # a detailed plan
```

Human capital and future consumption are estimated from your recent income/expense
run-rate, projected over the horizons and discounted — or specified precisely in
a markdown config document, where each input can be a flat amount or a dated
cashflow stream (e.g. a salary that stops at retirement, a pension that starts
later, a one-off inheritance). The forward-looking inputs are assumptions and are
never posted to your ledger, so the result always reconciles with the accounting
balance sheet:

```
economic net worth = accounting net worth
                   + human capital + pensions/benefits
                   - future consumption - bequests/obligations
```

## CSV import

Import bank exports with a `date`, `description`, signed `amount`
(positive = money in), and optional `category` column:

```sh
beans import bank.csv --account Checking --category Expenses:Other --dry-run
beans import bank.csv --account Checking --category Expenses:Other
```

Column names are remappable (`--date-col`, `--amount-col`, `--desc-col`,
`--category-col`) to fit whatever your bank produces.

Re-importing overlapping exports is safe: deduplication is count-aware, so
re-importing the same file is a no-op, but two genuinely distinct rows that
share a date and amount (say, two identical coffees on one day) both import
rather than collapsing into one (disable dedupe entirely with `--no-dedupe`).
Rows without a category are routed by saved rules before falling back to
`--category`:

```sh
beans rule add "WHOLE FOODS" Groceries
beans rule add "SHELL" Transportation
beans rule list
```

## Shell completions

```sh
beans completions bash > ~/.local/share/bash-completion/completions/beans
beans completions zsh  > ~/.zfunc/_beans    # with fpath+=(~/.zfunc)
```

Completes commands, subcommands, and account names (via
`beans account list --names`).

## Customization

- `beans -f path/to/ledger.db …` or `export BEANS_LEDGER=…` — keep multiple
  ledgers, store them in a synced folder, anything.
- `beans init --currency EUR` — any ISO code; symbol and decimal places adapt.
- `beans config set default_account Savings` — default cash side for
  `spend`/`earn`.
- `beans account modify … --cashflow …` — reshape cash flow classification.
- `--json` everywhere — pipe into `jq`, spreadsheets, or your own tooling.

## Development

```sh
pip install -e .[dev]
pytest
```

The codebase is small and orthogonal: `ledger.py` (SQLite double-entry core),
`reports.py` (statements), `budget.py`, `forecast.py`, `analysis.py`,
`loans.py` (amortization), `economic.py` (economic balance sheet / NPV),
`importer.py`, `cli.py`. All amounts are stored as
integers in minor units;
postings are debit-positive/credit-negative and must sum to zero.

## Versioning & releases

`beans` uses [semantic versioning](https://semver.org/) with `vX.X.X` tags.
The version lives in a single place — `beans/__init__.py` — and
`pyproject.toml` reads it dynamically, so there's nothing to keep in sync by
hand.

Check the installed version any time:

```sh
beans --version
```

**Cutting a release** is a two-step, tag-driven flow (see the
[manual](docs/MANUAL.md#releasing--publishing) for full detail):

```sh
# 1. Bump the version, commit, and create an annotated vX.X.X tag.
scripts/bump_version.py v1.2.3

# 2. Push the commit and the tag. Pushing the tag is what triggers publishing.
git push origin HEAD
git push origin v1.2.3
```

Pushing a `v*` tag runs the [release workflow](.github/workflows/release.yml),
which:

- builds the sdist and wheel and verifies the tag matches the package version,
- creates a **GitHub Release** with an auto-generated **"What's Changed"**
  section (categorised via [`.github/release.yml`](.github/release.yml)), and
- publishes the distributions **directly to [PyPI](https://pypi.org/project/beans-ledger/)**
  (as `beans-ledger`) using [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC —
  no API tokens stored in the repo).

`scripts/bump_version.py --show` prints the current version, and
`--push` will push the commit and tag for you in one step.

## Bugs & feature requests

Found a bug or have an idea for a new feature? Email roger@turningbull.com.
