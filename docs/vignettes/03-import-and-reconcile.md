# Import & reconcile

**What you'll accomplish:** stop hand-typing transactions. Pull a month of
activity from your bank's CSV export, auto-categorize it with rules, re-import
safely without creating duplicates, then prove your ledger matches the bank to
the cent — first on the balance, then line by line, so a difference names the
transaction that caused it — and lock the period so it can't drift.

**Prerequisites:** [Getting started](01-getting-started.md). A bank CSV export —
we provide four samples — [`sample-bank.csv`](sample-bank.csv),
[`sample-bank-june.csv`](sample-bank-june.csv),
[`sample-bank-july.csv`](sample-bank-july.csv) and
[`sample-bank-october.csv`](sample-bank-october.csv) — so every step here is
runnable as written. The commands below reference them by their
repo-root-relative path (`docs/vignettes/sample-bank.csv`), so run them from the
repository root — or substitute the path to wherever you saved the files.

Start fresh and seed opening balances:

```sh
export BEANS_LEDGER=/tmp/import-demo.db
beans init
beans tx add --date 2026-05-01 --desc "Opening balances" \
    --post Assets:Checking 1500 --post Assets:Savings 6000 \
    --post "Equity:Opening Balances"
```

The sample export looks like a typical bank download — a `date`, a
`description`, and a signed `amount` (positive = money in):

```text
date,description,amount
2026-05-02,PAYROLL DEPOSIT ACME CORP,3200.00
2026-05-03,WHOLE FOODS MARKET #412,-86.40
2026-05-06,SHELL OIL 57422,-48.10
2026-05-09,WHOLE FOODS MARKET #412,-52.75
2026-05-14,CITY POWER & LIGHT,-120.00
2026-05-21,SHELL OIL 57422,-44.30
2026-05-28,TRANSFER TO SAVINGS,-500.00
```

## 1. Teach `beans` to categorize

A bank export says *what* was paid, not *which account* it belongs to. Import
**rules** map a text fragment in the description to a category, so routine
charges file themselves:

```sh
beans rule add "WHOLE FOODS" Groceries
beans rule add "SHELL" Transportation
beans rule add "CITY POWER" "Housing:Utilities"
beans rule add "PAYROLL" Salary
```

```text
Import rule added: descriptions containing 'WHOLE FOODS' -> Expenses:Food:Groceries
Import rule added: descriptions containing 'SHELL' -> Expenses:Transportation
Import rule added: descriptions containing 'CITY POWER' -> Expenses:Housing:Utilities
Import rule added: descriptions containing 'PAYROLL' -> Income:Salary
```

```sh
beans rule list
```

```text
Pattern      Account
---------------------------------------
WHOLE FOODS  Expenses:Food:Groceries
SHELL        Expenses:Transportation
CITY POWER   Expenses:Housing:Utilities
PAYROLL      Income:Salary
```

## 2. Preview the import

Always dry-run first. `--dry-run` parses the file and shows exactly what *would*
happen, writing nothing:

```sh
beans import docs/vignettes/sample-bank.csv --account Checking \
    --category Expenses:Other --dry-run
```

```text
Would import 7 transaction(s) into Assets:Checking
Date        Description                Counter-account               Amount
---------------------------------------------------------------------------
2026-05-02  PAYROLL DEPOSIT ACME CORP  Income:Salary               3,200.00
2026-05-03  WHOLE FOODS MARKET #412    Expenses:Food:Groceries       -86.40
2026-05-06  SHELL OIL 57422            Expenses:Transportation       -48.10
2026-05-09  WHOLE FOODS MARKET #412    Expenses:Food:Groceries       -52.75
2026-05-14  CITY POWER & LIGHT         Expenses:Housing:Utilities   -120.00
2026-05-21  SHELL OIL 57422            Expenses:Transportation       -44.30
2026-05-28  TRANSFER TO SAVINGS        Expenses:Other               -500.00
```

Each row found its category from a rule — except `TRANSFER TO SAVINGS`, which
matched nothing and fell back to `--category Expenses:Other`. (You'd fix that
one up by hand later, or add a rule for it.) The fallback guarantees nothing
imports uncategorized.

> **Column names not matching?** Bank exports vary. Remap with `--date-col`,
> `--desc-col`, `--amount-col`, and `--category-col` to fit whatever headers
> your bank uses.

## 3. Run it for real

Happy with the preview — drop `--dry-run`:

```sh
beans import docs/vignettes/sample-bank.csv --account Checking --category Expenses:Other
```

```text
Imported 7 transaction(s) into Assets:Checking
```

## 4. Re-importing is safe

Bank exports overlap — next month's download will include the tail of this one.
Run the *same file* again:

```sh
beans import docs/vignettes/sample-bank.csv --account Checking --category Expenses:Other
```

```text
Imported 0 transaction(s) into Assets:Checking (7 duplicate(s) skipped)
```

Nothing doubled up. `beans` skips any row matching an existing transaction by
**(date, account, amount)**. (Need to force a genuine duplicate — say two
identical $5 coffees the same day? Add `--no-dedupe`.)

Here's the imported month as a register:

```sh
beans register Checking --period 2026-05
```

```text
REGISTER — Assets:Checking

ID  Date        C  Description                Counter-account              Amount   Balance
-------------------------------------------------------------------------------------------
 1  2026-05-01     Opening balances           Assets:Savings, ...        1,500.00  1,500.00
 2  2026-05-02     PAYROLL DEPOSIT ACME CORP  Income:Salary              3,200.00  4,700.00
 3  2026-05-03     WHOLE FOODS MARKET #412    Expenses:Food:Groceries      -86.40  4,613.60
 4  2026-05-06     SHELL OIL 57422            Expenses:Transportation      -48.10  4,565.50
 5  2026-05-09     WHOLE FOODS MARKET #412    Expenses:Food:Groceries      -52.75  4,512.75
 6  2026-05-14     CITY POWER & LIGHT         Expenses:Housing:Utilities  -120.00  4,392.75
 7  2026-05-21     SHELL OIL 57422            Expenses:Transportation      -44.30  4,348.45
 8  2026-05-28     TRANSFER TO SAVINGS        Expenses:Other              -500.00  3,848.45
```

The `C` column is blank — nothing is **cleared** yet. That's the next step.

## 5. Reconcile against the statement

Your May statement closes on the 21st showing $4,348.45. Ask `beans` where you
stand *before* clearing anything:

```sh
beans reconcile Checking --balance 4348.45 --date 2026-05-21
```

```text
RECONCILE — Assets:Checking
As of: 2026-05-21

Statement balance  $4,348.45
Cleared balance        $0.00
Difference         $4,348.45

7 uncleared posting(s) totaling $4,348.45
ID  Date        Description                  Amount
---------------------------------------------------
 1  2026-05-01  Opening balances           1,500.00
 ...
 7  2026-05-21  SHELL OIL 57422              -44.30
```

Everything is uncleared, so the difference is the whole balance. Tick off the
entries the statement confirms. You can clear specific IDs
(`beans clear Checking 2 3 4`) or sweep the whole statement period at once:

```sh
beans clear Checking --through 2026-05-21
```

```text
Cleared 7 posting(s) on Assets:Checking
```

Reconcile again:

```sh
beans reconcile Checking --balance 4348.45 --date 2026-05-21
```

```text
RECONCILE — Assets:Checking
As of: 2026-05-21

Statement balance  $4,348.45
Cleared balance    $4,348.45
Difference             $0.00

Reconciled — cleared balance matches the statement.
```

$0.00 difference — your books match the bank exactly. The 05-28 transfer stays
uncleared because it's on next month's statement. This loop is how real errors
surface: a nonzero difference with nothing left uncleared points straight at a
missing or duplicated transaction.

## 6. Find the line, not just the difference

A balance check tells you *that* something is off. Next month, let it tell you
*which line*. June's activity, with rent booked to the 1st the way a recurring
rule posts it:

```sh
beans tx add --date 2026-06-01 --desc "Rent" \
    --post Expenses:Housing:Rent 1450 --post Assets:Checking -1450
beans earn 3200 Salary --date 2026-06-02 --desc "PAYROLL DEPOSIT ACME CORP"
beans spend 91.20 Groceries --date 2026-06-04 --desc "WHOLE FOODS MARKET #412"
```

June's export, [`sample-bank-june.csv`](sample-bank-june.csv):

```text
date,description,amount
2026-06-02,PAYROLL DEPOSIT ACME CORP,3200.00
2026-06-03,RENT ACH SUNRISE PROPERTIES,-1450.00
2026-06-04,WHOLE FOODS MARKET #412,-91.02
2026-06-15,CITY POWER & LIGHT,-118.40
```

Hand the file to `reconcile` instead of typing a balance:

```sh
beans reconcile Checking --statement docs/vignettes/sample-bank-june.csv
```

```text
RECONCILE — Assets:Checking
Statement: docs/vignettes/sample-bank-june.csv — 4 row(s), 2026-06-02 → 2026-06-15
Matching window: ±5 day(s)

Matched                         2
  on an exact date              1
  within the date window        1
---------------------------------
Amount mismatch                 1
In bank, not in ledger          1
In ledger, not in bank          1
Cleared, absent from statement  0

Matched — date drift (1)
Same amount, nearby date. These are matches, not discrepancies (a recurring entry booked to the 1st often settles a day or two either side).
ID  Ledger date  Stmt date   Drift  Description     Amount
----------------------------------------------------------
 9  2026-06-01   2026-06-03    +2d  Rent         -1,450.00

Amount mismatch (1)
Same payee and date, different amount — check the entry.
ID  Date        Description              Ledger  Statement  Diff
----------------------------------------------------------------
11  2026-06-04  WHOLE FOODS MARKET #412  -91.20     -91.02  0.18

In bank, not in ledger (1)
On the statement but never recorded — import these.
Line  Date        Description          Amount
---------------------------------------------
   5  2026-06-15  CITY POWER & LIGHT  -118.40

In ledger, not in bank (1)
Outstanding checks and deposits in transit look like this — so do duplicates and typos.
ID  Date        Description           Amount
--------------------------------------------
 8  2026-05-28  TRANSFER TO SAVINGS  -500.00

Re-run with --unmatched-out PATH to write the bank-only rows as an editable CSV for `beans import`.
Nothing was written to the ledger. Mark the confirmed entries with `beans clear Assets:Checking <ID...>`.
```

Read that top to bottom — it's four different findings, and only two are
problems:

- **Rent matched.** You booked it to the 1st, the bank settled it on the 3rd.
  Amounts are equal, the dates are two days apart, so it pairs up inside the
  ±5 day window and is reported as a **match**, not a discrepancy. This is the
  whole reason the window exists: fixed-day recurring entries would otherwise
  flag every single month.
- **An 18¢ amount mismatch.** Same merchant, same day, different amount — a
  typo when you entered it. The matcher will *never* fuzz an amount difference
  away, because in double-entry that difference is exactly the thing you're
  looking for.
- **A bill you never recorded.** On the statement, absent from the ledger.
- **A $500 transfer in the ledger but not on this statement.** That's the
  05-28 transfer from May — legitimately outstanding, not an error. `beans`
  can't know which of the two it is, and that's the point of giving it its own
  class rather than burying it in a single number.

Nothing above touched the ledger — the whole pass is read-only.

Fix the typo, then let `reconcile` hand the missing row straight to `import`:

```sh
beans reconcile Checking --statement docs/vignettes/sample-bank-june.csv \
    --unmatched-out june-new.csv
```

```text
Wrote 1 unmatched row(s) to june-new.csv — fill in any blank category, then: beans import june-new.csv --account Assets:Checking
```

`june-new.csv` holds just the bank-only rows, in exactly the shape `import`
reads — and the category is already filled in, because the `CITY POWER` rule
from step 1 matched:

```text
date,description,amount,category,confidence,basis
2026-06-15,CITY POWER & LIGHT,-118.40,Expenses:Housing:Utilities,1.00,"rule ""CITY POWER"""
```

The `confidence` and `basis` columns say *how* each account was arrived at —
here, a rule, so there's nothing to second-guess. Rows resolved from your
ledger's history carry a score and the evidence behind it instead, and rows
nothing could resolve come out blank. `import` ignores columns it doesn't
know, so the file needs no cleaning up. Step 8 applies the same machinery
to a whole export.

Fill in any blanks, then import as-is:

```sh
beans import june-new.csv --account Checking
beans tx void 11
beans spend 91.02 Groceries --date 2026-06-04 --desc "WHOLE FOODS MARKET #412"
```

```text
Imported 1 transaction(s) into Assets:Checking
Voided transaction #11 (2026-06-04 WHOLE FOODS MARKET #412)
Recorded transaction #13: 2026-06-04  WHOLE FOODS MARKET #412  $91.02
    Expenses:Food:Groceries  <-  Assets:Checking
```

Run it again and the statement ties:

```text
Matched                         4
  on an exact date              3
  within the date window        1
---------------------------------
Amount mismatch                 0
In bank, not in ledger          0
In ledger, not in bank          1
Cleared, absent from statement  0
...
Every statement line ties to the register.
```

The one remaining ledger-only entry is that outstanding May transfer, exactly
as it should be. Now you can clear with confidence — `beans clear Checking
--through 2026-06-15` — and reconcile the balance to the cent as in step 5.

> **Credit cards.** Most card exports report a purchase as a *positive*
> number, the opposite of the convention `beans` reads. Add `--invert` and
> matching, the report, and the generated import file all line up:
> `beans reconcile "Credit Card" --statement card.csv --invert`.

## 7. Lock the reconciled period

A reconciled month is trustworthy — freeze it so a stray edit can't quietly
change history:

```sh
beans period close 2026-05-21
beans period status
```

```text
Books closed through 2026-05-21 — transactions on or before this date can no longer be added or voided.
Books closed through 2026-05-21
```

Now the books defend themselves:

```sh
beans tx void 3
```

```text
beans: error: cannot void a transaction dated 2026-05-03: the books are closed through 2026-05-21 (see `beans period reopen`)
```

Need to amend a closed period later? `beans period reopen` lifts the lock.

## 8. Let the ledger do the categorizing

Rules got you started, but every new merchant needs one — and you have to
notice. `beans categorize` closes that loop by reading the answer out of your
own register: it suggests a counter-account for every row and says how sure it
is, writing nothing.

July's export brings a merchant no rule covers,
[`sample-bank-july.csv`](sample-bank-july.csv):

```sh
beans categorize docs/vignettes/sample-bank-july.csv --account Checking \
    -o july-prep.csv
```

```text
Already set in the file  0
From an import rule      4
Inferred from history    0
Needs a decision         1

Date        Description                  Amount  Account                     Conf  Basis
-----------------------------------------------------------------------------------------------------
2026-07-18  BLUE RIDGE DENTAL ASSOC     -140.00  —                           0.00  no match
2026-07-02  PAYROLL DEPOSIT ACME CORP  3,200.00  Income:Salary               1.00  rule "PAYROLL"
2026-07-03  WHOLE FOODS MARKET #412      -79.15  Expenses:Food:Groceries     1.00  rule "WHOLE FOODS"
2026-07-06  SHELL OIL 57422              -51.20  Expenses:Transportation     1.00  rule "SHELL"
2026-07-11  CITY POWER & LIGHT          -124.80  Expenses:Housing:Utilities  1.00  rule "CITY POWER"
```

Least certain first, so the row that needs you is at the top — one line to fix
out of five. Fill in the dentist and import:

```sh
$EDITOR july-prep.csv          # BLUE RIDGE DENTAL ASSOC -> Expenses:Health
beans import july-prep.csv --account Checking
```

Now skip forward. The dentist came back in August and September, and each time
you categorized it the same way. Here's October — **and no rule was ever
added**:

```sh
beans categorize docs/vignettes/sample-bank-october.csv --account Checking
```

```text
Learned from 18 prior transaction(s) on this account

Already set in the file  0
From an import rule      1
Inferred from history    1
Needs a decision         1

Date        Description                   Amount  Account          Conf  Basis
---------------------------------------------------------------------------------------
2026-10-20  HARBOR POINT VETERINARY       -88.00  —                0.00  no match
2026-10-09  BLUE RIDGE DENTAL ASSOC 41   -210.00  Expenses:Health  0.60  3 prior
2026-10-02  PAYROLL DEPOSIT ACME CORP   3,200.00  Income:Salary    1.00  rule "PAYROLL"
```

The dentist files itself now, from `3 prior` — and the store number in
`BLUE RIDGE DENTAL ASSOC 41` didn't throw it off, because merchant matching
ignores digits. A rule would have done the same job, but you'd have had to
write it; this you got for free by categorizing the transaction once.

**Read the `basis` column, not just the score.** Two rows can score alike for
opposite reasons: `3 prior` is *thin evidence* that will firm up on its own,
while `20 prior: 14 Shopping / 6 Cloud` is *plenty of evidence that disagrees*
— a merchant that genuinely goes two ways, which no amount of history will
settle for you. The number ranks your attention; the basis tells you what to do
about it.

Confidence is a ranking heuristic, not a probability, and nothing is ever
imported on the strength of it. That's the whole point of the file: you read it
before the ledger does.

> **Still want rules?** Yes — for two things history can't do. A brand-new
> merchant you already know the answer for, and a deliberate change of mind
> ("from now on, Amazon is Shopping"). Rules are prescriptive; history is
> descriptive, so a rule always wins. And on a fresh ledger there's no history
> at all — which is exactly why step 1 started with rules.

## What just happened

A bank CSV became categorized, balanced double-entry transactions; a second
import proved idempotent; a line-by-line pass against the statement turned a
bare difference into four named findings — and handed the missing row back to
`import` as an editable file; a clear-and-reconcile pass tied your ledger to the
statement to the cent before you sealed it; and the ledger started categorizing
new merchants out of its own history, so the rules you maintain by hand stopped
growing. This is the monthly cadence that keeps a ledger honest.

## Next steps

- **[Recurring, goals & investing →](04-recurring-goals-investing.md)** —
  automate the transactions you'd otherwise import every month, and put your
  reconciled cash to work toward goals and investments.
- Reference: [CSV import](../../README.md#csv-import) and
  [Reconciliation](../../README.md#reconciliation) in the main README.
