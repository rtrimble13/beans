# Evaluation — an economic balance sheet skill

**Date:** 2026-09-04
**Question:** Is a Claude Code skill worth building that guides someone through
creating an economic balance sheet (or takes their pre-compiled inputs) and
then analyzes the result?
**Branch:** `claude/economic-skill-evaluation`
**Related:** [`reporting_skill_evaluation_20260904.md`](reporting_skill_evaluation_20260904.md),
[`ai_surface_consolidation_20260904.md`](ai_surface_consolidation_20260904.md)
**Method:** read `beans/economic.py` in full (737 lines — the input model,
the PV core, `write_template`, `parse_config`) plus its CLI wiring, MANUAL
section and vignette; then measured the thing that decides the answer —
how much the output moves when the assumptions move — against a seeded
13-month ledger.

---

## Status — accepted and built

Built on this branch, scoped as recommended: `.claude/skills/beans-economic/`
(`SKILL.md`, three references, four scripts, nine evals), covered by 54 new
tests in `tests/test_skill_scripts.py`, plus `install_skill.sh`, README,
`docs/claude-skill-setup.md` and a walkthrough vignette
(`docs/vignettes/11-economic-skill.md`).

What landed matches the verdict below rather than the original ask: the skill
interviews and stress-tests, and explicitly hands narration back to
`beans ai review --focus economic`. `econ_io.parse_rate` refuses the ambiguous
`0.03` form; `build_config.py` records every excluded line with its reason,
writes the sixth line the stock template cannot reach, and proves its output
parses before the file lands; `sensitivity.py` ranks drivers by span, bisects
the sign-flip boundary, and reports *inert* inputs separately from small ones.

**The three product findings remain open** and are deliberately not papered
over by the skill — the skill reports the default divergence rather than hiding
it. They are worth their own change: align the two default paths, guard the
ambiguous percent in `parse_config`, and reconsider the single discount rate.

---

## Verdict

**Yes — but rotated about 90° from the description.**

The three jobs in the ask are not equal, and one of them is already shipped:

| Job asked for | Verdict |
|---|---|
| Guide the user to create an EBS | **Yes.** This is where nearly all the value is. |
| Take pre-compiled inputs | **Fold in.** A path through the first job, not a second mode. |
| Analyze the result | **No, as stated** — `beans ai review --focus economic` and the MCP `beans_economic_balance_sheet` tool already narrate one EBS. **Yes, reshaped:** analyze the result's *dependence on its inputs*. |

The one-sentence version: **an economic balance sheet is not a measurement, it
is a model, and the useful output is not the number but which assumptions the
number is hostage to.** A skill that produces one authoritative-looking figure
would make this feature more dangerous, not more useful. A skill that says
"your answer is +$513k, it turns negative if inflation is 3%, and the
retirement date moves it more than anything else" is worth building.

---

## Evidence: the output is dominated by its assumptions

All figures below are the *same ledger, same day* (2026-09-04, financial
capital $65,042, accounting net worth $63,142). Only the assumptions change.

| Assumptions | Economic net worth |
|---|---:|
| defaults (3% / 0% growth / 0% inflation / 25y work / 40y horizon) | **$512,714.80** |
| income growth 3% | **$1,069,479.92** |
| inflation 3% | **−$114,889.96** |
| work-years 15 | $96,467.61 |
| live-years 55 | $375,275.89 |
| discount 5% | $488,285.63 |
| discount 1% | $490,411.14 |

A single assumption — price inflation at 3%, which is unremarkable — moves this
household from **half a million dollars ahead to a hundred thousand behind**.
Nothing in the ledger changed. Nothing is wrong with the arithmetic. The number
is simply not a fact about the household; it is a fact about the inputs.

### The discount rate does not behave the way anyone expects

Sweeping only the rate, holding everything else:

| Rate | Human capital | Future consumption | Economic net worth |
|---:|---:|---:|---:|
| 0.5% | 1,776,299.44 | 1,368,615.30 | 470,826.14 |
| 1% | 1,671,653.08 | 1,244,383.94 | 490,411.14 |
| 2% | 1,486,359.68 | 1,039,046.76 | 510,454.92 |
| **3%** | 1,328,521.66 | 878,948.86 | **512,714.80** ← peak |
| 4% | 1,193,550.64 | 752,862.02 | 503,830.62 |
| 5% | 1,077,678.30 | 652,534.67 | 488,285.63 |
| 10% | 693,297.55 | 370,548.80 | 385,890.75 |

Economic net worth is **non-monotonic in the discount rate**. Both sides shrink
as the rate rises — but consumption runs 40 years and income only 25, so at low
rates the longer stream dominates and the difference *widens*; past the
crossover the larger stream dominates and it narrows again. Where the peak
falls depends on the relative size and duration of the two streams, so it is
this household's peak, not a universal one.

The consequence is specific and worth stating plainly. `docs/MANUAL.md`
currently advises:

> Raise `--rate` for a volatile or commission-based income and lower it for a
> tenured or government salary; the discount rate is where income risk enters
> the analysis.

That is the standard intuition, and with a single rate applied to both sides it
does not reliably do what it says: raising the rate to reflect risky income
*also* discounts that household's future groceries. From 0.5% to 3% the
"conservative" move raises economic net worth; from 3% to 10% it lowers it.
Someone following the advice cannot predict the direction of their own
adjustment.

This is a limitation of the model, not a bug in the code — but it is exactly
the kind of thing that needs saying out loud every time the number is quoted,
which is a job for a skill (and, better, for the product; see below).

---

## Evidence: the inputs are not derivable, and the defaults are choices

`auto` mode only works for two of the six lines —
`_RUN_RATE_KINDS = ("income", "consumption")` (`beans/economic.py:75`) — because
those are the only ones with anything in the books to project from. The other
four are pure assertions about a life:

| Line | Where the number comes from |
|---|---|
| Human capital | ledger run-rate, **or** a retirement date you assert |
| Future consumption | ledger run-rate, **or** a spending path you assert |
| Pension / benefits | **only** from you |
| Inheritance / other | **only** from you |
| Bequests | **only** from you |
| Other obligations | **only** from you |

And the template ships all four of those as `Mode: none`. An unedited template
therefore models a household with no pension, no inheritance and no bequest —
which is a substantive claim wearing the costume of a default. For most
households at least one of those is wrong.

That is the case for elicitation. These are not fields to fill in; they are
questions to be asked, and the answers move the result more than anything in
the ledger does.

### Two traps a review-first workflow would catch

Both found by running the tool, not by reading it.

**1. The two default paths disagree by 40%.** On the same ledger, the same day:

```
beans economic npv                       →  $512,714.80   (growth 0%, inflation 0%)
beans economic create-template -o x.md
beans economic npv --file x.md           →  $305,848.20   (growth 1%, inflation 2%)
```

Nothing was edited. `write_template` defaults to `income_growth=0.01,
inflation=0.02` (`beans/economic.py:448`) while the no-file path uses the
`EconomicInputs` dataclass defaults of zero. Both are defensible; having both
is not. A $207k gap between "the quick estimate" and "the starting template"
will read as a bug to anyone who tries both.

**2. `0.03` silently means 0.03%, not 3%.** `parse_percent` reads bare numbers
as percent units, so a hand-edited `| discount_rate | 0.03 |` is accepted and
future consumption nearly doubles ($1,242,700 → $2,295,247). The header does
print `Discount 0.0%`, so it is detectable — but 0.03% *renders* as 0.0%, which
looks like a formatting quirk rather than a two-orders-of-magnitude error.

---

## Where the skill would NOT add value

Said plainly, because it is half the ask.

**Narrating one EBS is already shipped, twice.** `beans ai review --focus
economic` exists, and `beans/ai/prompts.py` already instructs the model to
"explain human capital…, and how economic net worth differs from accounting
net worth. These rest on assumptions — name them." The MCP server exposes
`beans_economic_balance_sheet`, and `focus: "economic"` adds it to the review
bundle. A skill whose analysis phase produces that same narrative is the
duplication the reporting-skill evaluation warned about, and would be worse
than nothing: two ways to ask the same question, with no way to tell which one
you want.

**The template is not a rescue case.** It is genuinely self-documenting, it
pre-fills real run-rates, and the parser's errors are specific and actionable —
`invalid mode 'sclar' for 'Human capital — future income' (expected auto,
scalar, stream, none)`, `invalid whole number for work_years: 'twenty-five'`.
A hand-authored `stream` config with a retirement stop and a later pension
parsed correctly on the first attempt. This is a well-built format; a skill
that mostly explains it is documentation with extra steps, and the MANUAL
already has that covered in depth.

So the skill has to earn its place on elicitation and on sensitivity. It does.

---

## What the skill should actually be

`.claude/skills/beans-economic/`, in the `beans-import` / `beans-report` mould.
Read-only with respect to the ledger; the only thing it writes is a config
document the user approves.

### Phase 0 — Preflight

Resolve the ledger, the run-rates `auto` would use, and how much history backs
them. Six months of data behind a 25-year human-capital projection is a fact
the briefing must carry. Check whether a config document already exists — an
existing plan is edited, never regenerated over.

### Phase 1 — Elicit, or ingest

**Elicit** is a conversation with a fixed agenda, one question per line of the
statement: when do you stop working; what happens to spending then; is there a
pension or annuity, from when, how much; is there an inheritance you would
actually plan around; is there a bequest you intend to leave. Each answer maps
to a `Mode:` and a table, and the mapping — not the arithmetic — is the work.

**Ingest** is the same agenda run in reverse: take whatever the user already
has, map it onto the six lines, and *report the gaps rather than defaulting
them*. A line the user did not mention is `Mode: none`, and the skill says so
explicitly instead of letting silence become a modelling choice.

Both paths end at the same place: a written config, shown in full, approved
before it is used. That document is the audit trail — the MANUAL is already
right about that, and the skill's job is to make it honest rather than to
replace it.

### Phase 2 — Sensitivity, which is the analysis

Run the model repeatedly and report **what the conclusion depends on**, not the
conclusion. Concretely:

- **One-at-a-time sweeps** over discount rate, income growth, inflation, work
  years and horizon, reported as the range each one produces. On the ledger
  above: inflation alone spans $627k and flips the sign; the discount rate over
  a plausible 1–5% band spans $24k. Those two facts, side by side, tell the
  user which number to go and think harder about.
- **The sign-flip boundary.** "Your economic net worth goes negative if
  long-run inflation exceeds X%" is the single most useful sentence this
  analysis can produce, and no command emits it today.
- **Scenario diffs.** The MANUAL already recommends keeping `base.md` and
  `retire-early.md` and diffing them, and that diff is currently manual
  arithmetic across two command outputs. The skill runs both and reports the
  delta as what it is: the cost of the decision in today's dollars.
- **The non-monotonic rate**, stated whenever the rate is discussed, because
  the intuition is wrong and the MANUAL currently reinforces it.

### Phase 3 — Brief

Short, and structurally different from the reporting skill's briefing: it leads
with the assumptions, not the answer. The number, the two or three inputs it is
most hostage to, the sign-flip boundary if one exists within a plausible range,
and the reconciliation back to accounting net worth (which is the one figure in
the whole statement that is not an assumption).

Footer: `Not licensed financial advice.` — same as everywhere else, and it
carries more weight here than it does on a spending trend.

### Guardrails

1. **Never present an economic net worth without the assumptions that produced
   it** in the same breath. Not in a footnote.
2. **Never let a `Mode: none` pass silently.** An excluded pension is a claim.
3. **Never invent a life fact.** No assumed retirement age, no assumed
   inheritance, no assumed lifespan. Ask, or mark it excluded and say so.
4. **Never quote a horizon the ledger cannot support** without saying how much
   history backs the run-rate.
5. **Always report the range, not just the point.** A single figure from this
   model is the one output shape that misleads.
6. **Never write to the ledger.** These inputs are deliberately never posted;
   that separation is the feature.
7. **Never overwrite an existing config** — it is someone's plan. New file,
   and say why.
8. **Check the percent forms** before running: a bare `0.03` is 0.03%.

---

## Product findings, separable from the skill

Three of these a skill would paper over. Papering over is worse than fixing.

1. **Align the two default paths** (`beans/economic.py:448` vs the
   `EconomicInputs` dataclass). Whichever pair is right, both entry points
   should use it. Currently 40% apart.
2. **Reject an ambiguous percent**, or warn: a `discount_rate` under, say,
   0.5 is almost certainly a decimal the user meant as a percent. A one-line
   guard in `parse_config` removes a two-orders-of-magnitude silent error.
3. **Consider a separate human-capital discount rate.** One rate for both sides
   is what makes the MANUAL's risk advice unreliable. A
   `--human-capital-rate` (defaulting to the single rate, so nothing changes
   unless asked) would let income risk be priced without repricing groceries.
   Until then, soften that MANUAL paragraph.

And one feature idea that is to this skill what `beans report trend` was to
`beans-report`: **`beans economic bs --sensitivity`**, emitting the one-at-a-time
ranges and the sign-flip boundary as structured JSON, plus
**`--compare other.md`** for a scenario delta. Both are deterministic
arithmetic over the existing PV core, they belong in `_toolcore` where MCP and
`beans ai` inherit them, and they would let the skill shrink to what it should
be: the conversation and the judgement, not the sweeping.

Sequence it the way the reporting work went — skill first, because the skill
will show which sweeps people actually want; product second.

---

## Bottom line

Build it, scoped to **elicitation and sensitivity**, not to narrating a
statement that two shipped surfaces already narrate. The measurements are the
argument: the same ledger yields anywhere from −$115k to +$1.07m depending on
assumptions nobody validated, four of the six input lines cannot be derived
from the books at all, and the two default paths through the feature disagree
by 40% before a user has typed anything.

That is not a reporting problem. It is a modelling problem wearing a report's
clothing, and the honest deliverable is a range with its drivers named — which
is precisely the kind of work that needs a conversation first and a briefing
second.

*Not licensed financial advice.*
