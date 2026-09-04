# Inference playbook

Named patterns, what each one actually implies, and the command to *propose*.
Never run a write command; the user runs it.

Each entry is: the shape in `trend.py` output → the reading → the check that
confirms it → what to offer.

---

## Subscription creep

**Shape.** `drift` up, small monthly amount, in a category like
`Expenses:Entertainment` or `Expenses:Other`; or several `new` findings across
a few periods.

**Reading.** Price rises on standing services, or subscriptions that were
started and never cancelled. This compounds quietly: it is small every month
and material every year.

**Confirm.** `beans recur list` — compare the rule's amount against the
series' latest level. `beans register <account> --period <window>` names the
payees.

**Offer.** The annualized figure (`annualized` in the finding), the list of
payees behind it, and — if a rule exists with a stale amount — the exact
`beans recur` change for the user to make.

---

## A payment that quietly lapsed

**Shape.** `stopped`.

**Reading.** The most valuable finding this skill produces, because nothing in
`beans` looks for it. Either a service ended (money back), a payment failed
(money still owed, possibly with a penalty), or a recurring rule was paused and
forgotten.

**Confirm.** `beans recur list` — is there still a rule? Is it `due`? Is it
paused? `beans register <account>` for the last posting's date.

**Offer.** Name the account, the prior typical amount, and how many periods it
has been absent. Ask which of the three it is — do not guess. If a rule is
paused, the fix is `beans recur resume <id>`, for them to run.

---

## Budget calibration

**Shape.** `--budgets` gathered, and an account over budget in most periods
rather than a few.

**Reading.** A budget missed nine times in twelve is not a discipline problem,
it is a wrong number. Variance reporting will keep flagging it forever and the
reader will keep ignoring it.

**Confirm.** The per-period variance rows in the series, plus the account's
`median` from `trend.py`.

**Offer.** A proposed `beans budget set <account> <amount> --period monthly`
using the trend's median or latest level, said plainly as a recalibration —
*"this makes the budget describe your spending; it does not reduce it."* If the
account also shows `drift`, say that a budget set to today's level will be wrong
again in six months, and why.

---

## Lifestyle creep

**Shape.** `total_expenses` shows `drift` up while `total_income` shows `step`
up, and the savings-rate series is flat or falling.

**Reading.** A raise absorbed by spending. The absolute numbers all improved,
which is why this hides from a period-over-period review: net income is up, so
nothing looks wrong.

**Confirm.** `--ratios` gives `savings_rate_pct` per period. Rank the expense
accounts by drift magnitude to see where it went.

**Offer.** The savings rate then vs now, the two or three accounts that account
for most of the expense drift, and what the rate would be had expenses held
flat — computed by `trend.py`, not by you.

---

## Thinning runway

**Shape.** `liquidity_months` (from `--ratios`) drifting down.

**Reading.** Either cash is falling or the monthly expense base is rising —
they are very different problems and the ratio alone does not distinguish them.

**Confirm.** Read the `cash` and `total_expenses` series side by side. Rising
expenses with flat cash is a spending story; falling cash with flat expenses is
a cash-flow story; both together needs saying twice.

**Offer.** Name which of the two it is, with both series. Do not recommend an
emergency-fund target as a rule of thumb — tie it to their own expense base.

---

## Stale forecast basis

**Shape.** An account shows `drift`, and `beans forecast` prices it at its
historical average.

**Reading.** `forecast --method average` prices each account at the mean of the
lookback window. On a trending series the mean sits behind the latest level, so
the projection understates — silently, and by more each month.

**Confirm.** Compare the account's monthly basis in `beans forecast --json`
against its `latest` in `trend.py`.

**Offer.** The gap between basis and latest, what it does to the projection over
the horizon, and `beans forecast --method trend` (or a shorter lookback) as the
alternative. Note that `trend` extrapolates, which is its own assumption.

---

## Goal trajectory

**Shape.** A goal exists (`beans goal list`), and the `net_worth` series has a
slope.

**Reading.** The question behind most of these briefings: *when does this
land?* A goal's required monthly contribution assumes a rate; the series shows
the actual one.

**Confirm.** `beans goal list --json` for the target and required monthly.
The `net_worth` series for the realized rate.

**Offer.** Required rate vs actual rate, and the effect of the single largest
expense finding on the date — *"the grocery drift alone is five weeks."* Frame
it as arithmetic on their own numbers, never as an instruction to spend less.

---

## One-off, correctly identified

**Shape.** `one-off`.

**Reading.** Usually nothing. It earns a line only when it was large enough to
distort something else the reader will look at — an average, a budget, a
forecast basis.

**Offer.** One sentence naming it and its period, so the reader knows you saw it
and chose not to trend it. Then move on. Resist the urge to make it a finding.

---

## Nothing to report

**Shape.** No findings clear both thresholds.

**Reading.** The correct and common outcome for a well-run ledger read monthly.

**Offer.** One paragraph: the window, that the totals and the ratios are within
their own noise, the `immaterial_count`, and anything preflight warned about.
Do not go looking for something alarming to justify the run — a briefing that
always finds a concern is one nobody reads.
