# Method — reading a financial series without lying to yourself

Every trap below has produced a confident, wrong statement about someone's
money. They are listed in the order they bite.

## 1. The partial period

The single most dangerous mistake, and the easiest to make.

`beans` reports the period you ask for, up to today. Ask for the current month
on the 4th and you get four days:

```
report income --period this-month   →  income 0.00, expenses 1800.00, net -1800.00
analyze      --period this-month   →  savings_rate null, liquidity_months 4.6
analyze      --period ytd          →  savings_rate 50.8%,  liquidity_months 19.8
```

Rent has posted; salary has not. Put that period at the end of a twelve-month
series and the honest-looking conclusion is *"income collapsed to zero and your
runway fell from 19.8 months to 4.6."* Both figures are real. The story is
fiction.

`series.py` ends the window at the last **complete** period
(`beans_io.last_complete`). Do not override it. If a partial period must be
shown, label it partial every time it appears — including in tables, where a
reader will otherwise scan the last column as comparable.

The same applies at the other end: a window reaching back before the ledger's
first transaction is padded with structural zeros, which look exactly like
thrift. `preflight.py` counts them.

## 2. Averages are not robust; use medians

One $2,000 vet bill moves a twelve-month mean by $167/month. So does a genuine
$167/month drift. A mean cannot tell them apart, and neither can a
least-squares line — both are dragged by the outlier.

`trend.py` therefore uses:

- **Theil–Sen** for the slope: the *median* of all pairwise slopes. It ignores
  up to roughly a third of the points being outliers.
- **MAD** (median absolute deviation) for the noise width, rather than a
  standard deviation, which the same outlier inflates.

This is why a lone spike classifies as `one-off` and leaves the trend alone.

## 3. Two thresholds, and they answer different questions

| | Question | Units | Default |
|---|---|---|---|
| **scale** | is this distinguishable from the series' own noise? | the series' own noise width | 3 × MAD |
| **materiality** | is it big enough that a person should care? | money, as a share of income | 1% of typical period income |

Keeping them separate matters. A perfectly flat rent that rises by 3¢ clears no
noise bar worth having; a $60 drift on a $6,000 income is real *and* trivial. A
finding must clear both, which is what keeps a briefing to four lines. The count
of real-but-small moves is reported as `immaterial_count` — mention the number,
not the list.

## 4. A step is not a drift

A raise, a rent increase and a new phone plan are *steps*: one change, flat
either side. A drift is a standing slope. They imply different actions — you
budget for a step and you investigate a drift — so the classifier fits both
models and believes whichever explains the series better, with a tie going to
the step because it claims less.

Note the noise for a step must be measured *within* each half. Measured
globally, a clean step is its own noise floor and no step is ever detectable.

## 5. Zero is a value; missing is not

An account absent from a period's income statement had no flow that period.
That is a real zero and belongs in the series. A period whose command *failed*
is a gap: `series.py` records `null` plus an entry in `errors`, and `trend.py`
excludes it from the fit rather than averaging over it. Never fill a gap with
zero — it manufactures a decline.

Two shapes fall out of this and are reported on their own:

- `stopped` — recurring, then two or more empty periods. The finding `beans`
  cannot make: a standing payment that quietly lapsed.
- `new` — absent, then present for two or more periods.

Both require the payment to have been *recurring*. A single bill in an
otherwise-empty year is a `one-off`, and calling it a cancelled subscription
would be inventing a story.

## 6. Transfers are not savings, and net worth is not income

`beans` already handles this — a checking→savings transfer touches no income or
expense account, and never appears in an income statement. The trap is
reasoning around the tool: do not read the register by eye and count a transfer
as saving. Savings rate comes from `beans analyze`, which computes it.

Likewise, the `networth` series moves with market value and revaluation, not
just with saving. A rising net worth alongside a falling savings rate is a
coherent story, not a contradiction — say both.

## 7. Category trends inherit the quality of categorization

If a quarter of spending sits in `Expenses:Other`, a category series measures
how consistently someone files receipts. `preflight.py` blocks above 25% and
warns above half that. Totals remain meaningful when categories do not — offer
them rather than nothing.

## 8. Horizon choice is a claim

3, 6 and 12 periods answer different questions, and quoting only the one that
supports a finding is a way to be accurate and misleading at once. Run all
three when it matters. Where they disagree, that disagreement is the finding: a
step shows as drift on a short window, and an acceleration shows as flat on a
long one.

## 9. Seasonality needs years, not months

Twelve months contain exactly one December. Anything you say about seasonality
from a single year is a guess — say "December is the only December in this
window" rather than "spending peaks in December". Two full years is the
minimum for the claim, and `--grain quarter` is usually the better lens.

## 10. Assumptions are not actuals

`forecast` and `economic bs` rest on inputs — discount rate, horizon, growth,
projection method. Their outputs are conditional, and the condition belongs in
the sentence. The ledger's own history is not conditional. Never mix them in one
figure without saying which is which.
