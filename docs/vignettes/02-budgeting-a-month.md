# Budgeting a month

**What you'll accomplish:** put spending targets on your categories, record a
month of activity, get instant feedback as you go, and read a budget-vs-actual
variance report. Then tie the numbers back to your income statement and check
your savings rate.

**Prerequisites:** comfort with [Getting started](01-getting-started.md) —
you should already know `init`, the chart of accounts, and `spend`/`earn`.

We'll work in a fresh scratch ledger seeded with opening balances:

```sh
export BEANS_LEDGER=/tmp/budget-demo.db
beans init
beans tx add --date 2026-06-01 --desc "Opening balances" \
    --post Assets:Checking 4000 --post Assets:Savings 8000 \
    --post "Equity:Opening Balances"
```

## 1. Set your budgets

A budget is a target amount per account, at a chosen cadence. Monthly is the
default; income targets work too.

```sh
beans budget set Groceries 600
beans budget set Dining 200
beans budget set "Housing:Rent" 1800
beans budget set Insurance 1200 --period yearly
beans budget set Salary 6000
```

```text
Budget set: Expenses:Food:Groceries = $600.00 monthly
Budget set: Expenses:Food:Dining = $200.00 monthly
Budget set: Expenses:Housing:Rent = $1,800.00 monthly
Budget set: Expenses:Insurance = $1,200.00 yearly
Budget set: Income:Salary = $6,000.00 monthly
```

Notice the cadence is per-budget: insurance is a *yearly* $1,200, which `beans`
will pro-rate to whatever period you report on. Review them anytime:

```sh
beans budget list
```

```text
Account                    Amount  Period
------------------------------------------
Expenses:Food:Dining       200.00  monthly
Expenses:Food:Groceries    600.00  monthly
Expenses:Housing:Rent    1,800.00  monthly
Expenses:Insurance       1,200.00  yearly
Income:Salary            6,000.00  monthly
```

## 2. Spend the month — with live feedback

Record the month's activity exactly as in vignette 01. The difference: once a
category has a budget, every `spend` against it tells you where you stand.

```sh
beans earn 6000 Salary --date 2026-06-02 --desc "June paycheck"
beans spend 1800 Rent --date 2026-06-03
beans spend 175 Groceries --payee "Market" --date 2026-06-05
beans spend 240.50 Groceries --payee "Costco" --date 2026-06-09
beans spend 96 Dining --date 2026-06-07 -m "Brunch"
beans spend 145.75 Dining --date 2026-06-11 -m "Dinner out"
```

Watch the running budget feedback (printed after each entry):

```text
Recorded transaction #3: 2026-06-03  Spending: Rent  $1,800.00
    Expenses:Housing:Rent  <-  Assets:Checking
Rent: 100% of June budget used ($1,800.00 of $1,800.00/month)
...
Recorded transaction #6: 2026-06-07  Brunch  $96.00
    Expenses:Food:Dining  <-  Assets:Checking
Dining: 48% of June budget used ($96.00 of $200.00/month)
Recorded transaction #7: 2026-06-11  Dinner out  $145.75
    Expenses:Food:Dining  <-  Assets:Checking
Dining: 121% of June budget used ($241.75 of $200.00/month)
```

That dinner pushed dining **over** its $200 monthly budget — you find out the
moment it happens, not at month end. One more, just to make the point:

```sh
beans spend 30 Dining --date 2026-06-12 -m "Coffee run"
```

```text
Recorded transaction #8: 2026-06-12  Coffee run  $30.00
    Expenses:Food:Dining  <-  Assets:Checking
Dining: 136% of June budget used ($271.75 of $200.00/month)
```

## 3. Read the variance report

For the whole-month picture, ask for a budget report over June:

```sh
beans budget report --period 2026-06
```

```text
BUDGET REPORT
For the period: June 2026

Account                       Budget     Actual  Remaining  Used
----------------------------------------------------------------
Expenses
  Expenses:Food:Dining        200.00     271.75     -71.75  136%
  Expenses:Food:Groceries     600.00     415.50     184.50   69%
  Expenses:Housing:Rent     1,800.00   1,800.00       0.00  100%
  Expenses:Insurance          100.00       0.00     100.00    0%
----------------------------------------------------------------
Total                      $2,700.00  $2,487.25    $212.75   92%

Income
  Income:Salary             6,000.00   6,000.00       0.00  100%
----------------------------------------------------------------
Total                      $6,000.00  $6,000.00      $0.00  100%
```

A negative **Remaining** (and a `Used` over 100%) flags an overspend — dining is
$71.75 in the red — while groceries left $184.50 on the table. The yearly
insurance budget shows up here as $100 (one month's twelfth of $1,200): budgets
are **normalized to the report period**.

## 4. Budgets scale to any period

The same budgets answer "how am I tracking this quarter?" — `beans` scales each
one automatically:

```sh
beans budget report --period 2026-Q2
```

```text
BUDGET REPORT
For the period: Q2 2026

Account                        Budget     Actual   Remaining  Used
------------------------------------------------------------------
Expenses
  Expenses:Food:Dining         600.00     271.75      328.25   45%
  Expenses:Food:Groceries    1,800.00     415.50    1,384.50   23%
  Expenses:Housing:Rent      5,400.00   1,800.00    3,600.00   33%
  Expenses:Insurance           300.00       0.00      300.00    0%
------------------------------------------------------------------
Total                       $8,100.00  $2,487.25   $5,612.75   31%
...
```

A $200/month dining budget becomes $600 for the quarter. (Reporting on
`this-month` mid-month pro-rates the budget to the days elapsed — handy for a
"am I on pace *today*?" read — which is why partial-month numbers look smaller
than the full-month ones above.)

## 5. Tie it back to the income statement

The budget *actuals* aren't a separate tally — they're the same postings the
income statement sums. Compare:

```sh
beans report income --period 2026-06
```

```text
INCOME STATEMENT
For the period: June 2026

Income
  Salary         6,000.00  100.0%
---------------------------------
Total Income    $6,000.00  100.0%

Expenses
  Food
    Dining         271.75    4.5%
    Groceries      415.50    6.9%
  Housing
    Rent         1,800.00   30.0%
---------------------------------
Total Expenses  $2,487.25   41.5%
---------------------------------
Net Income      $3,512.75   58.5%
```

Dining $271.75, groceries $415.50, rent $1,800 — identical to the `Actual`
column. The budget report is just the income statement with targets bolted on.

## 6. Check the health metrics

`analyze` turns the same data into the ratios you'd compute for a company:

```sh
beans analyze --period 2026-06
```

```text
FINANCIAL ANALYSIS
For the period: June 2026

Performance
  Income                             $6,000.00
  Expenses                           $2,487.25
  Net Income (savings)               $3,512.75
  Savings Rate                           58.5%
...
Working Capital
  Current Assets                    $15,512.75
  Current Liabilities                    $0.00
  Working Capital                   $15,512.75

Ratios
  Current Ratio                            n/a
  Quick Ratio                              n/a
  Liquidity Runway      6.2 months of expenses
  Debt / Assets                           0.0%
  Debt / Annual Income                    0.0%
...
Top expense categories
Account                    Amount  % of Income
----------------------------------------------
Expenses:Housing:Rent    1,800.00        30.0%
Expenses:Food:Groceries    415.50         6.9%
Expenses:Food:Dining       271.75         4.5%
```

A **58.5% savings rate** and **6.2 months** of liquidity runway — the household
equivalent of margin and burn rate. The **current** and **quick ratios** read
`n/a` here because this ledger carries no current liabilities (no credit-card
balance, no short-term debt) — there's nothing to divide by. Once you owe money
due within a year, those ratios measure whether your near-term assets can cover
it; the **[Loans & liquidity](05-loans-and-liquidity.md)** walkthrough builds a
ledger where they come alive.

## What just happened

You set targets once, got nudged as you spent, and read a single report that
showed every category against plan — all from the ordinary postings you were
already recording. No separate budgeting ledger, no double entry of the data.

Tidy up anytime: `beans budget remove Insurance` drops a target;
`beans budget set Dining 250` revises one.

## Next steps

- **[Import & reconcile →](03-import-and-reconcile.md)** — stop typing every
  transaction by hand: pull them from your bank's CSV and tie the result back to
  your statement.
- Reference: [Budgeting](../../README.md#budgeting) and
  [Analysis](../../README.md#analysis) in the main README.
