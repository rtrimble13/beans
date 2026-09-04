# Recurring rules and statement imports

Two systems are writing the same transaction into one ledger, and only one of
them knows the money actually moved.

## The overlap

A recurring rule is a balanced template plus a cadence. `beans recur run` posts
every occurrence due through a date, taking the date from the schedule and the
amount from the template. It is a *standing instruction*, not an observation.

A statement import posts what the bank says happened, with the date it cleared
and the amount it cleared for. It is an observation.

For rent, a subscription, a fixed insurance premium — anything a user set up as
a rule *because* it also appears on their statement — both systems describe one
payment. Import them both and the ledger says the rent was paid twice.

## What dedupe covers, and what it does not

`beans import` dedupes count-aware on `(date, amount)` within the target
account, against non-void postings. That is exactly the right key for the job
it was designed for — re-importing an overlapping statement period — and it is
blind to the ways a rule and a bank disagree:

| | Dedupe | Why |
|---|---|---|
| Rule posts 2026-10-01 −1800, statement says 2026-10-01 −1800 | **catches it** | keys match |
| Rule posts 2026-10-01 −1800, statement says 2026-10-03 −1800 | **misses it** | the due date is not the cleared date |
| Rule posts 2026-10-05 −79.99, statement says 2026-10-05 −82.47 | **misses it** | the template amount is an estimate |
| Rule has not run yet; statement carries the payment | **nothing to catch** | the duplicate arrives later, from `recur run` |

The first row is the only one that is safe by accident. The other three are why
Phase 4 exists.

Which drifts are common enough to expect:

- **Weekends and holidays.** A rule due on the 1st clears on the 3rd when the
  1st is a Saturday. This drifts differently every month, so a rule that
  matched cleanly last month may not this month.
- **Variable bills.** Utilities, usage-based services, anything with tax that
  moves. The rule carries whatever figure it was created with.
- **Price changes.** A subscription goes from 9.99 to 12.99 and the rule keeps
  posting 9.99 until someone notices — usually here.
- **A rule that was never run.** `beans status` nags about due rules for a
  reason; a user who imports statements regularly and runs `recur run` rarely
  will hit `rule_behind` on nearly every rule.

## Introspecting the rules

Everything below is read-only.

```sh
beans recur list --json         # names, cadence, next_due, status, posted count
beans recur show NAME           # the postings — the ONLY place the accounts appear
beans recur run --dry-run --to DATE --json   # instances still owed through DATE
beans search recurring --json   # instances already posted (tagged `recurring`)
```

Two details worth knowing, because `recur_match.py` is built on them:

- **`recur list --json` does not report accounts.** Only `recur show` does, and
  it has no `--json`. To know whether a rule even touches the account you are
  importing, you have to read `show`'s posting block.
- **`recur list`'s `amount` is the positive side** — the expense leg. The
  statement for an asset account reports the *other* sign. Match on the leg
  that hits the account being imported, not on the listed amount.
- **Posted instances are tagged `recurring`** by `post_recurring_instance`, and
  `beans search` is a LIKE across description, payee *and* tags — so a
  transaction merely described "recurring donation" turns up too. Check the tag
  list, not the fact that it matched.

## Resolving each verdict

### `duplicate_risk` — the ledger has it, dedupe will not catch it

Two fixes, and the difference matters:

**Drop the row from the prepared file.** The ledger keeps the rule's copy. This
is reversible: the row is still in the untouched original export, so nothing is
lost if the call turns out wrong. Prefer it when only the date drifted and the
amount is identical — the rule's version is then correct in every way that
affects a report.

**Void the rule's instance** (`beans tx void ID`) and import the statement's
row. This puts the real date and the real amount in the books, which is what
`beans reconcile --statement` compares against and what a balance check at a
period end will agree with. Prefer it when the amounts differ — the bank's
figure is right and the template's is stale.

But `beans tx void` is **one-way**. There is no unvoid. The transaction stays in
the ledger flagged void (history is kept), and every query filters it out,
including import's dedupe — which is why voiding first lets the statement row
import cleanly. Name the id, say what it is, and get an explicit yes.

If the amounts differ *and* the rule will keep posting the stale figure, the
lasting fix is a separate conversation: the rule needs updating. `beans recur`
has no edit — it is `remove` then `add`, which resets the occurrence counter.
Raise it as a follow-up rather than doing it inside an import.

### `rule_behind` — the statement has it, the rule has not fired

Import the statement's row. It is the observation; it has the real date and
amount. The problem is what happens afterwards: the rule's occurrence counter
has not advanced, so the next `beans recur run` posts its own copy of a payment
already in the books.

`beans` has no way to advance the counter without posting the instance — no
skip, no `--mark-posted`. So there is no clean fix, and the honest thing is to
say so and offer the two real options:

1. **Import the statement row and leave the rule behind.** Tell the user
   plainly that the next `recur run` will post a duplicate they will need to
   void. Best when accuracy of this period's books matters most.
2. **Let `recur run` post it and drop the statement's row instead.** The
   counter stays consistent and nothing needs voiding later, at the cost of
   booking the due date rather than the cleared date, and the template amount
   rather than the real one.

Recommend one — usually (1), since the ledger should record what happened —
but run neither without approval. `recur run` is a write.

### `dedupe_skips` — already there, keys match

Nothing to do. Mention it, so that when the Phase 6 dry run reports "3
duplicate(s) skipped" the user already knows which three and why.

### `posted_not_on_statement` — in the ledger, not on the statement

The rule fired for something the bank has not cleared, or has not cleared yet.
Not an import problem; Phase 7 reports it as `outstanding`. If it is a month
old rather than a few days, the rule is posting a payment that is no longer
happening — a cancelled subscription still on a schedule. Worth saying.

## What a missed overlap looks like afterwards

If one slips through, `beans reconcile --statement` is where it surfaces: an
`outstanding` row (in the ledger, not in the bank) sitting a few days from a
`matched` row of the same amount. The account's balance will be off by exactly
the duplicated amount, which the `--balance` check catches independently.

That is the backstop, not the plan. By then it is in the books.
