# Import & reconcile

**What you'll accomplish:** stop hand-typing transactions. Pull a month of
activity from your bank's CSV export, auto-categorize it with rules, re-import
safely without creating duplicates, then prove your ledger matches the bank to
the cent and lock the period so it can't drift.

**Prerequisites:** [Getting started](01-getting-started.md). A bank CSV export —
we provide a sample, [`sample-bank.csv`](sample-bank.csv), so every step here is
runnable as written. The import commands below reference it by its
repo-root-relative path (`docs/vignettes/sample-bank.csv`), so run them from the
repository root — or substitute the path to wherever you saved the file.

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

## 6. Lock the reconciled period

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

## What just happened

A bank CSV became categorized, balanced double-entry transactions; a second
import proved idempotent; and a clear-and-reconcile pass tied your ledger to the
statement to the cent before you sealed it. This is the monthly cadence that
keeps a ledger honest.

## Next steps

- **[Recurring, goals & investing →](04-recurring-goals-investing.md)** —
  automate the transactions you'd otherwise import every month, and put your
  reconciled cash to work toward goals and investments.
- Reference: [CSV import](../../README.md#csv-import) and
  [Reconciliation](../../README.md#reconciliation) in the main README.
