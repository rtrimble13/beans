# Importing a statement with Claude

**What you'll accomplish:** hand Claude a messy bank export — non-ISO dates,
split debit/credit columns, a preamble line above the header — and get it into
your ledger correctly categorized, with every uncertain row reviewed by you and
the result proven against the statement to the cent. You'll use the
`beans-import` **agent skill** for Claude Code, and you'll run every command it
runs, so you can see there is no magic in it.

**Prerequisites:** [Getting started](01-getting-started.md) and
[Import & reconcile](03-import-and-reconcile.md) — this vignette assumes you
know what `import`, `rule` and `reconcile` do. Install instructions for the
skill are in [`docs/claude-skill-setup.md`](../claude-skill-setup.md).

> **The skill drives the ordinary CLI.** Everything below is a `beans` command
> or a small helper script you can run yourself. The skill is a *procedure* —
> what to run, in what order, and what to refuse to do — not a new engine.

## The sample

[`sample-bank-november-raw.csv`](sample-bank-november-raw.csv) is deliberately
awkward, in the three ways real exports usually are:

```text
Account,**** 4412,Statement Period,11/01/2026 - 11/30/2026
Posting Date,Transaction Date,Description,Debit,Credit,Balance
11/02/2026,11/01/2026,PAYROLL DEPOSIT ACME CORP,,3200.00,11095.88
11/04/2026,11/03/2026,WHOLE FOODS MARKET #412,92.15,,11003.73
```

A preamble line above the header, `MM/DD/YYYY` dates, and the amount split
across `Debit` and `Credit`. `beans` reads none of that as-is — which is the
point.

## 0. A ledger with some history

The classifier learns from your register, so it needs one. Build the same
ledger [Import & reconcile](03-import-and-reconcile.md) builds, plus a couple
of October entries so two November merchants have a precedent:

```sh
export BEANS_LEDGER=/tmp/skill-demo.db
beans init
beans tx add --date 2026-05-01 --desc "Opening balances" \
    --post Assets:Checking 1500 --post Assets:Savings 6000 \
    --post "Equity:Opening Balances"

beans rule add "WHOLE FOODS" Groceries
beans rule add "SHELL" Transportation
beans rule add "CITY POWER" "Housing:Utilities"
beans rule add "PAYROLL" Salary

beans import docs/vignettes/sample-bank.csv       -a Checking --category Expenses:Other
beans import docs/vignettes/sample-bank-june.csv  -a Checking --category Expenses:Other
beans import docs/vignettes/sample-bank-july.csv  -a Checking --category Expenses:Other

beans account add "Expenses:Health:Dental" --type expense
beans account add "Expenses:Pets" --type expense
beans tx add --date 2026-10-09 --desc "BLUE RIDGE DENTAL ASSOC 41" \
    --post Expenses:Health:Dental 210 --post Assets:Checking -210
beans tx add --date 2026-10-20 --desc "HARBOR POINT VETERINARY" \
    --post Expenses:Pets 88 --post Assets:Checking -88

beans clear Checking --through 2026-10-31
```

That leaves checking at **7,895.88** as of 31 October — which is where the
November statement picks up.

## 1. Ask

In Claude Code, with the skill installed:

```
import my November checking statement from docs/vignettes/sample-bank-november-raw.csv
```

What follows is what Claude does, step by step.

## 2. Read the file before assuming anything

```sh
python3 ~/.claude/skills/beans-import/scripts/inspect_csv.py \
    docs/vignettes/sample-bank-november-raw.csv
```

```text
docs/vignettes/sample-bank-november-raw.csv  —  10 data row(s), delimiter ',', header on line 2

Columns: Posting Date, Transaction Date, Description, Debit, Credit, Balance
Mapped:  date='Posting Date', description='Description', debit='Debit', credit='Credit', balance='Balance'
Dates:   MM/DD/YYYY
Amounts: split debit/credit

NEEDS normalize_csv.py — beans cannot read this as-is:
  - dates are MM/DD/YYYY; beans accepts only YYYY-MM-DD
  - debit/credit are split across "Debit" and "Credit"
  - 1 preamble line(s) sit above the header

Check with the user:
  - Running balance column "Balance" ends at 9897.58 — that is the statement's ending balance for `beans reconcile ACCOUNT --balance`.
```

Note the last line. The statement's own running balance is what you will check
the whole import against in step 8 — it is the one figure in the file that no
step of this process derives, so it is the honest referee.

## 3. Normalize into a working copy

The original is evidence; it is never modified.

```sh
python3 ~/.claude/skills/beans-import/scripts/normalize_csv.py \
    docs/vignettes/sample-bank-november-raw.csv -o work/november.csv
```

```text
Wrote 10 row(s) to work/november.csv
  dates      MM/DD/YYYY -> YYYY-MM-DD
  amounts    from Debit/Credit
  category   none in source
```

```text
date,description,amount
2026-11-02,PAYROLL DEPOSIT ACME CORP,3200.00
2026-11-04,WHOLE FOODS MARKET #412,-92.15
2026-11-06,SHELL OIL 57422,-51.30
```

A debit is money out, so it comes through negative. If the dates had been
genuinely ambiguous — every day of the month ≤ 12, so `MM/DD` and `DD/MM` both
parse — the script would have **refused** rather than guessed, because a wrong
guess silently mis-dates the entire statement.

## 4. Categorize — nothing is written to the ledger

```sh
beans categorize work/november.csv --account Checking \
    -o work/checking-2026-11-prepared.csv
```

```text
CATEGORIZE — Assets:Checking
Source: work/november.csv — 10 row(s)
Learned from 18 prior transaction(s) on this account

Already set in the file  0
From an import rule      6
Inferred from history    2
Needs a decision         2

Date        Description                   Amount  Account                     Conf  Basis
---------------------------------------------------------------------------------------------------------------
2026-11-19  SUMMIT RIDGE CLIMBING GYM     -89.00  —                           0.00  no match
2026-11-23  ONLINE XFER TO SAVINGS       -500.00  —                           0.00  no match
2026-11-09  BLUE RIDGE DENTAL ASSOC 88   -145.00  Expenses:Other              0.25  2 prior: 1 Other / 1 Dental
2026-11-14  HARBOR POINT VETERINARY       -64.00  Expenses:Pets               0.33  1 prior
2026-11-02  PAYROLL DEPOSIT ACME CORP   3,200.00  Income:Salary               1.00  rule "PAYROLL"
2026-11-04  WHOLE FOODS MARKET #412       -92.15  Expenses:Food:Groceries     1.00  rule "WHOLE FOODS"
2026-11-06  SHELL OIL 57422               -51.30  Expenses:Transportation     1.00  rule "SHELL"
2026-11-12  CITY POWER & LIGHT           -131.40  Expenses:Housing:Utilities  1.00  rule "CITY POWER"
2026-11-17  WHOLE FOODS MARKET #412       -78.60  Expenses:Food:Groceries     1.00  rule "WHOLE FOODS"
2026-11-25  SHELL OIL 57422               -46.85  Expenses:Transportation     1.00  rule "SHELL"
```

Six rows answered by rules, two by history, two needing a person. That last
number is the only one that costs you time.

## 5. Triage

```sh
python3 ~/.claude/skills/beans-import/scripts/triage.py \
    work/checking-2026-11-prepared.csv
```

```text
TRIAGE — work/checking-2026-11-prepared.csv

10 row(s) across 8 merchant(s): 6 settled, 4 merchant(s) need a look (2 row(s) still have no account).

SUMMIT RIDGE CLIMBING GYM                1 row(s)      -89.00  conf 0.00
    proposed : — none proposed —
    basis    : no match
    evidence : none — no history — search the register, then fill it or add a rule

ONLINE XFER TO SAVINGS                   1 row(s)     -500.00  conf 0.00
    proposed : — none proposed —
    basis    : no match
    evidence : none — no history — search the register, then fill it or add a rule
    ! looks like a TRANSFER — counter-account is the other account, not an expense

BLUE RIDGE DENTAL ASSOC 88               1 row(s)     -145.00  conf 0.25
    proposed : Expenses:Other
    basis    : 2 prior: 1 Other / 1 Dental
    evidence : conflicting — history disagrees — decide this row on its merits; a rule would be wrong here

HARBOR POINT VETERINARY                  1 row(s)      -64.00  conf 0.33
    proposed : Expenses:Pets
    basis    : 1 prior
    evidence : thin — few priors, all agreeing — accept if it looks right; it firms up on its own
```

Four rows, four different problems — which is exactly why one confidence number
is not enough to act on:

- **SUMMIT RIDGE CLIMBING GYM** — genuinely new. Nothing in the register knows
  it. Needs you, once.
- **ONLINE XFER TO SAVINGS** — a **transfer**, not an expense. Booking it to a
  category would show $500 of spending that never happened *and* leave savings
  understated by $500. Confidence would never have caught this; the descriptor
  is what gives it away.
- **BLUE RIDGE DENTAL ASSOC 88** — note the digits differ from October's
  `ASSOC 41`, and `beans` still sees one merchant, because merchant matching
  strips digits. The `2 prior: 1 Other / 1 Dental` split is the ledger telling
  you it has filed this merchant two different ways — the `Expenses:Other` came
  from the blanket `--category` fallback back in step 0. **This is what a
  fallback bucket costs you later.**
- **HARBOR POINT VETERINARY** — thin, not conflicting. One prior, agreeing.
  Accept it; it firms up on its own.

Claude proposes; you decide. Nothing has been written.

## 6. Apply the decisions

```sh
beans rule add "BLUE RIDGE DENTAL" "Expenses:Health:Dental"
```

Then fill the three cells in `work/checking-2026-11-prepared.csv`:

```text
2026-11-19,SUMMIT RIDGE CLIMBING GYM,-89.00,Expenses:Entertainment,...
2026-11-23,ONLINE XFER TO SAVINGS,-500.00,Assets:Savings,...
2026-11-09,BLUE RIDGE DENTAL ASSOC 88,-145.00,Expenses:Health:Dental,...
```

> **The dental row needs both.** The rule fixes every *future* statement, but
> this prepared file already carries `Expenses:Other` — and a filled category
> column outranks a rule. Adding the rule alone changes nothing here. The dry
> run in the next step is what catches that, which is one good reason never to
> skip it.

Then confirm nothing is still blank. `categorize` is re-runnable over its own
output — it keeps what is filled and fills only what is empty:

```sh
beans categorize work/checking-2026-11-prepared.csv --account Checking --json
```

```json
{"rows": 10, "column": 10, "rule": 0, "history": 0, "unresolved": 0}
```

`unresolved: 0`. Ready.

## 7. Dry run, then import

```sh
beans import work/checking-2026-11-prepared.csv --account Checking --dry-run
```

```text
Would import 10 transaction(s) into Assets:Checking
Date        Description                 Counter-account               Amount
----------------------------------------------------------------------------
2026-11-02  PAYROLL DEPOSIT ACME CORP   Income:Salary               3,200.00
2026-11-04  WHOLE FOODS MARKET #412     Expenses:Food:Groceries       -92.15
2026-11-06  SHELL OIL 57422             Expenses:Transportation       -51.30
2026-11-09  BLUE RIDGE DENTAL ASSOC 88  Expenses:Health:Dental       -145.00
2026-11-12  CITY POWER & LIGHT          Expenses:Housing:Utilities   -131.40
2026-11-14  HARBOR POINT VETERINARY     Expenses:Pets                 -64.00
2026-11-17  WHOLE FOODS MARKET #412     Expenses:Food:Groceries       -78.60
2026-11-19  SUMMIT RIDGE CLIMBING GYM   Expenses:Entertainment        -89.00
2026-11-23  ONLINE XFER TO SAVINGS      Assets:Savings               -500.00
2026-11-25  SHELL OIL 57422             Expenses:Transportation       -46.85
```

This is the moment the skill stops and waits. It will not import on its own
reading of its own table.

```sh
beans import work/checking-2026-11-prepared.csv --account Checking --json
```

```json
{"rows": 10, "imported": 10, "skipped": 0}
```

## 8. Prove it

Two checks, and they prove different things.

**Line by line** — does every statement row have a matching posting?

```sh
beans reconcile Checking --statement work/november.csv
```

```text
Matched                         10
  on an exact date              10
  within the date window         0
----------------------------------
Amount mismatch                  0
In bank, not in ledger           0
In ledger, not in bank           0
Cleared, absent from statement   0

Every statement line ties to the register.
```

Reconcile reads the **normalized** copy, because `beans` cannot parse the raw
export — that is why it needed normalizing in the first place. So this proves
the *import* was faithful to the normalized file. It does not, on its own,
prove the normalization was faithful to the bank.

**The balance** — is the *total* right? This is the check that covers the
normalization, because the figure comes from the bank's own running-balance
column and nothing in this workflow derived it:

```sh
beans clear Checking --through 2026-11-30
beans reconcile Checking --balance 9897.58 --date 2026-11-30
```

```text
RECONCILE — Assets:Checking
As of: 2026-11-30

Statement balance  $9,897.58
Cleared balance    $9,897.58
Difference             $0.00

Reconciled — cleared balance matches the statement.
```

To the cent. If the debit/credit signs had been read backwards, or a row had
been dropped in normalization, this is where it would show up — which is why
the skill runs both checks and not just the first.

## 9. Close the month

Only when you're satisfied:

```sh
beans period close 2026-11-30
```

## What you actually reviewed

Ten transactions. Six were answered by rules you set months ago, two by the
register, and two needed you — of which one was a transfer that no confidence
score would have flagged. That ratio is the point: the skill is not trying to
categorize your spending for you. It is trying to make sure the four rows that
need your judgement are the four rows you actually look at.

---

**Next:** [Using beans from Claude (MCP)](08-mcp.md) — for reading your
finances rather than writing to them. The skill imports; the MCP server
reports. They work well together and install independently.
