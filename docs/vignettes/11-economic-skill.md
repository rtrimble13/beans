# An economic balance sheet with Claude

**What you'll accomplish:** turn "am I actually going to be all right?" into a
written, testable plan — and find out which of your own assumptions the answer
really hangs on. You'll use the `beans-economic` **agent skill** for Claude
Code, and you'll run every command it runs.

**Prerequisites:** [Getting started](01-getting-started.md) and the
[economic balance sheet vignette](06-economic-balance-sheet.md) — this assumes
you know what human capital and future consumption *are*. Install instructions:
[`docs/claude-skill-setup.md`](../claude-skill-setup.md).

> **Nothing here is posted to your ledger.** The forward-looking inputs are
> assumptions by design. The only file the skill writes is a plan document you
> approve.

## 0. A ledger to work from

Reuse the trend vignette's throwaway ledger — thirteen months of a household
earning about $6,600 and spending about $3,150:

```sh
./sample-trend-ledger.sh /tmp/econ-demo.db
export BEANS_LEDGER=/tmp/econ-demo.db
```

## 1. The number, and why it is not an answer

`beans` will tell you your economic net worth right now:

```sh
beans economic npv
```

```text
Financial capital (net)      63,142.00
+ Human capital           1,328,521.66
- Future consumption       -878,948.86
--------------------------------------
Economic net worth (NPV)   $512,714.80
```

Half a million dollars ahead. Now watch what happens when you change one
assumption — and *only* an assumption, the ledger is untouched:

```sh
beans economic npv --growth 3%       #  $1,069,479.92
beans economic npv --inflation 3%    #    -$114,889.96
beans economic npv --work-years 15   #     $96,467.61
```

Three percent inflation — an unremarkable number — takes this household from
half a million ahead to **a hundred thousand behind**. Nothing is wrong with
the arithmetic. The figure simply is not a fact about the household; it is a
fact about the inputs, and the default inputs were nobody's considered opinion.

That is the job. Not to compute the number — `beans` does that — but to find
out what it rests on.

## 2. Preflight — what is actually known

```sh
cd ~/.claude/skills/beans-economic/scripts
./preflight.py --lookback 12 --work-years 25
```

```text
accounting_net_worth: 63142.00
auto_basis          : monthly_income 6300.00, monthly_expense 3146.50 (12 months)
history             : 2025-08-01 .. 2026-09-01, 13 months, 91 transactions
projection_leverage : 13 months of history, 300 months projected — 1:23
warn: the run-rate is not flat — Expenses:Food:Groceries, Expenses:Insurance,
      Expenses:Entertainment moved more than 15% across the window.
```

Two things worth pausing on.

**`accounting_net_worth: 63,142.00` is the only figure on the statement that is
not an assumption.** Everything else — human capital, future consumption, the
lot — is a model output. Keep the two apart in your head and in your sentences.

**1:23.** Thirteen months of history are about to be projected twenty-five
years forward. That is not a reason to stop; it *is* a reason to say so every
time the human-capital figure gets quoted. And the run-rate is drifting, which
means a flat annuity off today's number will be wrong for the entire horizon —
in a known direction.

## 3. The interview

Six lines. Two the ledger can estimate. Four it cannot know anything about at
all — no amount of bookkeeping reveals whether you have a pension.

```
build my economic balance sheet
```

The conversation covers, one at a time: when you stop working and whether
income changes before then; whether spending changes when you stop; a pension
(from when, how much, indexed?); an inheritance you would genuinely plan
around; a bequest you intend to leave; and anything else large and future —
care costs, tuition, a settlement.

The last one is worth asking about precisely because
`beans economic create-template` has **no section for it**; the skill writes
one.

Suppose the answers are: retire September 2046; spending drops about 20% then;
a workplace pension of $2,400/month, index-linked, from the same date; no
inheritance being planned around; no specific bequest; nothing else known.
Those become:

```json
{
  "as_of": "2026-09-04",
  "settings": {"discount_rate": "3%", "income_growth": "1%",
               "inflation": "2%", "work_years": 20, "live_years": 40},
  "lines": {
    "income": {"mode": "stream", "note": "Salary as now; stops in September 2046.",
      "segments": [{"from": "2026-09-01", "amount": "6600", "growth": "1%"},
                   {"from": "2046-09-01", "amount": "0"}]},
    "consumption": {"mode": "stream", "note": "Drops ~20% once commute and mortgage go.",
      "segments": [{"from": "2026-09-01", "amount": "3150", "growth": "2%"},
                   {"from": "2046-09-01", "amount": "2520", "growth": "2%"}]},
    "pension": {"mode": "stream", "note": "Workplace pension, index-linked.",
      "segments": [{"from": "2046-09-01", "amount": "2400", "growth": "2%"}]},
    "inheritance": {"mode": "none", "note": "Not planning around it."},
    "bequest": {"mode": "none", "note": "Nothing specific intended."},
    "other": {"mode": "none", "note": "Nothing large and known."}
  }
}
```

Note what the three `none` lines carry: a **reason**. An excluded pension is a
claim that there is no pension, and the skill will not let that be silent.

## 4. Build the document

```sh
./build_config.py answers.json -o plan.md
```

```text
wrote plan.md
  economic net worth: 666804.20 (accounting: 63142.00)
  modelled as zero: Expected inheritance, Bequests, Other obligations
```

It validated every field, refused any ambiguous rate, chose the right table
shape per mode, and — before the file landed — proved it parses by running
`beans economic npv --file` against a temporary copy. A document this skill
wrote is always one `beans` can read.

It also will not overwrite an existing plan. Yours is an audit trail; keep it.

```sh
beans economic bs --file plan.md
```

```text
Economic Assets
  Financial Capital             65,042.00
  Human Capital              1,299,342.20
  Pension / Benefits           286,901.59
-----------------------------------------
Total Economic Assets       $1,651,285.79

Economic Liabilities
  Financial Liabilities          1,900.00
  Future Consumption           982,581.59
-----------------------------------------
Total Economic Liabilities    $984,481.59

-----------------------------------------
Economic Net Worth            $666,804.20
Accounting Net Worth           $63,142.00
```

## 5. Stress-test it — and read the result carefully

```sh
./sensitivity.py --file plan.md
```

```text
drivers : ['discount_rate', 'live_years']
inert   : ['income_growth', 'inflation', 'work_years']
flips   : {}

  discount rate                  501,778.92 ..   781,228.09   span 279,449.17
      (1% → 781,228.09 … 7% → 501,778.92; monotonic on this plan)
  income growth                  666,804.20 ..   666,804.20   span       0.00
  inflation                      666,804.20 ..   666,804.20   span       0.00
  years until you stop working   666,804.20 ..   666,804.20   span       0.00
  planning horizon               660,636.49 ..   673,619.15   span  12,982.66
```

Compare that with the same sweep before the interview, on the `auto` defaults:

```text
drivers : ['inflation', 'income_growth', 'work_years', 'live_years', 'discount_rate']
flips   : inflation → negative above 2.5962%

  inflation                      span 971,534.25
  income growth                  span 811,655.59
  years until you stop working   span 724,726.15
```

**The plan did not become immune to inflation.** Inflation went *inert*. Every
line is now an explicit schedule carrying its own growth, so the global
`inflation` setting no longer feeds anything — sweeping it moves nothing
because it is disconnected, not because the plan is robust.

This is the single easiest way to fool yourself with this tool, and it is why
the skill reports `inert` separately from a small span. A zero span is not a
result.

### Testing it properly

On a pinned plan you test inflation by changing the schedule and comparing two
documents:

```sh
# consumption segments at 3% growth instead of 2%
./build_config.py answers-inflation.json -o inflation.md
./sensitivity.py --file plan.md --compare inflation.md
```

```text
economic_net_worth       666,804.20 ->   566,243.32   -100,560.88
future_consumption       982,581.59 -> 1,083,142.47   +100,560.88
```

One extra point of inflation on spending costs **$100,561** in today's dollars.
That is the real answer to "how exposed am I to inflation?", and it took a
scenario, not a sweep.

## 6. A decision, priced

```
what would retiring five years earlier cost me?
```

A second document, then a diff:

```text
economic_net_worth      666,804.20 ->   540,012.88   -126,791.32
human_capital         1,299,342.20 -> 1,020,007.54   -279,334.66
future_consumption      982,581.59 ->   949,838.53    -32,743.06
other_benefits          286,901.59 ->   406,701.87   +119,800.28
financial_capital        65,042.00 ->    65,042.00         +0.00
```

Five years costs **$126,791** in today's dollars — and the decomposition is the
interesting part: $279,335 of forgone earnings, offset by $119,800 of pension
drawn five years earlier and $32,743 of lower lifetime spending. Financial
capital does not move, because the books are the books.

That delta is also more robust than either level, since both scenarios share
every other assumption.

## 7. The briefing

```text
ECONOMIC BALANCE SHEET — 2026-09-04

Accounting net worth (from the books):   $63,142.00
Economic net worth (model output):      $666,804.20

It rests on: retirement Sept 2046, spending -20% at retirement, a $2,400/mo
             index-linked pension, 3% discount, 2% inflation, 40-year horizon.
Backed by:   13 months of history projected 25 years forward (1:23), on a
             run-rate that is currently drifting upward.

What moves it, most first:
  1. Discount rate — $781,228 at 1% down to $501,779 at 7%, monotonic here.
     (On the auto defaults this same sweep is NOT monotonic — it peaks near
     3%. Which shape you get depends on the horizons in play, so check.)
  2. Planning horizon — $660,636 to $673,619 across ±10 years.
  Inert: income growth, inflation, working years — your schedules pin them.
  Tested separately: +1pt inflation on spending costs $100,561.

Nothing in the swept ranges takes this negative.

Excluded (modelled as zero): expected inheritance (not planning around it),
bequests (nothing intended), other obligations (nothing known).

Not licensed financial advice.
```

## What you actually got — and what it refused to do

A written plan, a number, and — the point — a ranked account of what that
number depends on. Along the way the skill declined to:

- state $666,804.20 without the assumptions that produced it;
- let three unmentioned lines become silent zeros;
- report inflation as "no effect" when it was merely disconnected;
- call a higher discount rate "conservative" without checking the direction —
  on the auto defaults that sweep peaks in the middle, so the direction is not
  something you can assume;
- accept a rate written as `0.03`, which `beans` reads as 0.03%, not 3%;
- overwrite `plan.md` when the second scenario was built;
- write anything at all to the ledger.

## Where to go next

- **Keep the documents.** `base.md`, `retire-early.md`, `no-pension.md`. The
  diff between two of them is the cost of a decision in today's dollars, and
  that is the most useful thing this tool produces.
- **Revisit after a real change** — a raise, a new pension, a house. The plan
  is a document, not a one-off calculation.
- **Fix the inputs first.** If preflight flags a drifting run-rate, the
  [`beans-report` skill](10-reporting-skill.md) will tell you what is drifting
  and by how much, which makes the next set of answers better.
- **Keep it private.** A plan document states your retirement date, your
  pension and any inheritance you expect. Keep it out of any repository you
  push.

Cleanup:

```sh
rm /tmp/econ-demo.db plan.md inflation.md
```
