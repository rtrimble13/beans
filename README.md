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
- **Ease of use** — `spend` / `earn` / `transfer` shortcuts, fuzzy account
  matching (`groceries` → `Expenses:Food:Groceries`), CSV import, and `--json`
  output on every report for scripting.
- **No dependencies** — pure Python standard library; data lives in a single
  SQLite file you own.

## Installation

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
```

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
beans register Checking --period ytd   # running-balance view of one account
beans balances          # everything, grouped by type
beans report trial      # the accountant's sanity check
```

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
view). The balance sheet computes **retained earnings** on the fly —
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

## Forecasting

```sh
beans forecast                          # 6 months from 6-month averages
beans forecast --months 12 --method trend --lookback 12
beans forecast --use-budget             # budgets drive accounts that have them
```

Projects monthly income, expenses, net savings, cash position, and net worth,
with a breakdown of which accounts drive the projection and from what basis
(history vs budget).

## Analysis

```sh
beans analyze --period ytd
beans networth --months 12     # month-end net worth trend with deltas
```

Reports the ratios you would compute for a company, adapted to a household:
savings rate (margin), liquidity runway in months of expenses, debt-to-assets,
debt-to-annual-income, and your top expense categories as a % of income.

## CSV import

Import bank exports with a `date`, `description`, signed `amount`
(positive = money in), and optional `category` column:

```sh
beans import bank.csv --account Checking --category Expenses:Other --dry-run
beans import bank.csv --account Checking --category Expenses:Other
```

Column names are remappable (`--date-col`, `--amount-col`, `--desc-col`,
`--category-col`) to fit whatever your bank produces.

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
`importer.py`, `cli.py`. All amounts are stored as integers in minor units;
postings are debit-positive/credit-negative and must sum to zero.
