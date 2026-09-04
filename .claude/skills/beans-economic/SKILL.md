---
name: beans-economic
description: >-
  Build and stress-test an economic (holistic) balance sheet on a beans ledger —
  "what's my economic net worth", "value my human capital", "can I afford to
  retire at 60", "what would retiring five years early cost me", "build my
  economic balance sheet", "model my pension", "how sensitive is my plan to
  inflation". Interviews the user for the six forward-looking lines beans cannot
  derive from the books (future income, spending, pension, inheritance, bequests,
  obligations), writes a validated `beans economic` config document from the
  answers, then reports what the answer actually depends on: which assumption
  moves it most, whether it is monotonic, and the inflation or retirement date at
  which economic net worth crosses zero. Read-only against the ledger — the
  forward-looking inputs are assumptions and are never posted. Not for ordinary
  reporting (that is `beans report` and the beans-report skill), not for
  importing statements (beans-import), and not for simply narrating one economic
  balance sheet — `beans ai review --focus economic` already does that.
---

# beans — the economic balance sheet

An economic balance sheet is **not a measurement, it is a model**. Exactly one
of its lines comes from the books — Financial Capital. The other five come from
somebody's beliefs about their own life, and those beliefs move the answer far
more than anything in the ledger does.

On one real ledger, holding the books completely constant:

| Change one assumption | Economic net worth |
|---|---:|
| defaults | $512,714.80 |
| income growth 3% | $1,069,479.92 |
| **inflation 3%** | **−$114,889.96** |

A single unremarkable inflation assumption takes that household from half a
million ahead to a hundred thousand behind. Nothing was wrong with the
arithmetic. The number is simply not a fact about the household; it is a fact
about the inputs.

So the deliverable here is never a number. It is **a number, its assumptions,
and the range those assumptions produce** — with the input that matters most
named first.

## What this skill is not for

- **Narrating one economic balance sheet.** `beans ai review --focus economic`
  and the MCP `beans_economic_balance_sheet` tool already do that, and
  `beans economic bs` prints it directly. If the user just wants the statement,
  run the command and show it.
- **Ordinary reporting.** Income statements, budgets, spending trends — those
  are `beans report`, `beans analyze` and the `beans-report` skill.
- **Writing to the ledger.** The forward-looking inputs are deliberately never
  posted. That separation is the whole design.

## Guardrails

Non-negotiable. If one conflicts with what you were asked, say so and stop.

1. **Never present an economic net worth without the assumptions that produced
   it, in the same breath.** Not in a footnote, not further down. The number
   alone is the one output shape that misleads.
2. **Never let `Mode: none` pass silently.** An excluded pension is a claim
   that there is no pension. `build_config.py` records every excluded line and
   its reason; repeat them in the briefing.
3. **Never invent a life fact.** No assumed retirement age, no assumed
   lifespan, no assumed inheritance. Ask, or mark the line excluded and say
   which one you excluded and why.
4. **Always report the range, not just the point.** Run `sensitivity.py` before
   briefing. If you are quoting one figure, you are doing this wrong.
5. **Never quote a horizon without its provenance.** Preflight reports the
   ratio — thirteen months of history projected twenty-five years forward is
   1:23. Say it whenever you quote human capital.
6. **Rates always carry a `%`.** `beans` reads a bare `0.03` as 0.03%, not 3%,
   and nearly doubles future consumption without complaining. `econ_io.parse_rate`
   refuses the ambiguous form; do not work around it.
7. **Never overwrite an existing config document.** It is somebody's plan.
   Write a new file and say why.
8. **Never write to the ledger**, and never run `beans economic create-template`
   — this skill writes its own config from answers the user gave, and
   `create-template` would clobber a plan.
9. **The reconciliation is the honest anchor.** Economic net worth always ties
   back to accounting net worth plus the assumed lines. Show both.
10. **End with:** `Not licensed financial advice.`

## Phase 0 — Preflight

```sh
cd .claude/skills/beans-economic/scripts
./preflight.py --lookback 12 --work-years 25    # add -f PATH for a non-default ledger
```

Read, and carry forward: **accounting net worth** (the one figure that is not an
assumption), the **run-rate basis** `auto` would use, how many months of history
stand behind it, and the **projection leverage** ratio. Also note whether the
run-rate is *drifting* — a flat annuity taken off a base that is climbing will
be wrong for the entire horizon, and preflight says which accounts are moving.

Exit status 1 is a blocker (no beans, unreadable ledger, no transactions).
Warnings are not blockers but every one belongs in the briefing.

## Phase 1 — Elicit, or ingest

Six lines. Two can be estimated from the ledger; four can only come from the
user. Work the agenda in `references/interview.md`; the short form is:

| Line | The question |
|---|---|
| Human capital | When do you stop working, and does the income change before then? |
| Future consumption | Does spending change when you stop working? |
| Pension / benefits | Is there a pension or annuity — from when, how much, indexed? |
| Inheritance | Is there one you would genuinely plan around? |
| Bequests | Do you intend to leave a specific amount? |
| Other obligations | Anything large and future — care costs, tuition, a settlement? |

**If the user already has inputs**, run the same agenda in reverse: map what
they brought onto the six lines, and **report the gaps rather than defaulting
them**. A line they did not mention is `Mode: none`, and you say so — silence
must never become a modelling choice on someone's behalf.

Two answers deserve pushing back on, gently, every time:

- *"Just use the ledger run-rate"* for consumption over a 40-year horizon.
  That models someone whose spending never changes for the rest of their life.
  Ask what happens at retirement.
- *"Assume I work to 65"* when the user has not thought about it. It is the
  second-largest driver in most plans; it deserves a real answer.

## Phase 2 — Build the document

Collect the answers into the JSON schema in `references/config-format.md`, then:

```sh
./build_config.py answers.json -o plan.md -f ~/.beans/ledger.db
```

It validates every field, refuses ambiguous rates, chooses the correct table
shape per mode, and **proves the result parses by running
`beans economic npv --file` against it before the file lands**. It will not
overwrite an existing plan.

Show the user the document. It is the audit trail of their assumptions and it
is meant to be read, kept, and diffed later.

## Phase 3 — Sensitivity, which is the analysis

```sh
./sensitivity.py --file plan.md -f ~/.beans/ledger.db -o sens.json
./sensitivity.py --file plan.md --compare retire-early.md -f ~/.beans/ledger.db
```

Roughly forty read-only runs, a few seconds. It returns:

- **`drivers`** — every swept assumption ranked by the span it produces. This
  is the ranking to lead the briefing with.
- **`sign_flips`** — the value at which economic net worth crosses zero, found
  by bisection. *"Your plan goes negative above 2.60% long-run inflation"* is
  the most useful single sentence this analysis produces.
- **`inert`** — assumptions the config pins, so the global setting does
  nothing. A `stream` schedule carries its own growth and its own end date, so
  sweeping `income_growth` on such a plan moves nothing. Saying so prevents a
  false sense of robustness.
- **`monotonic`** plus a note when it is false. **The discount rate is not
  monotonic**: it discounts human capital *and* future consumption over
  different horizons, so raising it "to be conservative" can raise or lower the
  answer depending on where you started. Never describe a rate change as
  conservative without checking.
- **`comparison`** — a scenario diff, line by line. That delta is the cost of
  the decision in today's dollars, which is what the user actually asked.

## Phase 4 — Brief

Lead with the assumptions, not the answer. Structure:

```
ECONOMIC BALANCE SHEET — <as-of>

Accounting net worth (from the books):   $X
Economic net worth (model output):       $Y

It rests on: <the 3-4 assumptions, with values>
Backed by:   <N months of history projected M years forward — 1:R>

What moves it, most first:
  1. <assumption> — range $A to $B across <band>
  2. …

Breaks even at: <sign-flip boundary, if one falls in a plausible range>
Excluded (modelled as zero): <every Mode: none line, with its reason>

Not licensed financial advice.
```

Rules for the prose:

- Give the range with the figure, always.
- Name what was excluded. Every time.
- Say which numbers are actuals (financial capital, accounting net worth) and
  which are model output (everything else).
- If the user asked a decision question ("should I retire early?"), answer with
  the scenario delta, not the level — and say plainly that the delta inherits
  every assumption both scenarios share.

### Keeping the plan

Config documents are meant to accumulate: `base.md`, `retire-early.md`,
`no-inheritance.md`. Suggest keeping them next to the ledger and out of any
repository the user pushes — a plan document states a retirement date, a
pension and an expected inheritance.

## References

- `references/interview.md` — the elicitation agenda, line by line: what to
  ask, what the answer maps to, and the follow-up that usually matters.
- `references/config-format.md` — the answers schema, the document format, the
  six headings, and the traps (ambiguous rates, lump sums vs schedules).
- `references/sensitivity.md` — how to read the sweeps, why the discount rate
  is non-monotonic, and what to do about inert parameters.
- `scripts/preflight.py`, `scripts/build_config.py`, `scripts/sensitivity.py` —
  all take `--help`; covered by `tests/test_skill_scripts.py`.
