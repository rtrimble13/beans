# Loans & liquidity

**What you'll accomplish:** classify what you own and owe as **current** (within
a year) or **non-current** (beyond it), finance a car with an amortizing loan,
and read a **classified balance sheet** plus the **working-capital ratios**
(current ratio, quick ratio) that fall out of it. By the end you'll know how
`beans` splits a long-term debt into the part due this year and the part due
later — automatically, from the loan's amortization schedule.

**Prerequisites:** comfort with [Getting started](01-getting-started.md) — you
should know `init`, the chart of accounts, and `tx add`.

```sh
export BEANS_LEDGER=/tmp/loan-demo.db
```

## 1. Current vs non-current

Every asset and liability carries a **liquidity** classification. Cash, a
checking balance, and a credit-card balance are **current** — realizable or due
within a year. A retirement account, a house, a mortgage are **non-current**.
Everything defaults to `current`; the starter chart already marks the obvious
long-term accounts (`--noncurrent`), which you can see in the `Flags` column of
`beans account list`. You set it yourself with `--noncurrent` / `--current` on
`account add` and `account modify`.

Start from opening balances that mix the two — cash and a credit-card balance
(current) alongside a retirement account (non-current):

```sh
beans init
beans tx add --date 2026-01-01 --desc "Opening balances" \
    --post Assets:Checking 6000 --post Assets:Savings 4000 \
    --post Assets:Investments:Retirement 40000 \
    --post "Liabilities:Credit Card" -900 \
    --post "Equity:Opening Balances"
```

## 2. Finance a car

A car is a long-term asset, and the loan against it is a long-term liability —
so we add both as `--noncurrent`. Buy a $25,000 car with $5,000 down and $20,000
financed:

```sh
beans account add "Assets:Vehicle" --type asset --noncurrent
beans account add "Liabilities:Auto Loan" --type liability
beans tx add --date 2026-02-01 --desc "Buy car" \
    --post "Assets:Vehicle" 25000 --post Assets:Checking -5000 \
    --post "Liabilities:Auto Loan" -20000
beans earn 5000 Salary --date 2026-02-05 --desc "Feb paycheck"
```

## 3. Attach the amortization schedule

Tell `beans` the loan's terms and it derives the monthly payment and the full
schedule:

```sh
beans loan add --account "Auto Loan" --principal 20000 --rate 6 --term 60 \
    --start 2026-02-01
```

```text
Attached loan to Liabilities:Auto Loan: $20,000.00 at 6% over 60 months, payment $386.66 (marked non-current)
```

`beans` solved for the $386.66 payment (give `--payment` instead of `--term` to
solve for the number of payments). Because the loan runs beyond a year it's
long-term, so the account is **marked non-current**. Inspect the schedule:

```sh
beans loan show "Auto Loan"
```

```text
AMORTIZATION SCHEDULE — Liabilities:Auto Loan
Principal $20,000.00 at 6.000% over 60 months, payment $386.66

 #  Date        Payment  Interest  Principal    Balance
-------------------------------------------------------
 1  2026-02-01   386.66    100.00     286.66  19,713.34
 2  2026-03-01   386.66     98.57     288.09  19,425.25
 3  2026-04-01   386.66     97.13     289.53  19,135.72
 4  2026-05-01   386.66     95.68     290.98  18,844.74
 5  2026-06-01   386.66     94.22     292.44  18,552.30
 6  2026-07-01   386.66     92.76     293.90  18,258.40
...
```

Early payments are mostly interest; principal takes over as the balance falls —
standard amortization.

## 4. The current portion of long-term debt

Here's the point of the loan model. Only the principal due in the **next twelve
months** is a current liability; the rest is long-term. `loan list` shows the
split:

```sh
beans loan list --date 2026-06-30
```

```text
LOANS
As of: 2026-06-30

Account                  Rate  Payment    Balance   Current  Non-current  Left
------------------------------------------------------------------------------
Liabilities:Auto Loan  6.000%   386.66  20,000.00  3,625.40    16,374.60    55
```

Of the $20,000 owed, **$3,625.40** comes due within a year and **$16,374.60**
later. `beans` computes that from the schedule — no manual tracking — and always
caps it at the real ledger balance so the two pieces sum to what you actually
owe.

## 5. The classified balance sheet

`report balance` puts it all together, splitting each side into current and
non-current:

```sh
beans report balance --date 2026-06-30
```

```text
BALANCE SHEET
As of: 2026-06-30

Assets
  Current Assets
    Checking                          6,000.00
    Savings                           4,000.00
  Current Assets subtotal           $10,000.00
  Non-current Assets
    Investments
      Retirement                     40,000.00
    Vehicle                          25,000.00
  Non-current Assets subtotal       $65,000.00
----------------------------------------------
Total Assets                        $75,000.00

Liabilities
  Current Liabilities
    Auto Loan                         3,625.40
    Credit Card                         900.00
  Current Liabilities subtotal       $4,525.40
  Non-current Liabilities
    Auto Loan                        16,374.60
  Non-current Liabilities subtotal  $16,374.60
----------------------------------------------
Total Liabilities                   $20,900.00

Equity
  Opening Balances                   49,100.00
  Retained Earnings                   5,000.00
----------------------------------------------
Total Equity                        $54,100.00
----------------------------------------------
Liabilities + Equity                $75,000.00
Net Worth                           $54,100.00
```

The **Auto Loan appears on both sides** — $3,625.40 under current liabilities,
$16,374.60 under non-current — while the retirement account and the car sit in
non-current assets. The split is applied to the true ledger balance, so the
statement still balances to the cent. (Prefer the old by-type-only view? Add
`--flat`.)

## 6. Liquidity ratios

With current and non-current separated, `analyze` can report the working-capital
ratios an analyst computes for a company:

```sh
beans analyze --from 2026-01-01 --to 2026-06-30
```

```text
...
Working Capital
  Current Assets        $10,000.00
  Current Liabilities    $4,525.40
  Working Capital        $5,474.60

Ratios
  Current Ratio               2.21
  Quick Ratio                 2.21
  Debt / Assets              27.9%
...
```

- **Current ratio** (current assets ÷ current liabilities) = **2.21** — you have
  $2.21 of near-term assets for every $1 of near-term obligations.
- **Quick ratio** = **2.21** — same idea but the numerator is *cash only*
  (a stricter test). Here it matches the current ratio because every current
  asset is already cash; hold a non-cash current asset (a prepaid, a receivable)
  and the quick ratio would come in lower.
- **Working capital** = current assets − current liabilities = **$5,474.60**, the
  cushion left after covering everything due this year.

Contrast this with vignette 02, where the same ratios read `n/a` — that ledger
carried no current liabilities, so there was nothing to divide by.

## 7. Make a payment

`loan pay` posts one instalment as a balanced transaction, splitting it into
principal and interest (interest computed on the actual outstanding balance):

```sh
beans loan pay "Auto Loan" --date 2026-02-01 --from Checking
```

```text
Recorded transaction #4: paid $386.66 on Liabilities:Auto Loan ($286.66 principal + $100.00 interest); balance $19,713.34
```

The interest ($100.00 = $20,000 × 6% ÷ 12) lands in `Expenses:Interest`, the
principal pays down the liability, and cash goes out — all double-entry, so the
books stay balanced. Because interest is computed on the real balance, extra or
missed payments stay accurate.

## What just happened

You classified assets and liabilities by liquidity, modeled a loan once, and got
a classified balance sheet plus current/quick/working-capital metrics for free —
with the current-portion-of-long-term-debt split derived from the amortization
schedule rather than tracked by hand. The ledger balance stays the source of
truth throughout; the schedule only decides how to split it.

## Next steps

- `beans loan pay` on a schedule, or automate the payment with a
  [recurring rule](04-recurring-goals-investing.md).
- `beans account modify <account> --current | --noncurrent` to reclassify a
  non-loan account (a prepaid, an emergency fund) as your view changes.
- Reference: [Accounts](../../README.md#accounts),
  [Loans](../../README.md#loans), and [Analysis](../../README.md#analysis) in the
  main README, and the `loan` / `analyze` sections of
  [the manual](../MANUAL.md).
```
