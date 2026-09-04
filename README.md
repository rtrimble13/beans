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
- **Trends over time** — `report trend` puts income, expenses and every
  account side by side across N months or quarters, ranked by what moved most,
  so drift is visible before it is obvious. It stops at the last *complete*
  period, because a part-elapsed one reads as a collapse.
- **Budgeting** — per-account budgets at weekly/monthly/quarterly/yearly
  cadence, with budget-vs-actual variance reports over any period.
- **Forecasting** — project income, expenses, cash, and net worth forward from
  historical averages, a linear trend, or your budgets.
- **Analysis** — savings rate, liquidity runway, debt-to-assets,
  debt-to-income, and expense composition.
- **Reconciliation** — clear postings against bank statements and reconcile
  to the cent, the way errors actually get caught. Hand `reconcile` the
  statement CSV itself and it matches line by line, sorting what doesn't
  tie into named discrepancy classes — read-only, so it never touches the
  register.
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
  deduplicating CSV import that categorizes itself — `beans categorize`
  suggests a counter-account for every row of a bank export from your own
  ledger's history, with a confidence score and the evidence behind it, and
  writes an editable file for you to review before anything is imported —
  shell completions, and `--json` output on every report for scripting.
- **AI assistant (optional)** — an opt-in `beans ai` command group: ask
  questions in plain English (`beans ai ask`) and get a CFO-style narrative
  review of your finances (`beans ai review`). Off by default, read-only,
  with a `--dry-run` transparency switch and support for local models so
  nothing has to leave your machine. See
  [AI assistant](#ai-assistant-optional).
- **Use it from Claude (optional MCP)** — an opt-in `beans mcp` server exposes
  the ledger as read-only tools and a `review` prompt to Claude Desktop and
  Claude Code, so Claude can read your finances directly. Local-first,
  read-only by default. See [Use beans from Claude](#use-beans-from-claude-mcp).
- **Agent skills for Claude Code (optional)** — three packaged workflows:
  `beans-import` gets a bank CSV into the ledger, categorized and reconciled
  (it writes, after you approve a dry run); `beans-report` reads trends across
  periods and writes a ranked briefing; `beans-economic` builds an economic
  balance sheet from an interview and stress-tests it. The last two are
  strictly read-only. See
  [Agent skills for Claude Code](#agent-skills-for-claude-code).
- **No dependencies** — the core is pure Python standard library and fully
  offline; data lives in a single SQLite file you own. The optional extras add
  the only opt-in surfaces: `[ai]` reaches a model provider (the sole networked
  feature), and `[mcp]` runs a local server for Claude — and **both** are built
  on just the standard library, so neither adds a third-party dependency.

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
7. [The AI assistant](docs/vignettes/07-ai-assistant.md) — install the
   optional extra, configure a provider (hosted or local), and ask questions
   and run reviews over your ledger with full transparency.
8. [Using beans from Claude (MCP)](docs/vignettes/08-mcp.md) — connect the
   optional MCP server to Claude Desktop and Claude Code so Claude can read
   your ledger directly, read-only and local-first.

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
beans report trend --periods 12                  # a series, not a snapshot
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

`report trend` is the odd one out, and deliberately so: every other statement
covers one period, so a question about *drift* — "are groceries creeping up?",
"how has my savings rate moved?" — had no command. It reports income, expenses,
net and per-account flows across N months or quarters, ranked by largest
change, and its window ends at the last **complete** period. That default
matters: four days into a month, that month has rent posted and no paycheck, so
including it in a series reads as an income collapse that reverses on the 15th.
`--include-partial` opts back in, marks the period, and still keeps it out of
the averages.

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
transaction.

### Reconciling line by line

The balance check tells you *that* something is off. To find out *which*
line, give `reconcile` the statement export itself:

```sh
beans reconcile Checking --statement may.csv --balance 4512.33
```

It pairs each statement row against the register and sorts the rest into
named classes:

```text
Matched                         28
  on an exact date              26
  within the date window         2
-----------------------------------
Amount mismatch                  1
In bank, not in ledger           1
In ledger, not in bank           1
Cleared, absent from statement   0
```

Amounts must match **exactly** — an amount difference is a finding, not
something to fuzz away — while dates get a ±5 day window and descriptions
are compared loosely, so `WHOLE FOODS MARKET #412` matches `Whole Foods`.
That window is what keeps recurring entries quiet: book rent to the 1st
of the month and a statement line on the 4th (or the 29th of the month
before) still reads as a match, not a discrepancy. Tune it with
`--window`, or set `--window 0` to demand exact dates.

This is **read-only** — no transaction is posted, nothing is cleared.
The one file it can write is the hand-off to `import`:

```sh
beans reconcile Checking --statement may.csv --unmatched-out new.csv
$EDITOR new.csv                       # fill in any blank category
beans import new.csv --account Checking
```

`new.csv` holds just the in-bank-not-in-ledger rows, in the exact shape
`import` reads, with the category filled in from your saved rules
wherever one matched — the blanks are the edit it's asking for. Since
you're meant to edit it, `reconcile` won't overwrite an existing one
without `--force`. For credit cards, whose exports usually report a
purchase as a positive number, add `--invert`.

Once a statement is reconciled, lock it:

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
`--category`. When several rules match, the longest — most specific —
pattern wins, whatever order you added them in:

```sh
beans rule add "WHOLE FOODS" Groceries
beans rule add "SHELL" Transportation
beans rule list
```

### Letting the ledger categorize for you

Rules only cover merchants you remembered to write a rule for. `categorize`
covers the rest by reading the answer out of your own register — how you
categorized this same merchant the last twenty times — and tells you how
sure it is:

```sh
beans categorize bank.csv --account Checking             # preview only
beans categorize bank.csv --account Checking -o prep.csv
```

```text
Already set in the file  0
From an import rule      1
Inferred from history    1
Needs a decision         1

Date        Description                   Amount  Account          Conf  Basis
---------------------------------------------------------------------------------------
2026-10-20  HARBOR POINT VETERINARY       -88.00  —                0.00  no match
2026-10-09  BLUE RIDGE DENTAL ASSOC 41   -210.00  Expenses:Health  0.60  3 prior
2026-10-02  PAYROLL DEPOSIT ACME CORP   3,200.00  Income:Salary    1.00  rule "PAYROLL"
```

Rows come out **least certain first**, so the ones needing you are at the
top. The dentist files itself from three prior transactions with no rule
ever written — and the store number in `...ASSOC 41` doesn't throw it off,
because merchant matching ignores digits.

Read the `basis`, not just the score: `3 prior` is thin evidence that firms
up on its own, while `20 prior: 14 Shopping / 6 Cloud` is plenty of evidence
that *disagrees* — a merchant that genuinely goes two ways. Same score,
different action. Confidence ranks your attention; it is not a probability,
and nothing is imported on its strength.

`-o` writes a CSV in exactly the shape `import` reads (the extra columns are
ignored on import), so the loop is preview → edit the blanks → import.
Rules still matter for what history can't know: a brand-new merchant, a
deliberate change of mind, and a fresh ledger with no history at all.

## Shell completions

```sh
beans completions bash > ~/.local/share/bash-completion/completions/beans
beans completions zsh  > ~/.zfunc/_beans    # with fpath+=(~/.zfunc)
```

Completes commands, subcommands, and account names (via
`beans account list --names`).

## Using beans with AI

Four ways to point a model at your books, and they are complements rather than
alternatives. Pick by what you are trying to do:

| You want to… | Use | Needs |
|---|---|---|
| ask from a terminal, a script, or a local model, with nothing else installed | **`beans ai`** | `[ai]` extra + a provider key (or a local endpoint) |
| ask from Claude Desktop, Claude Code, or any other MCP host | **`beans mcp`** | `[mcp]` extra + a host |
| get a bank statement into the ledger, categorized and reconciled | **`beans-import` skill** | Claude Code |
| understand what has been happening across months — trends, drift, inferences | **`beans-report` skill** | Claude Code |
| build an economic balance sheet and find out what it depends on | **`beans-economic` skill** | Claude Code |

The division is worth internalizing: the **server reads** (a period's numbers,
on demand), the **skills do a job** (a statement in; a briefing out), and
`beans ai` is the one that needs no other software at all. Everything here is
opt-in, and neither optional extra adds a third-party dependency.

### AI assistant (optional)

`beans ai` is an opt-in, off-by-default command group — the only part of the
tool that reaches the network. Install the extra (it adds **no** third-party
dependency; the client uses the standard library) and set a provider key:

```sh
pip install "beans-ledger[ai]"
export ANTHROPIC_API_KEY=sk-...        # or BEANS_AI_KEY, or an OpenAI key
```

Ask questions in plain English — an agent runs read-only `beans` commands and
reads their JSON to answer, so figures never drift from what `beans report`
would show:

```sh
beans ai ask "how much did I spend on eating out last quarter vs the one before?"
beans ai ask --explain "am I over budget anywhere this month?"   # show the commands it ran
```

Get a CFO-style narrative over your statements and ratios:

```sh
beans ai review                        # this-period briefing
beans ai review --brief --period ytd   # 3-bullet TL;DR
beans ai review --focus trend          # add a 12-period series to the bundle
```

**Privacy & data flow.** Only the JSON of the read-only commands the assistant
chooses to run is sent to the provider — never the ledger file itself, and
nothing is written back without a per-command confirmation showing the exact
command. `--dry-run` prints exactly what would be sent and sends nothing:

```sh
beans ai review --dry-run              # print the bundle, contact no one
```

**Local models.** Point at any OpenAI-compatible endpoint (Ollama, LM Studio,
vLLM) to keep everything on-box:

```sh
beans ai config set ai.provider openai
beans ai config set ai.base_url http://localhost:11434/v1
beans ai ask "what's my runway if I lost my job today?"
```

See [`docs/MANUAL.md`](docs/MANUAL.md) for the full `ai` reference and the
[AI assistant vignette](docs/vignettes/07-ai-assistant.md) for a walkthrough.

### Use beans from Claude (MCP)

`beans mcp` is an opt-in [MCP](https://modelcontextprotocol.io) server — the
way to let **Claude Desktop** and **Claude Code** read your ledger directly.
The host owns the model; `beans` just answers tool calls, locally and read-only
by default. There is no API key in `beans` and no embedded LLM (that's the
separate `[ai]` feature). The `[mcp]` extra adds no third-party dependency —
the protocol is hand-rolled on the standard library.

```sh
pip install "beans-ledger[mcp]"
beans mcp doctor        # verifies your setup and prints a ready-to-paste config
```

`doctor` finds your `beans-mcp` path and ledger, starts the server to confirm a
clean protocol stream, and prints a filled-in `claude_desktop_config.json`
snippet. Register it with Claude Code inside WSL:

```sh
claude mcp add beans --scope user -- beans-mcp --file ~/.beans/ledger.db
```

Then ask Claude about your finances — it calls read-only tools
(`beans_income_statement`, `beans_trend`, `beans_analyze`, …) and a `review`
prompt, so its
numbers match your statements exactly. Writes are off unless you pass
`--allow-writes`, and even then the host approves each call.

The important detail for most setups is the **WSL/Windows boundary** (beans in
WSL, Claude Desktop on Windows). The focused guide —
[`docs/mcp-setup-wsl.md`](docs/mcp-setup-wsl.md) — covers the
`claude_desktop_config.json` block, the native-Windows fallback, and a
troubleshooting table; the [MCP vignette](docs/vignettes/08-mcp.md) is a
start-to-finish walkthrough.

### Agent skills for Claude Code

Three [agent skills](https://code.claude.com/docs) ship with this repository
and install independently. All drive the ordinary `beans` CLI, so their figures
are the ones your statements show.

```sh
git clone https://github.com/rtrimble13/beans.git
cd beans && ./scripts/install_skill.sh     # all, symlinked into ~/.claude/skills
./scripts/install_skill.sh beans-report    # or just one
```

#### `beans-import` — statements into the ledger

It teaches Claude the statement-import workflow — inspect the export,
`categorize`, triage what's uncertain, dry-run, `import`, `reconcile` — and the
guardrails that go with writing to a financial record. From any directory:

```
import my November checking statement from ~/statements/november.csv
```

Claude derives the column mapping and sign convention from the file itself
(`MM/DD/YYYY` dates and split debit/credit columns are rewritten into a working
copy — your original is never touched), runs `beans categorize`, and hands you
a table of only the rows that need a decision, with transfers and refunds
flagged. It shows a `--dry-run` and waits for your go-ahead before writing
anything, then reconciles the result against the statement.

It will not use `--learn`, will not skip the dry run, will not invent an
account name, and will not reopen a closed period. Confidence scores rank your
attention; there is no auto-accept threshold, in `beans` or in the skill.

Setup, troubleshooting and WSL notes:
[`docs/claude-skill-setup.md`](docs/claude-skill-setup.md). Start-to-finish
walkthrough: the [Claude skill vignette](docs/vignettes/09-claude-skill.md).

#### `beans-report` — trends out of it

`beans-report` is the read-only counterpart. `beans` reports one period at a
time — every statement except `networth` is a snapshot, and `--compare` reaches
exactly one period back — so nothing in the tool can answer *"is my grocery
spend drifting up, and what does that do to my runway?"* This skill assembles
the series `beans` doesn't keep, and reads it with rules.

```
run my monthly financial review — what's been happening?
are my expenses creeping up, or was that just a bad month?
how has my savings rate moved this year?
```

It gathers many periods in a single pass, then classifies each account as
`drift`, `step`, `one-off`, `new`, `stopped` or `stable` using median-based
statistics, so one vet bill never becomes a trend. Two thresholds gate every
finding — whether it clears the series' own noise, and whether it is large
enough to matter against your income — which is what keeps a briefing to four
lines instead of thirty.

The rules that matter most are the ones about not fooling you:

- **A period in progress is never trended.** On the 4th of the month, that
  month shows four days of spending and often no salary; run it into a series
  and it reads as an income collapse that never happened.
- **A lapsed payment is surfaced, not celebrated.** A recurring charge that
  stopped is money you may still owe, or a service you stopped getting — never
  reported as a welcome drop in spending.
- **Data quality is checked first.** If a quarter of your spending sits in
  `Expenses:Other`, category trends measure filing habits; the skill says so and
  offers totals instead.
- **"Nothing much changed" is a valid answer**, and the correct one for a
  well-run ledger most months.

It never writes to your ledger. Recommendations — a recalibrated budget, a
paused rule to resume — are printed as commands for you to run.

Setup and troubleshooting for every skill:
[`docs/claude-skill-setup.md`](docs/claude-skill-setup.md). Walkthroughs: the
[import vignette](docs/vignettes/09-claude-skill.md) and the
[trend-briefing vignette](docs/vignettes/10-reporting-skill.md).

#### `beans-economic` — the future, and what it rests on

`beans economic bs` will print an economic balance sheet. The catch is that
exactly one of its lines — Financial Capital — comes from your books. The other
five come from beliefs about your own life, and they move the answer far more
than anything in the ledger does. On one worked example, holding the books
completely constant:

| Change one assumption | Economic net worth |
|---|---:|
| defaults | $512,714.80 |
| income growth 3% | $1,069,479.92 |
| **inflation 3%** | **−$114,889.96** |

So this skill does the two things a single command cannot. It **interviews you**
for the six forward-looking lines — when you stop working, what happens to
spending then, pension, inheritance, bequests, other obligations — and writes a
`beans economic` config document from your answers, validated by running beans
against it before the file lands. Then it **stress-tests** the result:

```
build my economic balance sheet
what would retiring five years earlier cost me?
how sensitive is my plan to inflation?
```

It reports which assumption moves the answer most, the value at which economic
net worth crosses zero (*"negative above 2.60% long-run inflation"*), which
inputs your config has pinned so sweeping them proves nothing, and — for a
decision question — the scenario delta decomposed by line, which is the cost of
that decision in today's dollars.

Three things it will not do: state a figure without the assumptions that
produced it, let a line you never mentioned become a silent zero, or write to
your ledger. It also refuses an ambiguous rate — `beans` reads a bare `0.03` as
0.03%, not 3%, and that alone nearly doubles future consumption.

Walkthrough: the
[economic balance sheet vignette](docs/vignettes/11-economic-skill.md).

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
