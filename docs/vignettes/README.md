# beans vignettes

Task-oriented walkthroughs of common personal-finance workflows in `beans`.

Where the [main README](../../README.md) is a *reference* — every command and
flag — these vignettes are *guided tours*. Each one follows a single realistic
job from start to finish, with copy-pasteable commands and the real output they
produce, so you can follow along against your own ledger.

Every command below is run against a throwaway ledger, so nothing here touches
your real books. To follow along the same way, point `beans` at a scratch file:

```sh
export BEANS_LEDGER=/tmp/demo.db   # or pass -f /tmp/demo.db to each command
beans init
```

When you're done, just delete the file.

## The vignettes

Read them in order — each builds on the habits of the one before — or jump to
whichever job you have in front of you.

1. **[Getting started](01-getting-started.md)** — Create a ledger, understand
   the starter chart of accounts, record opening balances, capture day-to-day
   spending and income, and read your first balance sheet, income statement, and
   cash flow statement.

2. **[Budgeting a month](02-budgeting-a-month.md)** — Set per-category budgets,
   track a month of spending against them, read the budget-vs-actual variance
   report, and tie it back to your income statement and savings rate.

3. **[Import & reconcile](03-import-and-reconcile.md)** — Import a bank CSV,
   auto-categorize transactions with rules, safely re-import overlapping
   exports, clear postings against a statement, reconcile to the cent, and lock
   the period.

4. **[Recurring, goals & investing](04-recurring-goals-investing.md)** —
   Automate bills and paychecks with recurring rules, set savings and
   debt-payoff goals, track investments as FIFO lots with mark-to-market, and
   glance at a forecast.

## Conventions used throughout

- Commands are shown in `sh` blocks; the output that follows is real, captured
  from running them in order.
- Transaction dates are fixed (the 2026 tax year) so the figures in the
  captured output match what you'll see. Two things still track the day you run
  them: reports with an "As of: <today>" header (`status`, `balances`,
  `goal list`, `invest list`) will show your current date, and `beans goal add
  --by` requires a date in the *future* — if you're following along after 2026,
  bump those `--by` dates forward.
- `beans` understands **fuzzy account names** — `groceries` resolves to
  `Expenses:Food:Groceries` — so the vignettes lean on the short forms once a
  workflow is established.
