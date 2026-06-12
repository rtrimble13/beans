# Getting started: your first ledger

**What you'll accomplish:** create a ledger, take stock of the starter chart of
accounts, record your opening balances the way a company books its first entry,
capture a handful of everyday transactions, and read the three financial
statements that fall out of them. By the end you'll have a complete, balanced
set of books and know how to look at them from every angle.

**Prerequisites:** `beans` installed (`pip install .`). Nothing else — we start
from an empty file.

Throughout, we point `beans` at a scratch ledger so nothing touches your real
books. Set it once:

```sh
export BEANS_LEDGER=/tmp/demo.db
```

(Or pass `-f /tmp/demo.db` to each command — same effect.)

## 1. Create the ledger

```sh
beans init
```

```text
Initialized ledger at /tmp/demo.db (currency: USD)
Created a starter chart of 23 accounts — see `beans account list`.
Record opening balances against Equity:Opening Balances, e.g.:
  beans tx add --desc 'Opening balance' --post Assets:Checking 2500 --post 'Equity:Opening Balances'
```

`init` creates a single SQLite file and seeds a sensible **chart of accounts** —
the named buckets every transaction flows through. (Add `--bare` if you'd rather
build the chart from scratch, or `--currency EUR` for a different base
currency.)

## 2. Look at the starter chart

```sh
beans account list
```

```text
Account                        Type       Flags  Balance
--------------------------------------------------------
Assets:Cash                    asset      cash      0.00
Assets:Checking                asset      cash      0.00
Assets:Savings                 asset      cash      0.00
Assets:Investments:Brokerage   asset                0.00
Assets:Investments:Retirement  asset                0.00
Equity:Opening Balances        equity               0.00
Expenses:Entertainment         expense              0.00
Expenses:Food:Dining           expense              0.00
Expenses:Food:Groceries        expense              0.00
Expenses:Housing:Rent          expense              0.00
...
Income:Salary                  income               0.00
Liabilities:Credit Card        liability            0.00
Liabilities:Loans              liability            0.00
```

Accounts are **hierarchical** (`Expenses:Food:Groceries`) and **typed** — every
account is an `asset`, `liability`, `equity`, `income`, or `expense`. The `cash`
flag marks accounts the cash-flow statement should explain (checking, savings,
wallet). Reshape the chart freely:

```sh
beans account add Expenses:Pets --type expense --desc "Vet, food, toys"
```

```text
Added expense account Expenses:Pets (cash-flow: operating)
```

## 3. Record your opening balances

Before tracking new activity, tell `beans` what you already own and owe. Like a
company's opening entry, this is one balanced transaction: assets and
liabilities on one side, `Equity:Opening Balances` soaking up the difference.

```sh
beans tx add --date 2026-01-01 --desc "Opening balances" \
    --post Assets:Checking 5000 \
    --post Assets:Savings 10000 \
    --post "Liabilities:Credit Card" -1200 \
    --post "Equity:Opening Balances"        # omitted amount auto-balances
```

```text
Recorded transaction #1
#1  2026-01-01  Opening balances
    Assets:Checking            5,000.00
    Assets:Savings            10,000.00
    Liabilities:Credit Card   -1,200.00
    Equity:Opening Balances  -13,800.00
```

The heart of double-entry: a transaction is a list of **postings that sum to
zero** (debits positive, credits negative). We gave four postings but only three
amounts — leaving one `--post` without an amount lets `beans` **auto-balance**
it. Here equity absorbs $13,800, exactly net assets.

## 4. Capture everyday activity

The general `tx add` form handles any complexity, but most days you reach for
three shortcuts — `spend`, `earn`, and `transfer` — each a balanced two-leg
entry.

```sh
beans earn 6000 Salary --date 2026-01-15 --desc "January paycheck"
beans spend 1800 Rent --date 2026-01-02
beans spend 450.25 Groceries --payee "Market" --date 2026-01-10
beans spend 54.20 Dining --from "Credit Card" -m "Pizza night" --date 2026-01-12
beans transfer 1000 Checking Savings --date 2026-01-20
```

```text
Recorded transaction #2: 2026-01-15  January paycheck  $6,000.00
    Assets:Checking  <-  Income:Salary
Recorded transaction #3: 2026-01-02  Spending: Rent  $1,800.00
    Expenses:Housing:Rent  <-  Assets:Checking
Recorded transaction #4: 2026-01-10  Spending: Groceries  $450.25
    Expenses:Food:Groceries  <-  Assets:Checking
Recorded transaction #5: 2026-01-12  Pizza night  $54.20
    Expenses:Food:Dining  <-  Liabilities:Credit Card
Recorded transaction #6: 2026-01-20  Transfer: Checking -> Savings  $1,000.00
    Assets:Savings  <-  Assets:Checking
```

A few things to notice:

- **Fuzzy account names.** We wrote `Groceries`, not
  `Expenses:Food:Groceries` — `beans` resolves the short form for you. Same with
  `Rent`, `Dining`, and `Salary`.
- **`spend`/`earn` default the cash side to checking.** The dining charge went
  to the credit card instead because we said `--from "Credit Card"`. To change
  the default for good: `beans config set default_account Savings`.
- **`-m` is shorthand for `--desc`** on the shortcuts.

## 5. See where you stand

Run `beans` with no command for a one-screen dashboard:

```sh
beans status
```

```text
BEANS STATUS — 2026-06-12

Cash & equivalents                             $18,749.75
Net worth               $17,495.55  (+$0.00 over 30 days)

This month (June 2026)
  Income                                            $0.00
  Expenses                                          $0.00
  Net                                               $0.00
```

(Our activity is all back in January, so "this month" is empty — that's
expected.) For the full picture grouped by account type:

```sh
beans balances
```

```text
ACCOUNT BALANCES
As of: 2026-06-12

Assets
  Checking            7,749.75
  Savings            11,000.00
------------------------------
Total Assets        $18,749.75

Liabilities
  Credit Card         1,254.20
------------------------------
Total Liabilities    $1,254.20
...
Expenses
  Food
    Dining               54.20
    Groceries           450.25
  Housing
    Rent              1,800.00
------------------------------
Total Expenses       $2,304.45
```

To follow a single account like a checkbook register — every entry with a
running balance — use `register`:

```sh
beans register Checking
```

```text
REGISTER — Assets:Checking

ID  Date        C  Description                    Counter-account            Amount   Balance
---------------------------------------------------------------------------------------------
 1  2026-01-01     Opening balances               Assets:Savings, ...      5,000.00  5,000.00
 3  2026-01-02     Spending: Rent                 Expenses:Housing:Rent   -1,800.00  3,200.00
 4  2026-01-10     Spending: Groceries            Expenses:Food:Groceries   -450.25  2,749.75
 2  2026-01-15     January paycheck               Income:Salary            6,000.00  8,749.75
 6  2026-01-20     Transfer: Checking -> Savings  Assets:Savings          -1,000.00  7,749.75
```

## 6. Read the three statements

This is where double-entry pays off: the same ledger rolls up into the three
statements analysts use for any company.

**Income statement** — what you earned and spent over a period, each line as a
percentage of total income:

```sh
beans report income --period 2026-01
```

```text
INCOME STATEMENT
For the period: January 2026

Income
  Salary         6,000.00  100.0%
---------------------------------
Total Income    $6,000.00  100.0%

Expenses
  Food
    Dining          54.20    0.9%
    Groceries      450.25    7.5%
  Housing
    Rent         1,800.00   30.0%
---------------------------------
Total Expenses  $2,304.45   38.4%
---------------------------------
Net Income      $3,695.55   61.6%
```

**Balance sheet** — what you own, owe, and are worth at a moment in time:

```sh
beans report balance --date 2026-01-31
```

```text
BALANCE SHEET
As of: 2026-01-31

Assets
  Checking              7,749.75
  Savings              11,000.00
--------------------------------
Total Assets          $18,749.75

Liabilities
  Credit Card           1,254.20
--------------------------------
Total Liabilities      $1,254.20

Equity
  Opening Balances     13,800.00
  Retained Earnings     3,695.55
--------------------------------
Total Equity          $17,495.55
--------------------------------
Liabilities + Equity  $18,749.75
Net Worth             $17,495.55
```

Notice **Retained Earnings** of $3,695.55 — exactly January's net income.
`beans` computes it on the fly so that **Assets = Liabilities + Equity** always
holds, even though you never "closed" the income statement.

**Cash flow statement** — where cash actually moved, classified into operating,
investing, and financing activities (direct method):

```sh
beans report cashflow --period 2026-01
```

```text
STATEMENT OF CASH FLOWS
For the period: January 2026

Cash Flows from Operating Activities
  Expenses:Food:Groceries                -450.25
  Expenses:Housing:Rent                -1,800.00
  Income:Salary                         6,000.00
------------------------------------------------
Net Cash from Operating Activities     $3,749.75
...
Net Change in Cash                    $18,749.75
Cash at Beginning of Period                $0.00
Cash at End of Period                 $18,749.75
```

The pizza night is *missing* from the cash flow statement on purpose: it was
charged to the credit card, so no cash moved. It shows up on the income
statement (you incurred the expense) but won't hit cash flow until you pay the
card — exactly how accrual vs. cash accounting should differ.

## What just happened

Every dollar you entered landed in two places, the books stayed balanced to the
cent, and three professional statements emerged for free. The accountant's
sanity check confirms it:

```sh
beans report trial --date 2026-01-31
```

```text
TRIAL BALANCE
As of: 2026-01-31
...
-----------------------------------------------
Totals                   $21,054.20  $21,054.20
```

Debits equal credits. The books tie.

## Next steps

- Made a typo? `beans tx void <id>` reverses an entry (keeping the audit
  trail), and `beans undo` voids the most recent one.
- **[Budgeting a month →](02-budgeting-a-month.md)** — put targets on those
  expense categories and track yourself against them.
- Reference: [Concepts](../../README.md#concepts) and
  [Financial statements](../../README.md#financial-statements) in the main
  README.
