# Command reference — the read-only reporting surface

Only the commands this skill may run. Every one is read-only; anything that
writes is refused by `beans_io.assert_read_only` before a subprocess starts.

Requires **beans 1.1+** for `report trend`; the skill degrades to a slower
path on older versions (see below) rather than failing.

## The shape of the surface

Almost every statement is a snapshot of one period, and `report income
--compare` reaches exactly one period back. The two exceptions are the two the
skill leans on.

| Command | Shape | Time series? |
|---|---|---|
| `report income` (+`--compare`) | one period, optionally vs. the immediately prior one | no |
| `report balance` / `report trial` | as of a date | no |
| `report cashflow` | one period | no |
| `analyze` | one period, plus position as of its end | no |
| `budget report` | one period | no |
| `forecast` | forward projection | forward only |
| `networth` | month-end rollup | **yes** — assets, liabilities and net worth only |
| **`report trend`** | income, expenses, net and every account across N periods | **yes** — this is the series |

`report trend` landed in beans 1.1 and is what `series.py` calls. Against an
older beans it has no such command, so the script falls back to running
`report income` once per period and assembling the same shape itself; the
`source` field in its output says which path ran. Nothing downstream changes.

**There is still no ratio series** — `analyze` is per-period — which is why
`--ratios` costs one call per period.

## Period grammar

Accepted by `--period` everywhere: `all`, `ytd`, `this-month`, `last-month`,
`this-quarter`, `last-quarter`, `this-year`, `last-year`, `YYYY`, `YYYY-MM`,
`YYYY-QN`. `--from` / `--to` take ISO dates and override a named period.

`YYYY-MM` and `YYYY-QN` are what this skill uses: they are absolute, so a
series is reproducible tomorrow. The relative names (`this-month`,
`this-quarter`) resolve against today and **truncate at today**, which is the
partial-period trap — see `method.md`.

`report income --period all --compare` degrades gracefully: it prints the
statement and notes that a comparison is unavailable for an unbounded period.

## `--json` availability

Most commands take `--json`. Two the skill needs do **not**:

- `beans config list` — plain `key = value` lines. `series.read_config` parses
  them for currency and decimals.
- `beans period status` — prose. Use `beans status --json` instead, whose
  `closed_through` field carries the same fact.

## Commands and their JSON

### `report trend [--periods N] [--grain month|quarter] [--end P]`
```json
{"report": "trend", "grain": "month", "period_count": 12,
 "periods": ["2025-09", "…", "2026-08"],
 "complete_through": "2026-08", "excluded_partial": "2026-09",
 "rows": [{"period": "2025-09", "start": "2025-09-01", "end": "2025-09-30",
           "partial": false, "income": "6000.00", "expenses": "2889.00",
           "net_income": "3111.00", "savings_rate_pct": 51.9}],
 "accounts": [{"account": "Expenses:Food:Groceries", "type": "expense",
               "amounts": ["530.00", "…", "746.00"], "total": "…",
               "average": "…", "first": "530.00", "last": "746.00",
               "change": "216.00"}],
 "totals": {"income": "…", "expenses": "…", "net_income": "…",
            "complete_periods": 12, "average_income": "…",
            "average_expenses": "…", "savings_rate_pct": 54.3}}
```
`accounts` is ranked by largest absolute change and holds one figure per
period, in `periods` order. Accounts with no flow anywhere in the window are
omitted entirely rather than carried as rows of zeros.

The window ends at the last **complete** period; `excluded_partial` names the
one left out, and is `null` when nothing was in progress (run on the last day
of a month, for instance). `--include-partial` includes it, marks the row
`"partial": true`, and still keeps it out of the averages — which is why
`totals.complete_periods` can differ from `period_count`.

### `report income --period P [--compare]`
```json
{"report": "income_statement", "period": "August 2026",
 "start": "2026-08-01", "end": "2026-08-31",
 "income":   {"Income:Salary": "6600.00"},
 "expenses": {"Expenses:Food:Groceries": "786.00", "…": "…"},
 "total_income": "6600.00", "total_expenses": "3104.00",
 "net_income": "3496.00",
 "compare": { …the same shape for the prior period… }}
```
An account with no flow in the period is **absent**, not zero. That is a real
zero and `series.py` fills it as one.

### `analyze --period P`
Ratios, already computed — never recompute them. Fields:
`income`, `expenses`, `net_income`, `savings_rate_pct`, `total_assets`,
`total_liabilities`, `net_worth`, `cash`, `current_assets`,
`current_liabilities`, `working_capital`, `current_ratio`, `quick_ratio`,
`liquidity_months`, `debt_to_assets_pct`, `debt_to_annual_income_pct`,
`top_expenses`. Flows are for the period; position is as of its end.

### `networth --months N`
```json
{"report": "net_worth_trend", "months": 14,
 "rows": [{"month": "2025-09", "as_of": "2025-09-30", "assets": "26589.00",
           "liabilities": "1400.00", "net_worth": "25189.00",
           "change": "3299.00"}]}
```
Anchored to the current month, so the final row is the *partial* month.
`series.py` filters to the window's periods, which drops it.

### `budget report --period P`
`rows` is empty when no budgets are set — not an error. `months` is the
fraction of a month the period covers, which is `0.13` for a four-day-old
month: another face of the partial-period trap.

### `recur list`, `goal list`, `budget list`
`{"rules": [...]}`, `{"rows": [...]}`, and a bare list respectively. The first
two are what Phase 3 reconciles actuals against.

### `forecast [--months N] [--method average|trend]`
Projection plus per-account drivers under `accounts`, each with the monthly
basis and how it was derived. Compare that basis against a drifting account's
latest level — see the stale-basis pattern in the playbook.

### `register <account> --period P`, `search <text>`, `tx list`
Transaction-level, and they carry payee and description text. Aggregates first;
reach for these only to drill into a finding the user asked about.

## Amounts, signs and currency

Every money value is a major-unit decimal string in the ledger's base currency
(`"1234.56"`). The reports have already applied the natural sign, so a positive
number means what its label says: income earned, expense incurred, asset held.
Parse with `Decimal`, never `float`, and re-emit at the ledger's `decimals`.

Foreign-denominated accounts carry parallel foreign balances at their own
precision; the statements stay in the base currency.

## Refused, always

`import`, `categorize`, `tx add`, `tx void`, `spend`, `earn`, `transfer`,
`undo`, `budget set`, `budget remove`, `rule add`, `rule remove`, `recur run`,
`recur pause`, `recur resume`, `recur remove`, `goal add`, `goal remove`,
`period close`, `period reopen`, `invest buy`, `invest sell`, `invest mark`,
`price set`, `currency revalue`, `clear`, `restore`, `init`.

Recommendations that need one of these are written out for the user to run.
