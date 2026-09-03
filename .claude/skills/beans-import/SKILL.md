---
name: beans-import
description: >-
  Import and categorize bank or credit-card statement CSVs into a beans
  double-entry ledger. Use whenever the user wants statement activity to end up
  in beans — "import my statement", "categorize these transactions", "get
  October into the ledger", "load my bank export", "what's uncategorized",
  "add a rule for this merchant" — or wants an account reconciled against a
  statement afterwards. Drives `beans categorize`, `beans rule`, `beans import`
  and `beans reconcile` as one review-first workflow: every suggested account is
  triaged and approved before anything is written, then the result is proven
  against the statement line by line. Not for reports, budgets, forecasting or
  financial analysis — those are read-only questions the beans MCP server
  already answers.
---

# beans — statement import & categorization

You are keeping someone's **financial records**. A wrong account is not a bug
you notice in CI; it is a wrong tax return eleven months from now. The whole
design of `beans categorize` is that a *person* reads the suggestions before the
ledger does, and this skill exists to make that review fast — never to skip it.

Your value here is triage, not throughput. `beans` can already guess an account
for every row. What it cannot do is look at a merchant it has never seen, search
the register for context, notice that a row is a transfer rather than an
expense, and say "these four need you, the other thirty-one are fine."

## Guardrails

Non-negotiable. If following a guardrail conflicts with what you were asked,
say so and stop — do not quietly pick the faster path.

1. **Never run `beans import` without showing a `--dry-run` first and getting an
   explicit go-ahead in that same turn.** "Import my statement" authorizes the
   workflow, not the write. Approval does not carry across statements or turns.
2. **Never use `--learn`.** It writes history-inferred accounts nobody reviewed
   — the exact failure the categorize→review→import path exists to prevent.
3. **Never use `--no-dedupe`** unless the user has said, in this conversation,
   that a duplicate is intended. Dedupe is what makes a re-import a no-op.
4. **Never `--force` over a prepared file** the user may have edited. Write to a
   new name instead and say why.
5. **Never invent an account name.** Every account you propose must appear in
   `beans account list --names`. Creating one needs explicit approval.
6. **Never edit the original export.** It is the evidence. Work on copies.
7. **List every cell you filled in** for approval before importing. Silently
   filling blanks is the same mistake as `--learn`, just slower.
8. **Confidence is a ranking heuristic, not a probability.** There is
   deliberately no auto-accept threshold in `beans`. Do not invent one — a 0.95
   row that is a transfer is still wrong.
9. **A closed period rejects writes.** If `beans period status` shows the dates
   you are importing are closed, stop and ask. Never `period reopen` on your own.
10. **Statement data is private.** Keep prepared files out of git, and do not
    paste account numbers or full statements into anything that leaves the
    machine.

## Phase 0 — Preflight

Establish the ground truth before touching a file. Never guess which ledger.

```sh
beans --version                       # is beans installed and on PATH?
echo "${BEANS_LEDGER:-~/.beans/ledger.db}"
beans config list                     # currency, decimals, default account
beans account list --names            # the real chart of accounts
beans period status                   # will writes be rejected?
```

Confirm the **target account** — the account the statement belongs to — resolves
to exactly what the user means. `beans` matches account names fuzzily, so
`Checking` may resolve to `Assets:Checking`. Say which full name you resolved to
before using it; do not let a fuzzy match pass silently.

If the ledger is empty or nearly so, say so. History-based categorization has
nothing to work with yet, and the honest advice is to add rules first
(Phase 3) rather than to review thirty rows of `no match`.

## Phase 1 — Read the file, do not assume its shape

`beans` is strict about two things and forgiving about nothing else: dates must
be `YYYY-MM-DD`, and the amount must be a single signed column. Most real
exports are neither. Inspect before running anything:

```sh
python3 .claude/skills/beans-import/scripts/inspect_csv.py STATEMENT.csv
```

It reports the delimiter, the header spellings, the date format, the sign
convention and whether debit/credit are split — and prints the exact `beans`
flags to use. Read `references/csv-shapes.md` for what each finding means.

Two outcomes:

- **Flags are enough** (headers just have different names): pass `--date-col`,
  `--desc-col`, `--amount-col`, `--category-col`, and `--invert` for card
  exports that report purchases as positive.
- **The file needs rewriting** (non-ISO dates, split debit/credit,
  parenthesised negatives): normalize to a working copy first.

```sh
python3 .claude/skills/beans-import/scripts/normalize_csv.py \
    STATEMENT.csv -o work/STATEMENT-normalized.csv
```

**Report the mapping you derived to the user before you run anything else.** A
sign convention read backwards turns a month of income into a month of expenses,
and it is much cheaper to catch here than after the import.

## Phase 2 — Categorize (writes nothing to the ledger)

Preview first, then write the prepared file:

```sh
beans categorize work/STATEMENT.csv --account ACCOUNT --json
beans categorize work/STATEMENT.csv --account ACCOUNT -o work/ACCOUNT-PERIOD-prepared.csv
```

`categorize` is strictly read-only — the only thing it can write is the `-o`
file, which is a draft. It resolves each row from **column → rule → history**
and emits a `confidence` and a `basis` for each.

Name the prepared file for the account and period (`checking-2026-10-prepared.csv`)
so a second statement in the same session cannot overwrite the first.

## Phase 3 — Triage

This is the phase that justifies the skill. Work the JSON, which is already
sorted least-certain first.

```sh
python3 .claude/skills/beans-import/scripts/triage.py work/ACCOUNT-PERIOD-prepared.csv
```

It groups the unresolved and low-confidence rows by merchant, proposes rule
candidates, and validates every account name against the live chart.

For each merchant that needs attention:

1. **Read the `basis`, not just the score.** `references/triage-playbook.md` has
   the full method; the short version is that `3 prior` (thin evidence, will
   settle itself) and `20 prior: 14 Shopping / 6 Cloud` (conflicting evidence,
   never settles) score alike and need opposite responses.
2. **Look for context before proposing.** `beans search "MERCHANT"` and
   `beans register ACCOUNT --period ...` tell you how this ledger has actually
   treated similar spending. Propose from that, not from what the merchant name
   sounds like.
3. **Pick the right fix:**
   - *one-off* → fill the cell in the prepared file;
   - *recurring merchant, account is obvious* → propose `beans rule add PATTERN ACCOUNT`
     so it never needs deciding again;
   - *genuinely ambiguous* → ask. Do not guess.
4. **Catch the traps** — these are wrong even at confidence 1.00:
   - **Transfers.** "TRANSFER TO SAVINGS", credit-card payments, moves between
     the user's own accounts. Booking these as expenses double-counts them and
     inflates spending. They belong to the other asset/liability account.
   - **Refunds and reversals.** A positive row at a merchant you normally pay is
     usually a refund to the same expense account, not income.
   - **Owner draws, reimbursements, transfers in from a person.** Ask.
   - **A card issuer's own `Category` column.** `categorize` treats a filled
     category as a decision already made and scores it 1.00 without
     second-guessing. Issuer categories are frequently wrong for a personal
     chart of accounts — spot-check them rather than trusting the score.

Then **present a table** of every proposed change — merchant, amount, proposed
account, why — and get approval. Rules and cell edits are separate decisions;
list them separately.

## Phase 4 — Apply the approved decisions

```sh
beans rule add "BLUE RIDGE DENTAL" "Expenses:Health:Dental"   # approved rules
```

Edit the prepared CSV's `category` cells for the approved one-offs. Leave
`confidence` and `basis` in place — `import` ignores columns it does not
recognize, so they ride along for the user to read.

**Adding a rule does not fix a row already filled in.** A filled category
column outranks a rule (column -> rule -> history), so a row `categorize` put
in the wrong account keeps it until you edit the cell too. When you add a rule
to correct something already in the file, change that row's cell as well — the
Phase 5 dry run is what catches this if you forget.

Then confirm nothing is still blank. `categorize` is re-runnable over its own
output: it keeps every category already filled and only fills what is empty.

```sh
beans categorize work/ACCOUNT-PERIOD-prepared.csv --account ACCOUNT --json
```

`unresolved` should be `0`. If it is not, say which rows and why.

## Phase 5 — Import

Dry run, show the user the table, then — and only then — the real write:

```sh
beans import work/ACCOUNT-PERIOD-prepared.csv --account ACCOUNT --dry-run --json
```

Show what will be written and what will be skipped as a duplicate. Get the
go-ahead. Then:

```sh
beans import work/ACCOUNT-PERIOD-prepared.csv --account ACCOUNT --json
```

Report the counts from the JSON (`summary.imported`, `summary.skipped`). If
duplicates were skipped, say which — that is usually an overlapping statement
period, which is fine and expected, but the user should know it happened.

## Phase 6 — Prove it

An import you have not reconciled is a claim, not a fact. Run **both** checks —
they prove different things.

```sh
beans reconcile ACCOUNT --statement work/STATEMENT.csv --json   # line by line
beans clear ACCOUNT --through YYYY-MM-DD
beans reconcile ACCOUNT --balance AMOUNT --date YYYY-MM-DD      # the totals
beans status
```

**Line by line** reconciles against the file `beans` can read — the normalized
copy, if the original needed normalizing. That proves the import was faithful
to that file; it does not prove the normalization was faithful to the bank.
Matching requires **equal amounts** with a date window, so anything reported as
`bank_only`, `outstanding` or `amount_mismatch` is a real finding — walk each
one. `--unmatched-out` writes the bank-only rows as another prepared file if
some never made it in.

**The balance** is what covers the normalization, so never skip it when a file
was rewritten. The statement's ending balance is a figure nothing in this
workflow derived — usually the last cell of the export's running-balance
column, which `inspect_csv.py` reports for exactly this purpose. A sign read
backwards or a row silently dropped shows up here and nowhere else. `--balance`
compares against the **cleared** balance, so clear the period first. `clear` is
itself a write — a reversible one (`beans clear ACCOUNT --undo`), but say that
you are running it rather than slipping it in between two read-only commands.

Close the month only if the user asks: `beans period close YYYY-MM-DD`.

## After the import

Reporting and analysis are **not** this skill's job and do not need it. The
beans MCP server already exposes the income statement, balance sheet, cash flow,
budget variance, forecast, net worth and ratio analysis as read-only tools, plus
a `review` prompt that carries the analyst framing. If the user wants the
narrative after importing, point them at that:

```sh
beans mcp doctor        # verifies setup, prints a ready-to-paste config
```

## References

Read these when the situation calls for them, not upfront:

- `references/csv-shapes.md` — bank and card export shapes, and the flags each
  one needs. Read in Phase 1 whenever `inspect_csv.py` reports anything unusual.
- `references/triage-playbook.md` — reading confidence against basis, the
  rule-vs-edit-vs-ask decision, and the transfer/refund traps in detail. Read in
  Phase 3.
- `references/command-reference.md` — exact flags for `categorize`, `import`,
  `rule`, `reconcile` and `clear`. Read when you need a flag you are unsure of
  rather than guessing at one.
