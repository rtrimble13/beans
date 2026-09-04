# A trend briefing with Claude

**What you'll accomplish:** hand Claude a year of ledger history and get back
four findings that matter — a grocery drift hiding under normal noise, a raise
that arrived as a step, one large bill that is *not* a trend, and an insurance
payment that quietly stopped and nobody noticed. You'll use the `beans-report`
**agent skill** for Claude Code, and you'll run every command it runs.

**Prerequisites:** [Getting started](01-getting-started.md). Helpful but not
required: [Budgeting a month](02-budgeting-a-month.md) and
[Recurring, goals & investing](04-recurring-goals-investing.md). Install
instructions are in [`docs/claude-skill-setup.md`](../claude-skill-setup.md).

> **This skill never writes.** Everything below is a read-only `beans` command
> or a helper script. Where a finding implies a change, the skill prints the
> command and you run it.

## Why this needs a skill at all

`beans report trend` will line up the periods for you — that part is a command
now, and if all you want is the numbers side by side, run it and stop reading.

What it cannot do is tell you which of those movements mean anything. A column
of twelve grocery figures does not say whether it is a drift, one bad month, or
noise; it does not know that the insurance payment stopping is a problem rather
than a saving; and it will happily hand you a category series over a ledger
where a third of the spending is filed under `Expenses:Other`. That reading is
what this skill does, and it is where the mistakes live.

Here is the flavour of mistake. It is 4 September 2026. Ask `beans` about the
current month:

```sh
beans report income --period this-month
```

```text
INCOME STATEMENT
For the period: September 2026

Income
----------------------------
Total Income         $0.00

Expenses
  Housing
    Rent          1,800.00
----------------------------
Total Expenses   $1,800.00
----------------------------
Net Income      -$1,800.00
```

Rent has posted. The paycheck has not — it lands on the 15th. Now the ratios:

```sh
beans analyze --period this-month --json   # savings_rate: null, liquidity_months: 4.7
beans analyze --period ytd --json          # savings_rate: 45.8, liquidity_months: 18.9
```

Every one of those numbers is correct. Put the first row at the end of a
twelve-month series and the honest-looking conclusion is *"your income has
collapsed to zero and your runway has fallen from 18.9 months to 4.7."* Both
halves are false, and both are the kind of false that ruins someone's evening.

The first rule — in the skill *and*, since beans 1.1, in `report trend` itself
— is that a period which has not fully elapsed is never trended. Most of what
follows is rules of that shape, and the ones that could be moved into the
product have been.

## 0. A ledger with a year of history

[`sample-trend-ledger.sh`](sample-trend-ledger.sh) builds a throwaway ledger
with thirteen months of activity — deliberately containing one of each thing
worth finding:

```sh
./sample-trend-ledger.sh /tmp/trend-demo.db
export BEANS_LEDGER=/tmp/trend-demo.db
```

```text
Seeded /tmp/trend-demo.db — 13 months to 2026-09-04.
```

Inside it: a raise in March, groceries creeping up by about $22 a month under
±$18 of noise, a streaming subscription that starts in January, an insurance
payment that stops after April, one $2,400 medical bill, and flat rent.

`beans report trend` will show you all twelve months of it:

```sh
beans report trend --periods 12
```

```text
TREND
Last 12 months: 2025-09 to 2026-08
2026-09 is still in progress and is excluded.

Period     Income  Expenses       Net  Savings
----------------------------------------------
2025-09  6,000.00  2,889.00  3,111.00    51.9%
2025-10  6,000.00  2,883.00  3,117.00    52.0%
2025-11  6,000.00  2,890.00  3,110.00    51.8%
2025-12  6,000.00  2,940.00  3,060.00    51.0%
2026-01  6,000.00  2,943.00  3,057.00    51.0%
2026-02  6,000.00  2,953.00  3,047.00    50.8%
2026-03  6,600.00  5,460.00  1,140.00    17.3%
2026-04  6,600.00  3,029.00  3,571.00    54.1%
2026-05  6,600.00  2,957.00  3,643.00    55.2%
2026-06  6,600.00  2,912.00  3,688.00    55.9%
2026-07  6,600.00  2,925.00  3,675.00    55.7%
2026-08  6,600.00  2,977.00  3,623.00    54.9%
----------------------------------------------
Average  6,300.00  3,146.50  3,153.50    50.1%

BY ACCOUNT (largest change first)
Account                        First      Last   Change   Average
-----------------------------------------------------------------
Income:Salary               6,000.00  6,600.00   600.00  6,300.00
Expenses:Food:Groceries       530.00    746.00   216.00    643.00
Expenses:Insurance            145.00      0.00  -145.00     96.67
Expenses:Entertainment          0.00     38.00    38.00     25.33
Expenses:Food:Dining          210.00    187.00   -23.00    199.75
Expenses:Housing:Utilities    204.00    206.00     2.00    181.75
Expenses:Health                 0.00      0.00     0.00    200.00
Expenses:Housing:Rent       1,800.00  1,800.00     0.00  1,800.00
```

Every number you need is on that page. Now try to read it.

The insurance row shows `-145.00`, which looks like a saving — it is a payment
that stopped. Groceries `+216.00` and dining `-23.00` are both "changes", but
one is a twelve-month drift and the other is next month's noise; first-versus-
last cannot tell them apart, and would have called dining a $23 fall even if
the middle ten months had been identical. `Expenses:Health` reads **First 0.00,
Last 0.00, Change 0.00** — and a $200 average, because a $2,400 bill in March
is sitting inside it, invisible in every column but one. And the March savings
rate of 17.3% is that same bill, not a lapse in discipline.

That gap — between having the numbers and knowing which of them are news — is
what the rest of this walkthrough is.

## 1. Ask

```
run my monthly financial review against /tmp/trend-demo.db — what's been happening?
```

The skill triggers on the *span*: "what's been happening", "over the last
year", "is X creeping up". A question about one month ("what did I spend in
August?") is answered directly instead — that's what `beans report` and the
MCP server are for.

## 2. Preflight — can this ledger support a trend read?

```sh
cd ~/.claude/skills/beans-report/scripts
./preflight.py --months 12 -f /tmp/trend-demo.db
```

```json
{
  "report": "beans-report/preflight",
  "generated": "2026-09-04",
  "last_complete_period": "2026-08",
  "excluded_partial": "2026-09",
  "window": ["2025-09", "2025-10", "…", "2026-07", "2026-08"],
  "closed_through": null,
  "transactions": 91,
  "first_transaction": "2025-08-01",
  "periods_covered": 12,
  "uncategorized": {"amount": "0.00", "total_expenses": "37758.00", "pct": "0.0"},
  "recur": 1,
  "warnings": ["no budgets are set — budget calibration is unavailable; …"],
  "blockers": [],
  "ok": true
}
```

This runs *before* any analysis, because two problems are invisible once a
chart has been drawn:

- **`excluded_partial: "2026-09"`** — the trap above, settled once, in one
  place, rather than judged again at every step.
- **`uncategorized.pct`** — if a quarter of your spending sat in
  `Expenses:Other`, a per-category trend would measure how consistently you
  file receipts. Above 25% the skill blocks category findings and offers
  totals instead. Here it is 0%.

It also counts how far your history actually reaches. Ask for twelve months of
a ledger that starts in June and nine of them are structural zeros, which look
exactly like thrift. Exit status 1 means a blocker; the warnings belong in the
briefing either way.

## 3. Gather — one call, not twelve

```sh
./series.py --months 12 --ratios -f /tmp/trend-demo.db -o /tmp/series.json
```

```text
wrote /tmp/series.json — 12 months (2025-09 … 2026-08)
```

```json
{
  "report": "beans-report/series",
  "grain": "month",
  "count": 12,
  "source": "beans report trend",
  "window": {"first": "2025-09", "last": "2026-08"},
  "excluded_partial": "2026-09"
}
```

Underneath, that is one `beans report trend --json`, one `networth`, and (with
`--ratios`) twelve `beans analyze` — every figure copied verbatim. The script
does **no** arithmetic, so any number it emits can be traced back to a command
you can re-run. The `source` field says where the series came from: on a beans
older than 1.1 there is no `report trend`, and the script falls back to twelve
`report income` calls that produce byte-identical output.

Two series it produced:

```text
Expenses:Food:Groceries  530  553  558  600  601  631  668  658  706  710  755  746
Expenses:Insurance       145  145  145  145  145  145  145  145    0    0    0    0
```

Look at the groceries row and try to say, by eye, whether that is a trend or a
run of ordinary months. That difficulty is the whole point.

## 4. Classify

```sh
./trend.py /tmp/series.json
```

Each account gets one verdict. Groceries:

```json
{
  "name": "Expenses:Food:Groceries",
  "classification": "drift",
  "direction": "up",
  "latest": "746.00",
  "median": "644.50",
  "monthly_slope": "+21.35",
  "noise_width": "10.40",
  "change": "+234.85",
  "annualized": "+256.20",
  "outliers": [],
  "pct_of_typical_income": "3.7"
}
```

The seeded drift was $22/month. The fit recovered $21.35 — through ±$18 of
noise, because the slope is a *median of pairwise slopes* (Theil–Sen) and the
noise band is a median absolute deviation. Neither can be dragged by an
outlier, which is exactly what the $2,400 medical bill is.

The full ranking:

```text
Expenses:Health             one-off   +2400.00   latest=   0.00
total_income                step       +600.00   latest=6600.00
Income:Salary               step       +600.00   latest=6600.00
net_income                  step       +583.00   latest=3623.00
Expenses:Food:Groceries     drift      +234.85   latest= 746.00
Expenses:Insurance          stopped    -145.00   latest=   0.00
total_expenses              step        +64.00   latest=2977.00
```

Six verdicts, each meaning something different:

| Verdict | Here | What it implies |
|---|---|---|
| `drift` | groceries | a standing slope — investigate the cause |
| `step` | salary, from March | one change, flat either side — re-budget around it |
| `one-off` | the $2,400 bill | nothing, except that it distorts averages |
| `new` | the streaming subscription | something started recurring |
| `stopped` | insurance, after April | **a payment that quietly lapsed** |
| `stable` | rent, dining, utilities | say nothing at all |

Rent never moved, so it does not appear. Neither does dining, which wobbles by
±$25 and goes nowhere. A briefing that mentioned them would be longer and worse.

### Why the subscription is missing

The streaming subscription is $38/month, and typical income is $6,300 — so it
sits under the default materiality floor of 1% of income, and is reported only
as a count:

```text
"immaterial_count": 3
```

Two thresholds gate every finding, and they answer different questions.
**Scale** asks whether a move stands out from the series' own noise;
**materiality** asks whether it is big enough for a person to care. Lower the
second and the subscription appears:

```sh
./trend.py /tmp/series.json --floor-pct 0.5
```

```text
Expenses:Entertainment      new         +38.00   latest=  38.00
Expenses:Housing:Utilities  step        -37.00   latest= 206.00
```

That is the dial to turn when a briefing feels too quiet — not the noise
threshold, which is what keeps one vet bill from becoming a trend.

## 5. Infer — the finding that pays for the run

`stopped` on `Expenses:Insurance` is the one `beans` itself can never surface.
The skill cross-checks it against the ledger's standing instructions:

```sh
beans recur list
```

```text
Rule       Frequency  Next Due    Status  Posted  Amount
--------------------------------------------------------
insurance  monthly    2025-09-05  due     0       145.00
```

There is still a rule. It says $145 a month. Nothing has posted against it
since April. That is one of three things — the policy ended, a payment failed,
or the rule was paused and forgotten — and they have very different
consequences. The skill puts the question to you rather than guessing, and if
the answer is the third, it prints `beans recur resume insurance` for **you**
to run.

Notice what it does *not* do: report a $145/month reduction in spending as good
news. Expenses did fall. That is not what happened.

The other inferences work the same way — actuals crossed against something the
ledger already knows:

- **Lifestyle creep.** Income stepped up $600 and total expenses stepped up
  too. The `--ratios` series shows the savings rate: `51.9 … 50.8, 17.3, 54.1
  … 54.9`. That 17.3 is March — the medical bill — and it is a one-off, not a
  collapse in discipline. Saying so is the finding.
- **A stale forecast basis.** `beans forecast` prices groceries at their
  historical *average*; the account is drifting, so the average sits behind the
  latest level and the projection quietly understates. The fix to propose is
  `--method trend`.
- **Budget calibration.** With budgets set, a category over budget in nine
  months of twelve is a wrong number, not a bad habit — and the recalibrated
  `beans budget set` line is printed for you to run.

## 6. The briefing

```text
TREND BRIEFING — 12 months to August 2026     (September excluded: in progress)

Headline: A raise in March lifted income $600/month, but grocery spend has been
drifting up all year and an insurance payment stopped in April.

1. Insurance stopped — $145/month, absent for 4 months (May–Aug). The recurring
   rule still exists and is due. Policy ended, payment failed, or rule paused?
   → if the rule is stale: beans recur resume insurance

2. Groceries drifting — +$21.35/month over 12 months, now $746 (was $530).
   $256/year at this rate; 3.7% of typical monthly income.
   → beans register Expenses:Food:Groceries --period 2026-Q2  to see the payees

3. Salary stepped up — +$600/month from March 2026. Expenses stepped up $64.
   Savings rate 51.9% → 54.9%, so most of the raise was kept.

4. One-off, not a trend — $2,400 medical in March. It is why the March savings
   rate reads 17.3%; the surrounding months are ~51–55%.

Caveats: no budgets set, so no budget calibration. 3 real but immaterial moves
below the $63 floor were not listed.

Not licensed financial advice.
```

Four findings. Each names its classification, its figure, and its window; each
ends in something you can do; none was computed in prose.

## What you actually got — and what it refused to do

You got the series `beans` does not keep, read with rules that are written
down. And the skill declined, without being asked, to:

- trend the month in progress, or report its $0 income as a fall;
- call the $2,400 medical bill a trend, or let it drag the grocery slope;
- report the lapsed insurance payment as a saving;
- list all nine moving accounts when four of them mattered;
- write anything to your ledger — not a budget, not a rule, not a period close.

If any of that seems obvious, run the numbers through a spreadsheet including
September and see which conclusion you reach first.

## Where to go next

- **Different horizons.** `--months 3` and `--months 6` alongside the 12. Where
  they disagree, the disagreement is the finding: a step reads as drift on a
  short window, an acceleration reads as flat on a long one.
- **Quarters.** `--grain quarter --periods 8` for two years, which is the
  minimum before saying anything about seasonality.
- **Keep the briefings.** Ask Claude to write each month's to a dated file. The
  payoff is the *next* run, which reads the previous one and closes the loop —
  "last month I flagged rising groceries; they rose another $9."
- **Fix the inputs.** If preflight blocked on uncategorized spending, the
  [`beans-import` skill](09-claude-skill.md) is how you clear it.
- **Skip the skill entirely** when you just want the numbers:
  `beans report trend --periods 12 --json`, or the `beans_trend` tool from any
  MCP host. `beans ai review --focus trend` puts the same series into a
  CFO-style briefing without leaving the terminal.

Cleanup:

```sh
rm /tmp/trend-demo.db /tmp/series.json
```
