# beans — the complete manual

This is the full command reference and instruction manual for `beans`, a
pure-stdlib, double-entry accounting tool for personal finance. It documents
every command, every flag, and the defaults and validation behind them, plus
best practices for using each one well.

If you're new to `beans`, start with the [README](../README.md) for a quick
tour or the [vignettes](vignettes/README.md) for guided, task-oriented
walkthroughs. This manual is the reference to come back to once you know the
shape of the tool and want the details on a specific command.

## Contents

1. [Global options and conventions](#global-options-and-conventions)
2. [`init` — create a ledger](#init--create-a-ledger)
3. [`account` — chart of accounts](#account--chart-of-accounts)
4. [`tx` — transactions](#tx--transactions)
5. [`spend` / `earn` / `transfer` — shortcuts](#spend--earn--transfer--shortcuts)
6. [`register` — account history](#register--account-history)
7. [`balances` — all balances](#balances--all-balances)
8. [`report` — financial statements](#report--financial-statements)
9. [`recur` — recurring transactions](#recur--recurring-transactions)
10. [`networth` — net worth trend](#networth--net-worth-trend)
11. [`budget` — budgets and variance](#budget--budgets-and-variance)
12. [`forecast` — projections](#forecast--projections)
13. [`analyze` — ratios and analysis](#analyze--ratios-and-analysis)
14. [`import` — CSV import](#import--csv-import)
15. [`rule` — auto-categorization rules](#rule--auto-categorization-rules)
16. [`config` — ledger configuration](#config--ledger-configuration)
17. [`status` — dashboard](#status--dashboard)
18. [`undo` — undo the last transaction](#undo--undo-the-last-transaction)
19. [`search` — full-text search](#search--full-text-search)
20. [`clear` / `reconcile` — bank reconciliation](#clear--reconcile--bank-reconciliation)
21. [`period` — closing the books](#period--closing-the-books)
22. [`goal` — savings and payoff goals](#goal--savings-and-payoff-goals)
23. [`invest` / `price` — investments](#invest--price--investments)
24. [`currency` — multi-currency and FX](#currency--multi-currency-and-fx)
25. [`export` / `backup` / `restore`](#export--backup--restore)
26. [`completions` — shell completions](#completions--shell-completions)
27. [General best practices](#general-best-practices)

---

## Global options and conventions

These apply to every `beans` invocation, before the subcommand:

| Option | Description |
|---|---|
| `-f PATH`, `--file PATH` | Ledger file to operate on. Overrides `$BEANS_LEDGER`. |
| `--version` | Print the installed version and exit. |
| `-h`, `--help` | Show help. Also works on any subcommand: `beans <command> -h`. |

**Ledger location.** If `-f`/`--file` is not given, `beans` uses
`$BEANS_LEDGER` if set, otherwise `~/.beans/ledger.db`. Running `beans`
with no subcommand at all is the same as `beans status`.

**Amounts.** Any argument documented as an amount (e.g. `AMOUNT`, `PRICE`,
`BALANCE`) is parsed in the ledger's currency using its configured decimal
places (2 for USD, 0 for currencies like JPY, etc.) — write plain decimals
like `1800` or `450.25`, no currency symbols or thousands separators.

**Dates.** All `DATE` arguments are `YYYY-MM-DD`. Most commands default to
today if a date is omitted.

**Account names.** Anywhere an account is expected, `beans` uses fuzzy
matching (`find_account`), tried in this order, case-insensitively:

1. Exact full name (`Expenses:Food:Groceries`)
2. Unique leaf match (`groceries` → the one account whose last segment is
   "groceries")
3. Unique substring match (`food` → the one account containing "food"
   anywhere in its name)

If more than one account matches at a given stage, `beans` reports the
ambiguous candidates and asks you to be more specific rather than guessing.
If nothing matches, it tells you to check `beans account list`.

**Periods.** Commands that accept `-p`/`--period` (income statement, cash
flow, budget report, analyze, register, tx list) understand:

- `ytd` (year-to-date)
- `all` (every transaction in the ledger)
- `this-month`, `last-month`
- `this-quarter`, `last-quarter`
- `this-year`, `last-year`
- `YYYY` (a specific year, e.g. `2026`)
- `YYYY-MM` (a specific month, e.g. `2026-06`)
- `YYYY-QN` (a specific quarter, e.g. `2026-Q2`)

The default when `--period`/`--from`/`--to` are all omitted varies by
command: `report income`, `report cashflow`, and `analyze` default to
`ytd`; `tx list` and `register` default to `all`; `budget report` defaults
to `this-month`.

`--from DATE` and `--to DATE` give an explicit range and override
`--period` when present; `--to` alone defaults its end to today.

**JSON output.** Any command that supports `--json` prints a single
machine-readable JSON document instead of formatted text — pipe it to `jq`
or your own scripts. Prefer `--json` over parsing human-readable tables in
automation; the human format is not a stable contract, the JSON schema is.

**Exit codes.** `beans` exits `0` on success and non-zero on error, with the
error message on stderr — safe to check in scripts (`beans tx add ... || echo
failed`).

**Recurring-rule reminders.** After most commands, if you have recurring
rules that are due, `beans` prints a reminder to stderr (this is suppressed
after `init`, `recur`, `status`, and `completions`, since those already
surface that information or aren't the right moment for it).

### Best practices — global

- Keep `$BEANS_LEDGER` set in your shell profile if you use a non-default
  location, so you never have to remember `-f` for routine commands.
- Get comfortable with fuzzy account matching for everyday entry
  (`spend`/`earn`), but use full account paths in scripts, recurring rules,
  and anything you'll re-run later — substring matches can become ambiguous
  as your chart of accounts grows.
- Reach for `--json` the moment you're piping `beans` output into another
  program; don't scrape the formatted tables.

---

## `init` — create a ledger

```
beans init [--currency CODE] [--bare]
```

| Flag | Description |
|---|---|
| `--currency CODE` | ISO currency code for the ledger's base (functional) currency. Default `USD`. |
| `--bare` | Skip the starter chart of accounts; start with nothing. |

Creates a new SQLite ledger file at the resolved path (see [global
conventions](#global-options-and-conventions)). Fails if a ledger already
exists there.

Unless `--bare` is given, `init` populates a starter chart of ~23 accounts
covering the common asset, liability, equity, income, and expense
categories a household needs (checking/savings, credit cards, salary,
housing, food, transportation, etc.) — see `beans account list` right after
`init` to see the full starter set.

### Best practices

- Set `--currency` at `init` time; changing a ledger's base currency later
  isn't supported, so get it right before you start recording transactions.
- Use the starter chart unless you already know your account structure —
  it's cheap to rename (`account modify --rename`) or add to
  (`account add`), and having sensible defaults for the cash-flow
  classification of common accounts (checking/savings marked `--cash`) saves
  you having to reason about it manually later.
- If you manage multiple books (e.g. personal + a side business), use
  separate ledger files (`-f` or `$BEANS_LEDGER`) rather than one chart of
  accounts with a naming convention — it keeps each ledger's trial balance
  and statements meaningful on their own.

---

## `account` — chart of accounts

### `account add`

```
beans account add NAME --type TYPE [--cash] [--cashflow ACTIVITY]
                        [--currency CODE] [--noncurrent] [--desc TEXT]
```

| Argument/Flag | Description |
|---|---|
| `NAME` | Hierarchical account name, e.g. `Expenses:Pets`. Segments are separated by `:`. |
| `-t, --type TYPE` (required) | One of `asset`, `liability`, `equity`, `income`, `expense`. |
| `--cash` | Mark as cash/cash-equivalent (assets only). Drives the statement of cash flows. |
| `--cashflow {operating,investing,financing}` | Override which cash-flow activity this account's flows are classified under. |
| `--currency CODE` | Denominate the account in a foreign ISO currency (assets and liabilities only), e.g. `EUR`. |
| `--noncurrent` | Classify the account as non-current (long-term) on the balance sheet. Assets and liabilities only; everything defaults to `current`. |
| `--desc TEXT` | Free-text description. |

### `account list`

```
beans account list [--type TYPE] [--all] [--names] [--json]
```

| Flag | Description |
|---|---|
| `-t, --type TYPE` | Filter to one account type. |
| `--all` | Include closed accounts (omitted by default). |
| `--names` | Print bare account names only, one per line — used internally for shell completion, also handy for scripting. |
| `--json` | Machine-readable output. |

Lists accounts with current balances.

### `account close`

```
beans account close NAME
```

Closes an account. Requires a zero balance — `beans` refuses to close an
account you still have a balance in, so you can't accidentally lose track
of money. Closed accounts stay in history but drop out of `account list`
and balance-affecting commands unless `--all` is given.

### `account modify`

```
beans account modify NAME [--rename NEW_NAME] [--cash | --no-cash]
                          [--current | --noncurrent] [--cashflow ACTIVITY]
                          [--desc TEXT]
```

| Flag | Description |
|---|---|
| `--rename NEW_NAME` | Rename the account (all history follows). |
| `--cash` / `--no-cash` | Toggle the cash-equivalent flag (mutually exclusive). |
| `--current` / `--noncurrent` | Set the balance-sheet liquidity class (mutually exclusive; assets and liabilities only). |
| `--cashflow {operating,investing,financing}` | Reclassify the account's cash-flow activity. |
| `--desc TEXT` | Replace the description. |

### Best practices

- Default cash-flow classification follows corporate convention by account
  type: income/expense → operating, asset → investing, liability/equity →
  financing — this is the type's default regardless of the `--cash` flag.
  In practice this only matters for non-cash assets (investments), since
  accounts marked `--cash` are excluded from the cash-flow statement's
  bucketing entirely (they're the cash side the statement explains, not a
  counterparty). Only set `--cashflow` explicitly on a non-cash account
  that genuinely doesn't fit its type's default (e.g. an
  `Expenses:...` account you want bucketed as investing instead of
  operating).
- Mark every checking/savings/wallet account `--cash` at creation time —
  the cash flow statement is only as good as this flag. If a "reconciles
  the change in cash" figure on `report cashflow` looks wrong, check this
  flag first.
- Prefer a deep, descriptive hierarchy (`Expenses:Food:Groceries` over a
  flat `Groceries`) — it makes fuzzy matching more powerful (you can match
  on `food` for the whole category or `groceries` for the leaf) and makes
  reports easier to scan.
- Rename with `account modify --rename` instead of closing and re-adding —
  renaming preserves all transaction history under the new name; closing
  and re-adding fragments your history across two accounts.
- Never delete a mistakenly-created account by any means other than
  `close` (there is no destructive delete) — this guarantees the ledger's
  history is always intact and auditable.

---

## `tx` — transactions

Transactions are the core primitive: a list of postings that must sum to
zero (debits positive, credits negative).

### `tx add`

```
beans tx add [--date DATE] [--desc TEXT] [--payee TEXT] [--tag TAG ...]
             --post ACCOUNT [AMOUNT] [FOREIGN] [--post ...]
             [--like ID]
```

| Flag | Description |
|---|---|
| `-d, --date DATE` | Transaction date. Default: today. |
| `-m, --desc TEXT` | Description. |
| `--payee TEXT` | Payee/counterparty name. |
| `--tag TAG` | Repeatable; attach one or more tags. |
| `--post ACCOUNT [AMOUNT] [FOREIGN]` | One posting; repeatable, at least two required. Positive amount = debit, negative = credit. Omit the amount on **one** posting to have it auto-balance to whatever makes the transaction sum to zero. A third value gives the exact foreign-currency amount when that account is denominated in a foreign currency. |
| `--like ID` | Clone the postings and description from an existing transaction by id, then override any of `--date`/`--desc`/`--payee` as needed. |

Example (a paycheck with a 401(k) split):

```sh
beans tx add --desc "Paycheck" --date 2026-02-15 \
    --post Assets:Checking 4000 \
    --post Assets:Investments:Retirement 1000 \
    --post Income:Salary              # omitted amount auto-balances to -5000
```

### `tx list`

```
beans tx list [--period SPEC | --from DATE --to DATE] [--account ACCOUNT]
              [--limit N] [--all] [--json]
```

| Flag | Description |
|---|---|
| `--period`, `--from`/`--to` | Standard period filter (see [Periods](#global-options-and-conventions)). |
| `-a, --account ACCOUNT` | Only transactions with a posting to this account. |
| `-n, --limit N` | Show only the last N transactions. |
| `--all` | Include voided transactions (omitted by default). |
| `--json` | Machine-readable output. |

### `tx show`

```
beans tx show ID [--json]
```

Shows one transaction's full detail — date, description, payee, tags, and
every posting.

### `tx void`

```
beans tx void ID
```

Voids a transaction. Voiding **keeps the audit trail** — nothing is
deleted; the transaction is marked voided and excluded from balances and
reports (unless `--all`/`--json` explicitly include it). This is the only
supported way to "undo" an entry other than the specific `beans undo`
shortcut for the most recent transaction.

### Best practices

- Use the general `tx add --post ...` form whenever a transaction has more
  than two legs (split paychecks, transactions that touch three or more
  accounts). For simple two-leg entries, prefer `spend`/`earn`/`transfer` —
  they're shorter and default the cash side for you.
- Always omit the amount on exactly one posting rather than computing the
  balancing figure yourself — it's one less arithmetic mistake, and it's a
  built-in sanity check: if your entered amounts don't leave a sensible
  remainder, you'll immediately notice.
- Use `--tag` for cross-cutting labels that don't belong in your chart of
  accounts (`--tag reimbursable`, `--tag trip:hawaii-2026`) rather than
  creating one-off accounts for them.
- Use `tx void`, not deletion, to correct history — and reach for `--like`
  when you need to re-enter a corrected version of a voided transaction, so
  the new entry mirrors the old one exactly except for what changed.
- Use `tx list --account X --limit N` as your day-to-day "did this post
  correctly" check right after entering transactions for an account.

---

## `spend` / `earn` / `transfer` — shortcuts

Each of these is a balanced two-leg entry with the common case's ergonomics
built in — a shorter alternative to `tx add` for the vast majority of
day-to-day entries.

### `spend`

```
beans spend AMOUNT CATEGORY [--from ACCOUNT] [--desc TEXT] [--payee TEXT]
            [--date DATE] [--foreign AMOUNT]
```

| Argument/Flag | Description |
|---|---|
| `AMOUNT` | Amount spent. |
| `CATEGORY` | Expense account (fuzzy-matched). |
| `--from ACCOUNT` | Paying account. Default: `config default_account`, or `Checking`. |
| `-m, --desc TEXT` | Description. |
| `--payee TEXT` | Payee. |
| `-d, --date DATE` | Date. Default: today. |
| `--foreign AMOUNT` | Exact foreign amount when one leg is a foreign-currency account. |

```sh
beans spend 54.20 Dining --from "Credit Card" -m "Pizza night"
```

If `Dining` is budgeted, `spend` immediately prints feedback like
`Groceries: 92% of June budget used`, so you see budget impact the moment
you record the expense.

### `earn`

```
beans earn AMOUNT SOURCE [--to ACCOUNT] [--desc TEXT] [--date DATE]
           [--foreign AMOUNT]
```

| Argument/Flag | Description |
|---|---|
| `AMOUNT` | Amount earned. |
| `SOURCE` | Income account (fuzzy-matched). |
| `--to ACCOUNT` | Receiving account. Default: `config default_account`, or `Checking`. |
| `-m, --desc TEXT` | Description. |
| `-d, --date DATE` | Date. Default: today. |
| `--foreign AMOUNT` | Exact foreign amount when one leg is a foreign-currency account. |

```sh
beans earn 120 Interest --to Savings
```

### `transfer`

```
beans transfer AMOUNT FROM TO [--desc TEXT] [--date DATE] [--foreign AMOUNT]
```

| Argument/Flag | Description |
|---|---|
| `AMOUNT` | Amount moved. |
| `FROM` | Source account (fuzzy-matched). |
| `TO` | Destination account (fuzzy-matched). |
| `-m, --desc TEXT` | Description. |
| `-d, --date DATE` | Date. Default: today. |
| `--foreign AMOUNT` | Exact foreign amount when one leg is a foreign-currency account, e.g. EUR received. |

```sh
beans transfer 1000 Checking Savings
```

### Best practices

- Set `beans config set default_account Savings` (or whichever account you
  pay from most) once, up front, so you can drop `--from`/`--to` from most
  `spend`/`earn` calls.
- Use `--foreign` whenever you know the exact foreign-currency amount from
  a receipt or statement (e.g. `beans transfer 1100 Checking "EUR Savings"
  --foreign 1000`) instead of letting `beans` derive it from the latest
  recorded rate — the derived amount is only as accurate as your last
  `currency set`.
- Let the automatic budget feedback from `spend` be your primary
  early-warning system; if you're consistently surprised by
  `budget report` at month end, you're not looking at the `spend` feedback
  closely enough.
- Reserve `transfer` for moving money between your own accounts; use
  `spend`/`earn` for anything that crosses into income or expense — this
  keeps the income statement accurate (transfers are correctly invisible to
  it).

---

## `register` — account history

```
beans register ACCOUNT [--period SPEC | --from DATE --to DATE] [--json]
```

Shows one account's transaction history with a running balance — the
classic checkbook register view. Accepts the standard period filters.

### Best practices

- Use `register` (not `tx list --account`) when you specifically want the
  running balance column — it's the fastest way to spot exactly where a
  reconciliation discrepancy first appears.
- Run `beans register Checking --period this-month` right before
  `reconcile` as a final visual check before comparing to your statement.

---

## `balances` — all balances

```
beans balances [--date DATE] [--json]
```

| Flag | Description |
|---|---|
| `-d, --date DATE` | As-of date. Default: today. |
| `--json` | Machine-readable output. |

All account balances grouped by type (assets, liabilities, equity, income,
expense) as of a point in time.

### Best practices

- Use `--date` to answer "what did I have on hand as of [date]" questions
  (e.g. reconstructing net worth on a specific day for taxes) rather than
  computing it by hand from `register`.

---

## `report` — financial statements

```
beans report {income|balance|cashflow|trial} ...
```

### `report income` (alias `is`)

```
beans report income [--period SPEC | --from/--to] [--compare] [--json]
```

The income statement, with each line shown as a percent of total income
(common-size view). `--compare` adds a column comparing against the prior
period of equal length.

### `report balance` (alias `bs`)

```
beans report balance [--date DATE] [--flat] [--json]
```

The balance sheet as of a date (default: today). Computes **retained
earnings** on the fly — cumulative net income never formally closed — so
Assets = Liabilities + Equity always holds without requiring you to
manually close the books each period.

By default the sheet is **classified**: assets and liabilities are each split
into **current** and **non-current** sections. Assets follow their liquidity
tag (`account add/modify --current/--noncurrent`); a liability with an attached
loan (see `loan add`) is split by its amortization schedule — the principal due
within twelve months is current, the rest non-current — and other liabilities
follow their tag. The split is applied to the true ledger balance, so the two
buckets always sum to the type total. Pass `--flat` for the old by-type-only
listing. The `--json` output always carries both the flat totals (`assets`,
`liabilities`, …) and the split keys (`assets_current`, `liabilities_noncurrent`,
…).

### `report cashflow` (alias `cf`)

```
beans report cashflow [--period SPEC | --from/--to] [--json]
```

The statement of cash flows, direct method, classified into operating,
investing, and financing activities based on each account's cash-flow
category. The net change reconciles to beginning and ending cash.
Non-cash transactions (e.g. groceries charged to a credit card) correctly
appear on the income statement but not here until the card is paid.

### `report trial` (alias `tb`)

```
beans report trial [--date DATE] [--json]
```

The trial balance — the accountant's sanity check that total debits equal
total credits across every account. Aliased as `tb`.

### Best practices

- Run `report trial` after any bulk operation (a large CSV import, a
  `restore`) as a fast integrity check before trusting the other
  statements.
- Use `--compare` on the income statement routinely, not just when
  something looks off — trend visibility is most useful before a problem
  is big enough to notice by eye.
- Get your cash/cashflow account flags right (see `account add --cash`)
  before relying on `report cashflow` — it's the statement most sensitive
  to misconfigured accounts.
- Use the short aliases (`is`, `bs`, `cf`, `tb`) once they're muscle
  memory; they're identical in behavior to the full names.

---

## `recur` — recurring transactions

Define a bill, paycheck, or subscription once; post it on demand or ahead
of time.

### `recur add`

```
beans recur add NAME --freq FREQ [--start DATE] [--end DATE]
                [--desc TEXT] [--payee TEXT] [--tag TAG ...]
                --post ACCOUNT [AMOUNT] [--post ...]
```

| Flag | Description |
|---|---|
| `NAME` | Unique rule name, e.g. `rent`. |
| `-F, --freq FREQ` (required) | One of `daily`, `weekly`, `biweekly`, `monthly`, `quarterly`, `yearly`. |
| `--start DATE` | First occurrence. Default: today. |
| `--end DATE` | Last possible occurrence (optional — open-ended if omitted). |
| `-m, --desc TEXT` | Description. Default: the rule name. |
| `--payee TEXT` | Payee. |
| `--tag TAG` | Repeatable; instances also automatically get the `recurring` tag. |
| `--post ACCOUNT [AMOUNT]` | Posting template, repeatable, same syntax as `tx add --post`. |

```sh
beans recur add rent --freq monthly --start 2026-07-01 \
    --post Expenses:Housing:Rent 1800 --post Assets:Checking
```

Monthly-style rules anchor to the start date's day-of-month and clamp to
short months (a rule started Jan 31 posts Feb 28, then Mar 31).

### `recur list`

```
beans recur list [--json]
```

Lists all rules and whether each is currently due.

### `recur show`

```
beans recur show NAME
```

Full detail on one rule.

### `recur run`

```
beans recur run [--to DATE] [--dry-run] [--json]
```

| Flag | Description |
|---|---|
| `--to DATE` | Post everything due through DATE. Default: today. |
| `--dry-run` | Preview without writing. |
| `--json` | Machine-readable output. |

Posts all due occurrences. **Idempotent** — safe to run as often as you
like; already-posted occurrences are never duplicated. Use `--to` with a
future date to post ahead for planning purposes.

### `recur pause` / `recur resume` / `recur remove`

```
beans recur pause NAME
beans recur resume NAME
beans recur remove NAME
```

`pause` suspends a rule (it stops appearing as due); `resume` reactivates
it; `remove` deletes the rule definition. Already-posted transactions
always remain in the ledger (tagged `recurring`), regardless of the rule's
current state.

### Best practices

- Always `recur run --dry-run` before the real run when you're not certain
  what's due, especially the first time you set up a new rule — it's free
  insurance against a wrong amount or account posting for real.
- Run `recur run` (no `--to`) as a habit at the start of every `beans`
  session — since it's idempotent, there's no cost to running it more
  often than strictly necessary, and it keeps your dashboard/reports
  current.
- Use `recur run --to <future-date>` combined with `forecast
  --use-recurring` to sanity-check a plan (e.g. "will I have enough cash
  through the end of the quarter") without permanently posting anything —
  do the projection first, then decide whether to actually run ahead.
- Prefer `pause`/`resume` over `remove` for a bill that's temporarily
  suspended (e.g. a subscription on hold) — `remove` is meant for a rule
  that's gone for good; both preserve history either way, but `pause`
  keeps the rule ready to resume with its original schedule intact.
- Set `--end` on any rule with a known final date (a loan payoff date, a
  lease end) so it naturally stops nagging you as due once it's over,
  instead of relying on remembering to `remove` it.

---

## `networth` — net worth trend

```
beans networth [--months N] [--json]
```

| Flag | Description |
|---|---|
| `-n, --months N` | Months of history to show. Default: 12. |
| `--json` | Machine-readable output. |

Month-end net worth trend with deltas between months.

### Best practices

- Check `networth` monthly rather than daily — net worth is a lagging,
  low-frequency indicator; daily checking mostly just shows market noise if
  you hold investments.
- Widen `--months` when a single number looks off, to see whether it's a
  one-month blip or the start of a trend.

---

## `budget` — budgets and variance

### `budget set`

```
beans budget set ACCOUNT AMOUNT [--period {weekly,monthly,quarterly,yearly}]
```

Sets or updates a budget for an account (expense **or** income — income
targets work too, e.g. a minimum salary goal). `--period` defaults to
`monthly`; amounts are automatically normalized to whatever period a report
is run over (a `$600`/month grocery budget shows as `$1,800` for a quarter,
and is pro-rated for partial periods).

```sh
beans budget set Groceries 600
beans budget set Insurance 1200 --period yearly
```

### `budget list`

```
beans budget list [--json]
```

### `budget remove`

```
beans budget remove ACCOUNT
```

### `budget report`

```
beans budget report [--period SPEC | --from/--to] [--json]
```

Budget vs. actual for a period (default: this month), scaled to whatever
period you ask for.

### Best practices

- Set budgets at whatever cadence a bill or category naturally recurs at
  (`--period yearly` for annual insurance, `--period weekly` for a
  discretionary allowance) rather than forcing everything to monthly and
  doing the math yourself — normalization handles the conversion for any
  report period.
- Budget income targets, not just expenses, when you want `budget report`
  to flag a shortfall on the income side too (e.g. a minimum freelance
  revenue goal).
- Let `spend`'s inline budget feedback be your day-to-day signal; use
  `budget report --period <quarter/year>` periodically to see the
  cumulative picture, since normalization means a category that looks fine
  week to week can still drift over a quarter.

---

## `forecast` — projections

```
beans forecast [--months N] [--method {average,trend}] [--lookback N]
               [--use-budget] [--use-recurring] [--json]
```

| Flag | Description |
|---|---|
| `-n, --months N` | Months to project. Default: 6. |
| `--method {average,trend}` | Projection method. Default: `average`. |
| `--lookback N` | Months of history to learn from. Default: 6. |
| `--use-budget` | Use budgeted amounts for accounts that have a budget. |
| `--use-recurring` | Project scheduled recurring transactions at their exact amounts and dates. Takes priority over budgets and history for those accounts. |
| `--json` | Machine-readable output. |

Projects income, expenses, net savings, cash position, and net worth
forward, with a breakdown of which accounts drive the projection and
whether each is driven by history, budget, or a recurring schedule.
**Source priority per account: recurring schedule > budget > history.**

### Best practices

- Use `--method trend` instead of the `average` default when your spending
  or income has a clear directional trend (a raise that just took effect, a
  bill that's growing) — `average` will lag a real trend change for as long
  as `--lookback` months.
- Layer `--use-recurring` and `--use-budget` together for your most
  accurate forecast: recurring rules nail the accounts you've scheduled
  exactly, budgets cover the categories you've planned but not automated,
  and history fills in the rest.
- Increase `--lookback` for a noisy or seasonal category (e.g. utilities,
  which vary by season) so the average smooths across a full cycle rather
  than a few atypical months.

---

## `analyze` — ratios and analysis

```
beans analyze [--period SPEC | --from/--to] [--json]
```

Financial ratios and expense breakdown for a household, computed the way
you'd compute them for a company: savings rate (margin), **working capital**
(current assets − current liabilities) with the **current ratio** (current
assets / current liabilities) and **quick ratio** (cash / current liabilities),
liquidity runway in months of expenses, debt-to-assets, debt-to-annual-income,
and top expense categories as a percent of income. The current/quick ratios use
the same current vs non-current split as the classified balance sheet, so they
sharpen as you tag long-term accounts and attach loans.

### Best practices

- Run `analyze --period ytd` (the default) as your regular financial
  check-in rather than trying to eyeball these ratios from the raw
  statements — they're already computed and comparable period to period.
- Compare `analyze` across `--period` values (e.g. this quarter vs. last
  quarter) to see whether your savings rate and runway are improving or
  eroding, not just their current absolute value.

---

## `import` — CSV import

```
beans import CSVFILE --account ACCOUNT [--category ACCOUNT]
             [--date-col NAME] [--desc-col NAME] [--amount-col NAME]
             [--category-col NAME] [--dry-run] [--no-dedupe]
```

| Flag | Description |
|---|---|
| `CSVFILE` | Path to the CSV file. |
| `-a, --account ACCOUNT` (required) | Target account being imported into (e.g. the bank account you exported). |
| `--category ACCOUNT` | Fallback counter-account for rows with no category and no matching rule. |
| `--date-col NAME` | Date column name. Default: `date`. |
| `--desc-col NAME` | Description column name. Default: `description`. |
| `--amount-col NAME` | Signed amount column; positive = money in. Default: `amount`. |
| `--category-col NAME` | Category column name. Default: `category`. |
| `--dry-run` | Parse and report without writing anything. |
| `--no-dedupe` | Import rows even if a matching transaction (same date, account, amount) already exists. |

Rows without a category are routed through saved [import rules](#rule--auto-categorization-rules)
before falling back to `--category`.

Deduplication is count-aware: re-importing the same file is a no-op, but
two genuinely distinct rows sharing a date and amount (e.g. two identical
coffee purchases in one day) both import rather than collapsing into one.

### Best practices

- Always `--dry-run` a CSV the first time you see its shape from a given
  bank, to check column mapping before writing anything.
- Set up [`rule add`](#rule--auto-categorization-rules) entries for
  recurring merchants before your first real import of a statement — rules
  apply automatically on every future import, so the upfront cost pays off
  immediately at the next statement.
- Leave deduplication on (the default) for routine re-imports of
  overlapping statement periods; only reach for `--no-dedupe` when you
  specifically know you're re-importing something you intentionally voided
  or need duplicated.
- Remap columns (`--date-col`, `--amount-col`, etc.) rather than
  hand-editing your bank's export to match `beans`'s defaults — it's less
  error-prone and repeatable for every future export from that bank.

---

## `rule` — auto-categorization rules

### `rule add`

```
beans rule add PATTERN ACCOUNT
```

Routes future CSV-imported rows whose description contains `PATTERN`
(case-insensitive substring match) to `ACCOUNT`.

```sh
beans rule add "WHOLE FOODS" Groceries
beans rule add "SHELL" Transportation
```

### `rule list`

```
beans rule list [--json]
```

### `rule remove`

```
beans rule remove PATTERN
```

### Best practices

- Add a rule the first time you see an uncategorized merchant in an
  import, rather than fixing the same merchant by hand on every future
  statement.
- Keep patterns as specific as you need to avoid false matches (e.g.
  `"SHELL OIL"` instead of `"SHELL"` if you also shop at a store with
  "shell" in its name), but no more specific than that — over-specific
  patterns break the moment a merchant's statement descriptor changes
  slightly.

---

## `config` — ledger configuration

```
beans config get KEY
beans config set KEY VALUE
beans config list
```

Gets, sets, or lists ledger-level configuration stored in the ledger file
itself (not global — it travels with the ledger). Known keys include
`currency`, `decimals`, `default_account` (used by `spend`/`earn`/`invest
buy`/`invest sell` when `--from`/`--to`/`--account` aren't given), and
`created`.

### Best practices

- Set `default_account` right after `init` if your primary cash account
  isn't named `Checking` — it's the single setting that most reduces
  typing on everyday `spend`/`earn` calls.
- Use `config list` when picking up a ledger you didn't set up yourself
  (e.g. after a `restore`) to quickly see its currency and default account
  before entering transactions.

---

## `status` — dashboard

```
beans status [--json]
```

The default command — running bare `beans` is equivalent to `beans
status`. One-screen dashboard: cash position, net worth, month-to-date vs.
budget, due recurring rules, and goal progress.

### Best practices

- Make `beans` (bare) your daily-driver entry point — it's designed to be
  the first thing you run in a session, surfacing what's due or off-track
  before you go looking for it in individual reports.

---

## `undo` — undo the last transaction

```
beans undo
```

Voids the most recent transaction in the ledger — typo insurance for the
entry you just made. Equivalent to `tx void` on the latest transaction id,
but you don't need to know or look up the id.

### Best practices

- Use `undo` immediately after a `spend`/`earn`/`transfer`/`tx add` you
  realize was wrong, before entering anything else — it only ever targets
  the single most recent transaction, so acting immediately is what makes
  it useful.
- For anything other than the very last entry, use `tx show ID` +
  `tx void ID` instead — `undo` won't reach further back.

---

## `search` — full-text search

```
beans search QUERY [--limit N] [--json]
```

| Flag | Description |
|---|---|
| `QUERY` | Text to search for. |
| `-n, --limit N` | Show only the last N matches. |
| `--json` | Machine-readable output. |

Full-text search over transaction descriptions, payees, and tags.

```sh
beans search "whole foods"
```

### Best practices

- Reach for `search` instead of scrolling `tx list` output when you
  remember roughly what a transaction was about but not when it happened.
- Search by payee or a tag (e.g. `beans search reimbursable`) to
  reconstruct an ad hoc group of transactions that spans account and
  category boundaries.

---

## `clear` / `reconcile` — bank reconciliation

### `clear`

```
beans clear ACCOUNT [ID ...] [--through DATE] [--undo]
```

| Argument/Flag | Description |
|---|---|
| `ACCOUNT` | Account to clear postings in. |
| `ID ...` | Specific transaction ids to mark cleared. |
| `--through DATE` | Clear everything dated on or before DATE (sweep a whole statement at once). |
| `--undo` | Un-clear instead of clear. |

Marks postings as cleared against a bank statement. Cleared entries show a
`*` in `register`.

```sh
beans clear Checking 12 14 15
beans clear Checking --through 2026-05-31
```

### `reconcile`

```
beans reconcile ACCOUNT --balance BALANCE [--date DATE] [--json]
```

| Flag | Description |
|---|---|
| `-b, --balance BALANCE` (required) | The statement's ending balance. |
| `-d, --date DATE` | Statement date. Default: today. |
| `--json` | Machine-readable output. |

Compares the account's cleared balance against a bank statement's ending
balance. A nonzero difference with no uncleared postings points straight
at a missing or duplicated transaction.

```sh
beans reconcile Checking --balance 4512.33
```

### Best practices

- Reconcile every account against every statement, every period — small,
  regular reconciliation catches errors while they're still easy to find;
  a large backlog makes tracing a discrepancy much harder.
- Use `clear --through DATE` to sweep an entire statement period at once
  when the statement matches cleanly, and fall back to clearing individual
  ids only for the entries that need special attention.
- When `reconcile` shows a nonzero difference, check for **uncleared**
  postings first (a transaction you haven't cleared yet) before assuming
  something is missing from the ledger entirely — the difference usually
  points at one specific transaction, not a systemic problem.
- Run `period close` right after a clean reconciliation (see below) so the
  reconciled period can't accidentally be altered later.

---

## `period` — closing the books

### `period close`

```
beans period close DATE
```

Locks all transactions on or before `DATE` — they can no longer be added,
voided, or modified. Use this the way an accountant locks a closed month or
quarter.

### `period status`

```
beans period status
```

Shows the current period-close state (the date through which the books are
locked, if any).

### `period reopen`

```
beans period reopen
```

Removes the period lock entirely.

### Best practices

- Close a period only after you've reconciled every account through that
  date — closing is meant to lock in *verified* history, not just old
  history.
- Treat `period reopen` as an exceptional action, not a routine one — if
  you find yourself reopening often, you're closing too early or too
  aggressively.
- Check `period status` before bulk operations like `restore` or a large
  backdated `import`, since a closed period will reject any transaction
  dated on or before the lock.

---

## `goal` — savings and payoff goals

### `goal add`

```
beans goal add NAME --account ACCOUNT [--target AMOUNT] --by DATE
```

| Flag | Description |
|---|---|
| `NAME` | Goal name. |
| `-a, --account ACCOUNT` (required) | Asset account to grow toward a target, or liability account to pay down. |
| `--target AMOUNT` | Target balance. Omit for a liability payoff goal (implied target of 0). |
| `--by DATE` (required) | Target date. |

```sh
beans goal add house --account Savings --target 20000 --by 2028-01-01
beans goal add car-free --account Liabilities:Loans --by 2027-06-01  # payoff
```

### `goal list`

```
beans goal list [--json]
```

Shows progress bars and the required monthly contribution to stay on
track.

### `goal remove`

```
beans goal remove NAME
```

### Best practices

- Omit `--target` for any liability account goal — it's a payoff goal by
  design (target balance zero), and setting an explicit target there would
  be redundant.
- Revisit `goal list`'s required-monthly figure whenever your `--by` date
  approaches or your balance moves unexpectedly — the required contribution
  recalculates from wherever you currently stand, so it's the fastest way
  to see whether you need to accelerate.
- Point goals at the actual account the money accumulates in (not a
  category), since goals track account balances, not spending categories.

---

## `invest` / `price` — investments

Investments are held as FIFO lots with a price history; every trade stays
balanced double-entry.

### `invest buy`

```
beans invest buy SYMBOL QUANTITY --price PRICE --account ACCOUNT
                 [--from ACCOUNT] [--date DATE]
```

| Flag | Description |
|---|---|
| `SYMBOL` | Ticker/security symbol. |
| `QUANTITY` | Shares/units purchased. |
| `-p, --price PRICE` (required) | Price paid per share/unit. |
| `-a, --account ACCOUNT` (required) | Investment (asset) account holding the lot. |
| `--from ACCOUNT` | Paying cash account. Default: `config default_account`, or `Checking`. |
| `-d, --date DATE` | Trade date. Default: today. |

```sh
beans invest buy VTI 10 --price 280 --account Brokerage
```

### `invest sell`

```
beans invest sell SYMBOL QUANTITY --price PRICE --account ACCOUNT
                  [--to ACCOUNT] [--date DATE]
```

| Flag | Description |
|---|---|
| `-p, --price PRICE` (required) | Sale price per share/unit. |
| `-a, --account ACCOUNT` (required) | Investment account the lots are sold from. |
| `--to ACCOUNT` | Receiving cash account. Default: `config default_account`, or `Checking`. |
| `-d, --date DATE` | Trade date. Default: today. |

Sells FIFO (oldest lots first) and books the realized gain or loss.

```sh
beans invest sell VTI 5 --price 300 --account Brokerage
```

### `invest list`

```
beans invest list [--json]
```

Holdings with quantity, cost basis, market value, and unrealized
gain/loss.

### `invest mark`

```
beans invest mark [--date DATE] [--dry-run] [--json]
```

Posts a mark-to-market adjustment so each investment account's book value
equals its market value (against `Income:Unrealized Gains`), assuming the
account is driven by `invest` commands. This is what keeps the balance
sheet reading like a real brokerage statement while Assets = Liabilities +
Equity still holds.

### `price set`

```
beans price set SYMBOL PRICE [--date DATE]
```

Records a price observation for a symbol. Default date: today.

### `price list`

```
beans price list [SYMBOL] [--json]
```

Lists recorded prices, optionally filtered to one symbol.

### Best practices

- Record a `price set` for every symbol you hold at least as often as you
  want your balance sheet's market values to be current — `invest mark`
  only marks-to-market using the latest price you've recorded, it doesn't
  fetch prices itself.
- Run `invest mark --dry-run` before the real run the first time you use
  it on a new ledger, to confirm which accounts and amounts it's about to
  touch.
- Let FIFO lot selling do its job for tax-lot accuracy — don't try to
  specify which lot to sell; if you need specific-lot selling for tax
  purposes, track that externally and only use `beans` for the aggregate
  investment picture.
- Keep `invest buy`/`sell` as the only way money moves into or out of an
  investment account you're tracking this way — mixing in plain
  `tx add`/`transfer` postings against the same account will make `invest
  mark`'s book-vs-market assumption incorrect.

---

## `loan` — amortizing loans

Attach amortization terms to a liability account. `beans` derives the payment
schedule and, for the classified balance sheet, splits the account's balance
into a current portion (principal due within a year) and a non-current
remainder.

### `loan add`

```
beans loan add --account ACCOUNT --principal AMOUNT --rate PERCENT
               (--term N | --payment AMOUNT) [--start DATE]
```

| Flag | Description |
|---|---|
| `-a, --account ACCOUNT` (required) | Liability account the loan is drawn against (fuzzy match). |
| `-p, --principal AMOUNT` (required) | Original loan amount. |
| `-r, --rate PERCENT` (required) | Nominal annual interest rate as a percent, e.g. `6.25`. |
| `-n, --term N` | Number of monthly payments. Omit to derive it from `--payment`. |
| `--payment AMOUNT` | Monthly payment. Omit to derive it from `--term`. |
| `-s, --start DATE` | Date of the first payment. Default: today. |

Give either `--term` or `--payment`; `beans` solves for the other. Attaching a
loan also marks the account non-current. One loan per account.

### `loan list`

```
beans loan list [--json]
```

Every loan with its rate, payment, current balance, current portion,
non-current portion, and payments remaining.

### `loan show`

```
beans loan show ACCOUNT [--json]
```

The full amortization schedule — per payment: date, payment, interest,
principal, and remaining balance — plus total interest over the life of the loan.

### `loan pay`

```
beans loan pay ACCOUNT [--amount AMOUNT] [--from ACCOUNT] [--date DATE]
```

Posts one payment as a balanced transaction: interest (computed on the actual
outstanding balance) to `Expenses:Interest`, the remaining principal against the
liability, and the total out of a cash account (`--from`, else your default cash
account). `--amount` overrides the scheduled payment (e.g. an extra-principal
month). The final payment trues up to the exact remaining balance.

### Best practices

- Attach a loan instead of hand-tagging a mortgage or auto loan `--noncurrent`:
  the schedule splits the *current portion of long-term debt* precisely, which a
  single tag can't.
- The balance sheet always splits the real ledger balance, so use `loan pay`
  (or ordinary postings) to keep that balance accurate; a variable rate or extra
  principal only makes the current/non-current *split point* approximate, never
  the totals or the books.

---

## `currency` — multi-currency and FX

`beans` keeps its books in one base (functional) currency; foreign-currency
asset/liability accounts carry both a base amount and a foreign amount on
each posting.

### `currency set`

```
beans currency set CODE RATE [--date DATE]
```

| Argument/Flag | Description |
|---|---|
| `CODE` | ISO currency code, e.g. `EUR`. |
| `RATE` | Base-currency units per one unit of the foreign currency. |
| `-d, --date DATE` | Rate date. Default: today. |

```sh
beans currency set EUR 1.0832   # base units per 1 EUR
```

### `currency list`

```
beans currency list [--json]
```

Foreign-currency accounts with their balances and unrealized FX gain/loss.

### `currency rates`

```
beans currency rates [CODE] [--json]
```

Recorded exchange-rate history, optionally filtered to one currency.

### `currency revalue`

```
beans currency revalue [--date DATE] [--dry-run] [--json]
```

Posts FX adjustments (against `Income:FX Gains`) so each foreign account's
base value matches the current rate — the FX twin of `invest mark`.

The foreign amount on a posting comes from the latest rate on or before
the transaction date unless given explicitly (`--foreign` on
`spend`/`earn`/`transfer`, or a third value on `tx add --post ACCOUNT
AMOUNT FOREIGN`).

### Best practices

- Record `currency set` rates at least as often as you make transactions
  in that currency — a stale rate means `beans` derives foreign amounts
  from an out-of-date rate for anything you don't specify explicitly with
  `--foreign`.
- Prefer explicit `--foreign` amounts from real receipts/statements over
  letting the rate derive them, the same way you would for `invest buy`/`sell`
  prices — it keeps your books exact rather than approximate.
- Run `currency revalue --dry-run` before the real run for the same reason
  as `invest mark --dry-run` — confirm the accounts and amounts before
  posting.
- Use `account add --currency CODE` only for assets/liabilities actually
  denominated in that currency (a foreign bank account, a foreign loan) —
  income/expense accounts always stay in the ledger's base currency.

---

## `export` / `backup` / `restore`

### `export`

```
beans export {json|csv} [--output FILE]
```

| Argument/Flag | Description |
|---|---|
| `FORMAT` | `json` (everything: accounts, transactions, budgets, rules, goals, lots, rates) or `csv` (one row per posting, for spreadsheets). |
| `-o, --output FILE` | Write to a file instead of stdout. |

Both formats include voided transactions (the CSV carries a `void` column
alongside `cleared`), so archived data matches the ledger rather than
silently dropping voids.

```sh
beans export json -o ledger.json
beans export csv
```

### `backup`

```
beans backup [DEST]
```

| Argument | Description |
|---|---|
| `DEST` | File or directory to write to. Default: alongside the ledger file, timestamped. |

Creates a consistent point-in-time SQLite copy using SQLite's online
backup API — consistent even if taken mid-write.

```sh
beans backup
beans backup ~/backups/
```

Restore a binary snapshot by just pointing `beans` at it directly:
`beans -f backup.db`.

### `restore`

```
beans restore FILE
```

Rebuilds a ledger from a `beans export json` file by replaying every
record through the normal write path — so every transaction is
re-validated to balance. **Restores into an empty ledger only** — it will
not overwrite an already-initialized ledger, which makes it safe for
moving a ledger between machines or restoring from a text backup.

```sh
beans -f new.db restore ledger.json
```

### Best practices

- Use `backup` for routine, frequent snapshots (before large imports, on a
  schedule) — it's cheap, consistent even mid-write, and restoring is just
  pointing `-f` at the file.
- Use `export json` for portable, human-inspectable archival and for
  moving a ledger between machines or `beans` versions — it's the only
  format that round-trips through `restore`'s full validation.
- Use `export csv` specifically for spreadsheet analysis, not as a backup
  format — it's a flattened, posting-per-row view, not something `beans`
  can restore from.
- Never point `restore` at an existing ledger expecting it to merge or
  overwrite — it only works into an empty ledger; create a fresh file with
  `-f` first if you need to test a restore.

---

## `completions` — shell completions

```
beans completions {bash|zsh}
```

Prints a shell completion script for the given shell, completing commands,
subcommands, and account names (via `account list --names`).

```sh
beans completions bash > ~/.local/share/bash-completion/completions/beans
beans completions zsh  > ~/.zfunc/_beans    # with fpath+=(~/.zfunc)
```

### Best practices

- Install completions once, right after `pip install`, rather than
  waiting until you're annoyed by typing full account names — they
  complete account names dynamically from your actual chart of accounts.
- Regenerate/re-source completions after a `beans` upgrade that adds new
  commands, since the script is generated from the installed version's
  command set.

---

## General best practices

- **Let every transaction balance itself.** Omit the amount on one posting
  in multi-leg entries and let `beans` compute it; it's a free
  double-check that your numbers add up to what you intended.
- **Use `spend`/`earn`/`transfer` for the 95% case, `tx add` for the rest.**
  Reserve the general form for genuinely multi-leg transactions (split
  paychecks, three-way splits); the shortcuts are shorter and safer for
  everything else because they default the cash side for you.
- **Reconcile often, close periods after reconciling.** Small, frequent
  reconciliation catches errors while they're cheap to trace; `period
  close` then locks in verified history so it can't drift later.
- **Never delete — void, close, or reopen instead.** `tx void`, `account
  close`, and `period reopen` are all the "undo" primitives `beans`
  offers; there's no destructive delete, which is what makes the ledger
  trustworthy as an audit trail.
- **Back up before anything irreversible-feeling.** A CSV import with
  unfamiliar column mappings, a `restore`, a big batch of `recur run --to`
  postings — `beans backup` first, `--dry-run` when available, then do it
  for real.
- **Keep `--cash` and `--cashflow` accurate on every account.** They're the
  quiet inputs behind the statement of cash flows; get them right at
  `account add` time and you'll rarely think about them again.
- **Prefer `--json` for anything you're not reading yourself.** The
  formatted tables are for humans and can change; the JSON schema is the
  stable contract for scripts and other tools.
- **Start every session with bare `beans`.** The dashboard is designed to
  surface what needs attention (due bills, off-track budgets and goals)
  before you go looking for it command by command.
- **Use full account paths in anything you'll re-run.** Fuzzy matching is
  great for one-off, interactive entry; recurring rules, scripts, and
  import rules should use exact account names so they don't silently break
  or become ambiguous as your chart of accounts grows.
