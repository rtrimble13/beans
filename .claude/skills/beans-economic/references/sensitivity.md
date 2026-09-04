# Reading the sweeps

## Why a range and not a number

The point estimate is the least informative thing this model produces. Measured
on one ledger, changing one assumption at a time and nothing else:

| Change | Economic net worth |
|---|---:|
| defaults (3% / 0% / 0% / 25y / 40y) | $512,714.80 |
| income growth 3% | $1,069,479.92 |
| inflation 3% | −$114,889.96 |
| work-years 15 | $96,467.61 |

Quoting `$512,714.80` alone is not wrong so much as it is unfinished. The
useful output is the range and the name of whichever input produces most of it.

## `drivers` — what to lead with

Every swept assumption, ranked by the span it produces across its band. On the
worked example: inflation ($971,534) > income growth ($811,656) > working years
($724,726) > horizon ($230,926) > discount rate ($64,536).

Lead the briefing with that order. It tells the user which of their own answers
deserves more thought, which is the actionable part.

## `sign_flips` — the sentence worth having

Found by bisection between the two grid points that straddle zero:

> Your plan goes negative above **2.60%** long-run inflation.

That is concrete, checkable against the world, and impossible to get from a
single run. Report it whenever the boundary falls inside a plausible band —
and note when it does *not*, which is itself reassuring:

> Nothing in the swept ranges takes this negative.

## `inert` — the false-robustness trap

An assumption with a span of exactly zero is not robust; it is **disconnected**.
A `stream` schedule carries its own growth and its own end date, so on a
stream-mode plan the global `income_growth` and `work_years` settings do
nothing at all.

This matters because sweeping them and seeing no movement looks like stability.
It is not. Say which parameters were inert and why:

> `income_growth` and `work_years` are inert here — your human capital is an
> explicit schedule, so those global settings no longer feed it. To test a
> different retirement date, change the schedule and compare the two documents.

## `monotonic` — and the discount rate, which is not

Sweeping the discount rate alone on the worked example:

| Rate | Human capital | Future consumption | Economic net worth |
|---:|---:|---:|---:|
| 0.5% | 1,776,299 | 1,368,615 | 470,826 |
| 1% | 1,671,653 | 1,244,384 | 490,411 |
| 2% | 1,486,360 | 1,039,047 | 510,455 |
| **3%** | 1,328,522 | 878,949 | **512,715** ← peak |
| 5% | 1,077,678 | 652,535 | 488,286 |
| 10% | 693,298 | 370,549 | 385,891 |

Both sides shrink as the rate rises. But consumption runs 40 years and income
only 25, so at low rates the longer stream dominates and the gap *widens*; past
the crossover the larger stream dominates and it narrows again. Economic net
worth therefore **peaks in the middle**.

Two consequences to state whenever the rate comes up:

1. **"Raise the rate to be conservative" is not reliable advice here.** One
   rate discounts the user's future salary *and* their future groceries. From
   0.5% to 3% the "conservative" move raises the answer; from 3% to 10% it
   lowers it. Which direction you get depends on where you started.
2. **Where the peak sits is this household's, not a general fact.** It depends
   on the relative size and duration of the two streams. Do not generalise it.

The script detects non-monotonicity automatically and attaches a note naming
the peak. Repeat that note; do not paraphrase it into "the rate doesn't matter
much", which is a different and false claim.

## `comparison` — the cost of a decision

`--compare other.md` runs two documents and diffs them line by line. On the
worked example, pulling retirement forward five years:

```
economic_net_worth   440,302.38 -> 280,768.00   -159,534.38
human_capital      1,299,342.20 -> 1,020,007.54  -279,334.66
other_benefits       320,518.16 ->   440,318.44  +119,800.28
```

Five years of retirement costs $159,534 in today's dollars: $279,335 of
forgone earnings, offset by $119,800 of pension drawn five years earlier.

That decomposition is the answer to "what would retiring early cost me" —
and it is worth saying that the delta inherits every assumption the two
documents share, so it is more robust than either level.

## Cost

One `beans economic npv` run per grid point, plus up to fourteen bisection
steps per sign flip: roughly forty runs, a few seconds. All read-only. Narrow
it with `--sweep inflation,work_years` when only one question is live.
