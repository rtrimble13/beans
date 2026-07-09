# The economic balance sheet

**What you'll accomplish:** look past *this month's* net worth to your **lifetime**
net worth. You'll value your **human capital** — the present value of the income
you expect to earn — as an asset, and your **future consumption** as a liability,
producing an **economic balance sheet** that reconciles with the accounting one.
By the end you'll see why a young household that looks broke on paper can be
comfortably in the black once its future earnings are counted, and how to model a
real retirement date, a pension, and a one-off inheritance.

**Prerequisites:** comfort with [Getting started](01-getting-started.md) and the
[classified balance sheet](05-loans-and-liquidity.md) — you should know `init`,
opening balances, and `report balance`.

```sh
export BEANS_LEDGER=/tmp/economic-demo.db
```

## 1. A household that looks underwater

Meet someone early in their career: some cash, a growing retirement account, and
a mortgage that dwarfs both.

```sh
beans init
beans tx add --desc 'Opening balances' \
  --post Assets:Checking 40000 \
  --post Assets:Investments:Retirement 160000 \
  --post Liabilities:Loans -250000 \
  --post 'Equity:Opening Balances'
```

The accounting balance sheet is blunt about it:

```sh
beans report balance
```

```
Total Assets                        $200,000.00
Total Liabilities                   $250,000.00
Net Worth                           -$50,000.00
```

Fifty thousand dollars underwater. But this ignores the most valuable thing this
person owns: **thirty years of future paychecks.**

## 2. Counting human capital

The economic balance sheet discounts those future paychecks to today's dollars
and puts them on the asset side, and does the same for future spending on the
liability side. For a quick estimate, hand it your monthly income and spending
and a few assumptions:

```sh
beans economic bs --rate 3 --work-years 30 --live-years 45 \
                  --growth 1.5 --inflation 2 --income 9000 --expense 4200
```

```
ECONOMIC BALANCE SHEET
As of: 2026-07-09
Discount 3.0% | income growth 1.5% | inflation 2.0% | work 30y | horizon 45y

Economic Assets
  Financial Capital            200,000.00
  Human Capital              2,605,209.61
-----------------------------------------
Total Economic Assets       $2,805,209.61

Economic Liabilities
  Financial Liabilities        250,000.00
  Future Consumption         1,823,346.26
-----------------------------------------
Total Economic Liabilities  $2,073,346.26

-----------------------------------------
Economic Net Worth            $731,863.35
Accounting Net Worth          -$50,000.00
```

Same person, same day — but counting thirty years of income at $9,000/month
(growing 1.5% a year, discounted at 3%) turns a **−$50,000** accounting position
into a **+$731,863** economic one. Human capital, not the checking account, is the
asset that matters most at this stage of life.

The assumptions are yours to set:

- `--rate` is the discount rate. Raise it for a volatile or commission-based
  income (future dollars are less certain), lower it for a tenured salary.
- `--work-years` is how long you'll keep earning; `--live-years` how long you'll
  keep spending.
- `--growth` and `--inflation` grow income and spending each year.

Leave off `--income`/`--expense` entirely and `beans` estimates them from your
ledger's recent run-rate — the same engine behind `forecast`.

`beans economic npv` prints just the bottom line and the pieces behind it, handy
for tracking the number over time.

## 3. A real plan: retirement, then a pension

Flags are fine for a back-of-envelope figure, but a real plan has structure:
income *stops* at retirement, and a pension *starts*. Capture that in a config
document. Generate a starting template — pre-filled with your ledger's
run-rates — and open it up:

```sh
beans economic create-template -o economic.md
```

Edit it to say: earn $9,000/month (growing 1.5%) until retirement in 2056, then
nothing; spend $4,200/month (growing with inflation) for life; and collect a
$3,000/month pension once retired. The result looks like this:

```
## Settings

| Field | Value |
|---|---|
| as_of | 2026-07-09 |
| discount_rate | 3.0% |
| work_years | 30 |
| live_years | 45 |
| income_growth | 1.5% |
| inflation | 2.0% |

## Human capital — future income

Mode: stream

| From (date) | Amount (monthly) | Growth |
|---|---|---|
| 2026-07-01 | 9,000 | 1.5% |
| 2056-07-01 | 0 | 0% |

## Future consumption — spending

Mode: scalar

| Amount (monthly) | Growth | Years |
|---|---|---|
| 4,200 | 2.0% | 45 |

## Pension / benefits

Mode: stream

| From (date) | Amount (monthly) | Growth |
|---|---|---|
| 2056-07-01 | 3,000 | 0% |
```

Each line has a **`Mode:`**: `auto` estimates it from your ledger, `scalar` is a
flat/growing amount, `stream` is a dated schedule where each value prevails until
the next date (so the income row of `0` in 2056 is retirement), and `none`
excludes it. A `Date / Amount` table instead of `From / Amount / Growth` models a
one-off lump sum — an inheritance received or a tuition bill paid.

Feed the document to the same command:

```sh
beans economic bs --file economic.md
```

```
ECONOMIC BALANCE SHEET
As of: 2026-07-09
Discount 3.0% | income growth 1.5% | inflation 2.0% | work 30y | horizon 45y

Economic Assets
  Financial Capital            200,000.00
  Human Capital              2,599,473.29
  Pension / Benefits           177,261.06
-----------------------------------------
Total Economic Assets       $2,976,734.35

Economic Liabilities
  Financial Liabilities        250,000.00
  Future Consumption         1,823,346.26
-----------------------------------------
Total Economic Liabilities  $2,073,346.26

-----------------------------------------
Economic Net Worth            $903,388.09
Accounting Net Worth          -$50,000.00
```

Human capital now stops cleanly at retirement, and the pension adds $177,261 of
present value on the asset side. An explicit flag still wins over the document
(`beans economic bs --file economic.md --rate 4` stress-tests a higher discount
rate without editing the file), so you can keep a `base.md` and diff it against a
`retire-early.md` — the difference in economic net worth is the cost of that
choice in today's dollars.

## What just happened

- The **economic balance sheet** extends the accounting one with the present
  value of the future: human capital and benefits as assets, future consumption
  and obligations as liabilities.
- It always **reconciles** with your books:
  `economic net worth = accounting net worth + human capital + benefits −
  future consumption − obligations`. The financial side comes straight from the
  ledger; the forward-looking side is an assumption and is never posted to your
  books.
- Inputs can be a quick **flag** estimate, or a versionable **markdown config**
  where each line is a flat amount, a dated **stream**, or a one-off lump sum —
  as much or as little structure as your question needs.
