# Statement CSV shapes, and the flags each one needs

`beans` reads a statement export with three requirements, and is unforgiving
about all three:

| Requirement | Where it is enforced | What happens otherwise |
|---|---|---|
| Dates are `YYYY-MM-DD` | `beans/utils.py` → `parse_date` | Hard error naming the line. `today`/`yesterday` are also accepted, but never appear in an export. |
| One **signed** amount column, positive = money into the account | `beans/matching.py` → `read_statement` | Split debit/credit columns cannot be read at all. |
| Header names match, case-insensitively | `beans/matching.py` → `resolve_columns` | Error listing the columns it did find. `date` and `amount` are required; `description` and `category` are optional. |

There is no alias table. `Transaction Date` does not resolve to `date` on its
own — you either pass `--date-col "Transaction Date"` or rewrite the file.

Amounts are more forgiving than dates: `parse_amount` strips commas, spaces and
a leading or trailing currency code/symbol (`$5`, `CHF 10`, `EUR 5.50`). It does
**not** understand parenthesised negatives — `(45.00)` is an error, not `-45.00`.

## Decision: flags or rewrite?

Use flags when the only difference is **naming**. Rewrite the file when the
difference is **structural**.

| Finding | Fix |
|---|---|
| Header is `Posting Date` / `Memo` / `Amount (USD)` | `--date-col`, `--desc-col`, `--amount-col` |
| Card export, purchases positive | `--invert` (native, on `categorize` and `reconcile`) |
| Issuer supplies its own category column named something else | `--category-col "Category"` |
| Dates are `MM/DD/YYYY`, `DD/MM/YYYY`, `12-May-2026` | **rewrite** — `normalize_csv.py` |
| Separate `Debit` and `Credit` columns | **rewrite** |
| `(45.00)` for negatives | **rewrite** |
| Trailing summary/total rows, preamble lines above the header | **rewrite** |
| `CR`/`DR` suffix on the amount | **rewrite** |

## Shape 1 — bank checking export

The common US bank download. Two dates (use the posting date unless the user
says otherwise — it is what the bank reconciles against), a descriptor with
store and reference numbers baked in, and often split debit/credit.

```text
Posting Date,Transaction Date,Description,Debit,Credit,Balance
10/02/2026,10/01/2026,PAYROLL DEPOSIT ACME CORP,,3200.00,8412.55
10/03/2026,10/03/2026,WHOLE FOODS MARKET #781,86.40,,8326.15
```

Structural on two counts (dates and debit/credit), so normalize:

```sh
python3 scripts/normalize_csv.py statement.csv -o work/checking-2026-10.csv \
    --date-col "Posting Date" --desc-col Description \
    --debit-col Debit --credit-col Credit
```

Then the normalized file uses plain `date,description,amount` and needs no
column flags at all.

Notes specific to this shape:

- **A running `Balance` column is a gift** — its last row is the statement's
  ending balance, which is exactly what `beans reconcile ACCOUNT --balance`
  wants in Phase 6. `inspect_csv.py` reports it when present.
- **Debit/credit sign convention is not universal.** Most banks put the
  magnitude in whichever column applies (debit 86.40 = money out). A few write
  debits as already-negative. `normalize_csv.py` detects this and says which
  reading it used; sanity-check it against a row you can identify.
- **Transfers between the user's own accounts appear here** and are the single
  most common categorization error. See `triage-playbook.md`.

## Shape 2 — credit card export

```text
Transaction Date,Post Date,Description,Category,Type,Amount
10/04/2026,10/05/2026,BLUE RIDGE DENTAL ASSOC 41,Health,Sale,210.00
10/09/2026,10/10/2026,AMAZON MKTPLACE 442,Shopping,Sale,31.00
10/22/2026,10/22/2026,PAYMENT THANK YOU,,Payment,-450.00
```

Three things to get right:

1. **Sign.** Purchases are positive here — the opposite of beans convention. The
   card account is a **liability**, so a purchase must reach the ledger as a
   negative (money out of the account, increasing what is owed). Use `--invert`,
   or let `normalize_csv.py` flip it. `inspect_csv.py` flags a probable card
   export when most rows are positive and the descriptors look like merchants.

2. **The issuer's `Category` column.** `beans categorize` treats a row that
   already carries a category as *a decision already made*: confidence 1.00,
   source `column`, never second-guessed (`beans/classify.py` → `Classifier.suggest`).
   That is right when the user filled it in and wrong when Chase did. Issuer
   taxonomies do not match a personal chart of accounts — "Shopping" covers a
   laptop and a birthday present. **Either drop the column** (leave
   `--category-col` pointing at a column that does not exist, or strip it in
   normalization) **and let history do the work, or spot-check every row it
   filled.** Do not silently accept it because the score is 1.00.

3. **The payment row.** `PAYMENT THANK YOU` is a transfer from the checking
   account, not income. It must be categorized to the funding asset account.
   Importing it as income overstates income *and* leaves checking unreconciled.

## Working copies

Never modify the original export — it is the evidence you reconcile against in
Phase 6, and `beans reconcile --statement` should read the file the bank
produced, not your rewrite of it.

Keep working copies in a `work/` directory and make sure it is git-ignored.
Statement data is private, and a prepared CSV carries every merchant the user
paid that month.
