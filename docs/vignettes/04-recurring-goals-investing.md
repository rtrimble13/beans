# Recurring, goals & investing

**What you'll accomplish:** automate the transactions you'd otherwise type every
month, point your savings at concrete targets, track investments as FIFO lots
with mark-to-market valuation, and peek at where your finances are headed. This
is `beans` working *for* you between the day-to-day entries.

**Prerequisites:** [Getting started](01-getting-started.md). Helpful but not
required: [Budgeting](02-budgeting-a-month.md).

Start fresh with opening balances that include a credit-card balance to pay
down:

```sh
export BEANS_LEDGER=/tmp/auto-demo.db
beans init
beans tx add --date 2026-01-01 --desc "Opening balances" \
    --post Assets:Checking 5000 --post Assets:Savings 3000 \
    --post "Liabilities:Credit Card" -2400 \
    --post "Equity:Opening Balances"
```

## 1. Define recurring transactions

Rent, a paycheck, a subscription — anything on a schedule. Define the postings
once and a frequency; `beans` knows when each is due.

```sh
beans recur add rent --freq monthly --start 2026-01-01 \
    --post Expenses:Housing:Rent 1800 --post Assets:Checking
beans recur add paycheck --freq biweekly --start 2026-01-02 \
    --desc "Salary deposit" --post Assets:Checking 2500 --post Income:Salary
```

```text
Added recurring rule 'rent' (monthly, first due 2026-01-01)
Post due instances with `beans recur run`.
Added recurring rule 'paycheck' (biweekly, first due 2026-01-02)
Post due instances with `beans recur run`.
```

```sh
beans recur list
```

```text
Rule      Frequency  Next Due    Status  Posted    Amount
---------------------------------------------------------
paycheck  biweekly   2026-01-02  due     0       2,500.00
rent      monthly    2026-01-01  due     0       1,800.00

2 rule(s) due — post with `beans recur run`
```

Supported frequencies are `daily`, `weekly`, `biweekly`, `monthly`,
`quarterly`, and `yearly`. Monthly-style rules anchor to the start date's
day-of-month and clamp to short months (a rule started Jan 31 posts Feb 28,
then Mar 31).

## 2. Post what's due — idempotently

Defining a rule doesn't post anything; you post on demand. Preview first:

```sh
beans recur run --to 2026-03-31 --dry-run
```

```text
Would post 10 transaction(s) due through 2026-03-31
Date        Rule      Description       Amount
----------------------------------------------
2026-01-02  paycheck  Salary deposit  2,500.00
2026-01-16  paycheck  Salary deposit  2,500.00
...
2026-01-01  rent      rent            1,800.00
2026-02-01  rent      rent            1,800.00
2026-03-01  rent      rent            1,800.00
```

Seven biweekly paychecks and three monthly rents through Q1. Post them for real
by dropping `--dry-run`:

```sh
beans recur run --to 2026-03-31
```

```text
Posted 10 transaction(s) due through 2026-03-31
...
```

The key property: **`run` is idempotent.** Run it again and nothing
double-posts — it only ever fills the gap between what's posted and what's due:

```sh
beans recur run --to 2026-03-31
```

```text
Posted 0 transaction(s) due through 2026-03-31
```

So you can safely `beans recur run` as often as you like — every login, in a
cron job, whatever. Posted instances are ordinary transactions (tagged
`recurring`); they stay even if you later `pause`, `resume`, or `remove` the
rule. And any command nudges you on stderr when rules come due:

```text
(2 recurring rule(s) due — run `beans recur run`)
```

## 3. Set goals

Point an account at a target by a date. Two flavors: grow an **asset** to a
target balance, or pay a **liability** down to zero.

```sh
beans goal add emergency-fund --account Savings --target 10000 --by 2027-01-01
beans goal add debt-free --account "Credit Card" --by 2026-12-01
```

```text
Goal 'emergency-fund' added (savings, Assets:Savings by 2027-01-01)
Goal 'debt-free' added (payoff, Liabilities:Credit Card by 2026-12-01)
```

`goal list` shows progress and — most usefully — the **monthly contribution**
each goal needs from today to land on time:

```sh
beans goal list
```

```text
GOALS
As of: 2026-06-12

debt-free — Liabilities:Credit Card (payoff)
  $2,400.00 remaining, due 2026-12-01
  Needs $422.25/month for 6 months

emergency-fund — Assets:Savings (savings)
  [######--------------] 30%  $3,000.00 of $10,000.00 by 2027-01-01
  Needs $1,044.42/month for 7 months
```

The savings goal is 30% there ($3,000 of $10,000) and needs $1,044.42/month;
the payoff goal needs $422.25/month to clear the card by December. These update
automatically as the underlying account balance moves.

## 4. Track investments

Hold securities as **FIFO lots** with a price history — and keep it all balanced
double-entry. Buy moves cash into the investment account:

```sh
beans invest buy VTI 10 --price 280 --account Brokerage --date 2026-02-10
beans invest buy VTI 5 --price 300 --account Brokerage --date 2026-04-15
```

```text
Recorded transaction #12: bought 10 VTI for $2,800.00 (Assets:Investments:Brokerage <- Assets:Checking)
Recorded transaction #13: bought 5 VTI for $1,500.00 (Assets:Investments:Brokerage <- Assets:Checking)
```

Record a current price, then value the portfolio:

```sh
beans price set VTI 320 --date 2026-06-01
beans invest list
```

```text
PORTFOLIO
As of: 2026-06-12

Account                       Symbol  Qty  Cost Basis   Price  Market Value  Unrealized
---------------------------------------------------------------------------------------
Assets:Investments:Brokerage  VTI      15    4,300.00  320.00      4,800.00      500.00
---------------------------------------------------------------------------------------
Total                                       $4,300.00             $4,800.00     $500.00
```

15 shares cost $4,300 and are worth $4,800 — a $500 **unrealized** gain. That
gain isn't on the books yet. `mark` posts the mark-to-market adjustment so the
balance sheet carries market value:

```sh
beans invest mark --date 2026-06-01
```

```text
Posted 1 mark-to-market adjustment(s) as of 2026-06-01
Account                           Book    Market  Adjustment
------------------------------------------------------------
Assets:Investments:Brokerage  4,300.00  4,800.00      500.00
```

When you sell, `beans` draws down lots **first-in, first-out** and books the
**realized** gain against the original cost — not the marked value:

```sh
beans invest sell VTI 8 --price 320 --account Brokerage --date 2026-06-10
```

```text
Recorded transaction #15: sold 8 VTI for $2,560.00 (realized gain $320.00)
```

Eight shares sold at $320 came out of the first lot (bought at $280), so the
realized gain is 8 × ($320 − $280) = $320. The portfolio now shows the
remaining 7 shares at their true FIFO cost:

```sh
beans invest list
```

```text
PORTFOLIO
As of: 2026-06-12

Account                       Symbol  Qty  Cost Basis   Price  Market Value  Unrealized
---------------------------------------------------------------------------------------
Assets:Investments:Brokerage  VTI       7    2,060.00  320.00      2,240.00      180.00
---------------------------------------------------------------------------------------
Total                                       $2,060.00             $2,240.00     $180.00
```

Two shares left from the $280 lot plus five from the $300 lot = $2,060 cost
basis — FIFO accounting, automatic.

## 5. Look ahead

With recurring rules defined, `forecast` projects them forward (recurring
schedule takes priority over historical averages and budgets):

```sh
beans forecast --months 3 --use-recurring
```

```text
FORECAST
Horizon: 3 months | Basis: recurring schedule > 6-month history (average)

Month      Income  Expenses         Net  Proj. Cash  Proj. Net Worth
--------------------------------------------------------------------
2026-07  7,500.00  1,800.00    5,700.00   24,060.00        24,220.00
2026-08  5,000.00  1,800.00    3,200.00   27,260.00        27,420.00
2026-09  5,000.00  1,800.00    3,200.00   30,460.00        30,620.00
--------------------------------------------------------------------
Total                        $12,100.00

Projection drivers (monthly)
Account                Type      Monthly  Basis
---------------------------------------------------
Expenses:Housing:Rent  expense  1,800.00  recurring
Income:Salary          income   5,833.33  recurring
```

The `drivers` table shows exactly what's behind the projection and on what
basis — here both lines come straight from the recurring schedule. July shows
three biweekly paychecks ($7,500); other months show two.

## What just happened

You set up the machinery that runs your finances on autopilot: recurring rules
that post your bills and income idempotently, goals that tell you the monthly
number to hit, an investment book that values itself like a brokerage statement,
and a forecast that turns it all into a forward view — every piece staying
balanced double-entry underneath.

## Where to go next

You've now walked the four core workflows. From here the main README covers the
rest:

- [Multi-currency](../../README.md#multi-currency) — foreign-denominated
  accounts with FX revaluation, the currency twin of `invest mark`.
- [Export & backup](../../README.md#export--backup) — your whole ledger as JSON
  or CSV, and consistent SQLite snapshots.
- [Recurring transactions](../../README.md#recurring-transactions),
  [Goals](../../README.md#goals), and [Investments](../../README.md#investments)
  for the full flag reference behind this vignette.
