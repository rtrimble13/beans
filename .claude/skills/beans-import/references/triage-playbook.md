# Triage playbook

`beans categorize` hands you a list sorted least-certain first. This is how to
work it.

## Read the basis, not the score

The single most important habit. Two rows can score identically for opposite
reasons and need opposite responses:

```text
AMAZON MKTPLACE 442   Expenses:Shopping  0.64  20 prior: 14 Shopping / 6 Cloud
UNITED AIRLINES 900   Expenses:Travel    0.60  3 prior
```

| Basis shape | What it means | What to do |
|---|---|---|
| `3 prior` | **Thin evidence.** Only a few past examples, all agreeing. | Accept if it looks right. It firms up on its own as history accumulates — no action needed, no rule needed. |
| `20 prior: 14 Shopping / 6 Cloud` | **Conflicting evidence.** A merchant that genuinely goes two ways. | This never settles. More history will not fix it. Decide *this* row on its own merits — amount and date are your evidence. A rule would be actively wrong here. |
| `~blue ridge dental 3 prior` | **Fuzzy match** to a near-miss merchant key. | Check the `~` name is actually the same merchant. Statement descriptors drift; sometimes it is a different shop. |
| `no match` | Nothing resolved it. | Needs you. Search the register, then fill or add a rule. |
| `rule "WHOLE FOODS"` | A saved rule matched. | Standing intent, already decided. Leave alone unless the user is changing their mind. |
| `already set` | The file carried a category. | Confidence 1.00 **and never second-guessed.** If a card issuer wrote it, it deserves a spot-check — see below. |

Confidence is a ranking heuristic, not a probability. `beans` deliberately has
no auto-accept threshold, and you should not invent one: it exists to sort your
attention, and a high score on a misclassified transfer is still wrong.

## How merchants are matched

Worth knowing, because it explains surprising results
(`beans/classify.py` → `merchant_key`):

- **Digits are stripped.** `BLUE RIDGE DENTAL ASSOC 41` and `BLUE RIDGE DENTAL
  ASSOC` are one merchant. Store numbers, tills and reference numbers would
  otherwise fragment one shop across dozens of buckets.
- **Containment counts as a match** when the shorter key is ≥5 characters, and
  the *longest* containing merchant wins.
- **Only clean two-posting transactions are learned from.** A split across three
  or more accounts has no single answer, so it is excluded rather than guessed
  at. A merchant you always split will therefore show `no match` forever — that
  is correct behaviour, not a bug, and it is a poor rule candidate too.

## Before proposing anything, look

Do not propose an account from what the merchant name sounds like. Look at how
this ledger has actually treated it:

```sh
beans search "DENTAL"                      # any prior transaction mentioning it
beans register Expenses:Health --period 2026   # what lives in the account you're considering
beans account list --names                 # what accounts actually exist
```

A chart of accounts is personal. One ledger files vet bills under
`Expenses:Pets`, another under `Expenses:Health`. The register tells you which
one you are in; the merchant name does not.

## Fill, rule, or ask

| Situation | Action |
|---|---|
| One-off purchase, account obvious from context | Fill the cell in the prepared CSV |
| Merchant recurs monthly, account is unambiguous, history cannot know it yet (new merchant, or a deliberate change of mind) | Propose `beans rule add PATTERN ACCOUNT` |
| Merchant already has consistent history | Do nothing — history already answers it. A rule here is a hand-maintained cache of what the books already record. |
| Evidence conflicts (`14 Shopping / 6 Cloud`) | Decide this row; **do not** add a rule |
| Personal/tax significance, or you would be guessing | **Ask.** |

A rule only affects rows nothing has already answered. Because resolution
runs column -> rule -> history, adding a rule does **not** change a row whose
category cell the prepared file already carries — correct that cell too, or
the rule takes effect only from the next statement onward.

Rules are prescriptive and always beat inference, so a bad rule is worse than no
rule — it silently overrides a register that knew better. Keep patterns specific
enough not to false-match (`SHELL OIL`, not `SHELL`) and no more specific than
that, since over-specific patterns break when a descriptor changes slightly.
When several rules match, the **longest pattern wins**, regardless of the order
they were added.

## The traps

These are wrong regardless of confidence. Check every statement for them.

**Transfers.** The big one. "TRANSFER TO SAVINGS", "PAYMENT THANK YOU", "ONLINE
XFER TO ...", ATM withdrawals moving into a cash account, credit-card payments.
None of these are expenses — the money is still the user's. Booking a card
payment as an expense double-counts it: once when the card was swiped, again
when the card was paid. The counter-account is the **other account**
(`Assets:Savings`, `Liabilities:CreditCard`), and if that account's statement is
also being imported, the same movement appears in both files — expect and
account for it rather than importing it twice.

**Refunds and reversals.** A positive amount at a merchant the user normally
pays is almost always a refund. It belongs to the same expense account it
originally came from (netting the expense down), not to income.

**The issuer's category column.** `categorize` scores a pre-filled category 1.00
and never revisits it. That is correct when the user filled it in, and wrong
when a card issuer did — issuer taxonomies do not match a personal chart of
accounts. Spot-check them, and prefer dropping the column entirely so the
ledger's own history answers instead.

**Income that is not income.** Reimbursements from an employer or a friend,
owner draws, transfers in from another person. Ask.

**Duplicated statement periods.** Overlapping exports are normal and dedupe
handles them — but dedupe keys on `(date, amount)` only. Two genuinely different
$45.00 charges on the same day both import (correct), and a transaction the user
already entered by hand at a slightly different date will *not* be caught (it
lands outside the key). Phase 7 reconciliation is what surfaces that.

**Scheduled payments the ledger already posted.** The same blind spot, but with
a system on the other end of it rather than a person: `beans recur run` writes
rent from a template on its due date, and the statement reports it on the day it
cleared. Two days apart, or two dollars apart, and dedupe sees two different
transactions. This is not a triage judgement — the row's *account* is usually
right — so it is a separate pass with its own tool
(`scripts/recur_match.py`, Phase 4) and its own reference,
`recurring-overlap.md`. Do not resolve it by editing the category cell.

## What to hand back

A table, not prose. One row per decision, grouped so the user can approve in
bulk:

```text
PROPOSED RULES (apply to all future imports)
  BLUE RIDGE DENTAL   -> Expenses:Health:Dental    3 rows this statement, new merchant
  HARBOR POINT VET    -> Expenses:Pets             2 rows, matches Expenses:Pets history

PROPOSED CELL EDITS (this statement only)
  2026-10-22  PAYMENT THANK YOU  -450.00  -> Assets:Checking   transfer, not income
  2026-10-14  AMAZON MKTPLACE 442  -31.00 -> Expenses:Shopping  14/6 split; small, non-business

NEEDS YOUR DECISION
  2026-10-18  ZELLE FROM J SMITH   +200.00  reimbursement, gift, or income?
```

Then stop and wait. Do not import on the strength of your own table.
