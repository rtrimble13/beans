# The answers schema and the document format

## The answers JSON

What you hand `build_config.py`. Everything optional except
`settings.discount_rate`; any line you omit becomes `Mode: none` with the note
"not discussed".

```json
{
  "as_of": "2026-09-04",
  "settings": {
    "discount_rate": "3%",
    "income_growth": "1%",
    "inflation": "2%",
    "work_years": 25,
    "live_years": 40,
    "lookback_months": 12
  },
  "lines": {
    "income": {
      "mode": "stream",
      "note": "Salary now; stops at retirement in 2046.",
      "segments": [
        {"from": "2026-09-01", "amount": "6600", "growth": "1%"},
        {"from": "2046-09-01", "amount": "0"}
      ]
    },
    "consumption": {"mode": "auto", "note": "From the ledger run-rate."},
    "pension": {
      "mode": "stream",
      "segments": [{"from": "2046-09-01", "amount": "2400", "growth": "2%"}]
    },
    "inheritance": {
      "mode": "stream",
      "flows": [{"date": "2040-01-01", "amount": "50000"}]
    },
    "bequest": {"mode": "none", "note": "Nothing planned."},
    "other": {"mode": "scalar", "amount": "500", "growth": "2%", "years": 10,
              "note": "Care costs for a parent."}
  }
}
```

The six `lines` keys are exactly: `income`, `consumption`, `pension`,
`inheritance`, `bequest`, `other`. Anything else is refused.

## Modes

| Mode | Means | Needs |
|---|---|---|
| `auto` | estimate from the ledger run-rate | nothing — **only valid for `income` and `consumption`** |
| `scalar` | a flat or growing monthly amount over a horizon | `amount`, optional `growth`, optional `years` |
| `stream` | a piecewise schedule, **or** dated lump sums | exactly one of `segments` or `flows` |
| `none` | excluded — modelled as zero | nothing, but give a `note` |

`auto` on any line but income or consumption is refused, with the reason: there
is nothing in the books to estimate a pension from.

## `segments` vs `flows`

This is the distinction that is easy to get wrong, so the script enforces it.

- **`segments`** — a *monthly* schedule. Each entry's amount prevails from its
  date until the next entry's date. Dates must strictly ascend. A final segment
  of `0` is how you stop a stream (retirement).
- **`flows`** — *one-off* dated lump sums. An inheritance received, tuition
  paid, a settlement.

Under the hood the difference is a column: beans reads a table with a `Growth`
column as a monthly schedule and one without as lump sums. `build_config.py`
emits the right shape, which is most of why it exists.

## Rates

**Always write a `%`.** `beans` reads a bare number as a percentage, so `3` and
`3%` both mean 3% — but `0.03`, the other natural way to write 3%, means
**0.03%**. It is accepted silently and roughly doubles future consumption.

`econ_io.parse_rate` refuses any bare number below 0.5 and says what it would
have meant. Every rate this skill writes carries an explicit `%` so a document
it produced can never be re-read as a fraction.

Negative growth is allowed (a declining income, deflation); a negative discount
rate is not.

## The document it writes

Six `##` sections, headed so that beans' own keyword matching lands on the
intended line:

| Heading written | Maps to |
|---|---|
| `## Human capital — future income` | income |
| `## Future consumption — spending` | consumption |
| `## Pension / benefits` | pension |
| `## Expected inheritance` | inheritance |
| `## Bequests` | bequest |
| `## Other obligations` | other |

Note the last two are **separate sections**. The stock
`beans economic create-template` combines them into one
("Bequests / other obligations"), which beans matches to `bequest` — so the
sixth line is unreachable from the stock template. Writing them apart is how
this skill gets at it.

Each section carries the user's note as prose above its `Mode:` line, and every
excluded line is also listed in a comment block near the top, so the exclusions
are visible without reading the whole document.

## Validation

`build_config.py` renders to a temporary file, runs
`beans economic npv --file` against it, and only moves it into place if that
succeeds. A document this skill wrote is therefore always one beans can read.

It refuses to overwrite an existing file without `--force`, because a config
document is somebody's plan and is meant to be kept and diffed.
