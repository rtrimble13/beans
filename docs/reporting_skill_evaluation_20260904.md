# Evaluation — a `beans-report` agent skill

**Date:** 2026-09-04
**Question:** Is there value in a Claude Code skill that drives `beans`'
report features to summarize trends and make inferences? If so, how should it
be built?
**Branch:** `claude/reporting-skill-evaluation-n4csum`
**Companion:** [`ai_surface_consolidation_20260904.md`](ai_surface_consolidation_20260904.md) — whether `beans ai` and the MCP server should be removed in favour of this skill (verdict: no).
**Method:** read the reporting surface (`reports.py`, `analysis.py`,
`forecast.py`, `budget.py`, `_toolcore/`, `mcp/server.py`, `ai/`), then
exercised every claim below against a purpose-built 14-month ledger.

---

## Verdict

**Yes — but not as "another way to ask beans for reports."** That job is
already done, and done well, by the MCP server and `beans ai review`. A skill
that re-renders statements Claude can already fetch would be negative value:
context spent to duplicate a shipped feature.

The real gap is narrower and more defensible: **`beans` has no time series.**
Every report except `networth` is a single-period snapshot, and the one
comparison it offers (`--compare`) reaches exactly one period back. Nothing in
the product — not `analyze`, not `review_bundle_spec`, not the MCP tool set —
can answer *"is my grocery spend drifting up, and what does that do to my
runway?"* That question requires assembling a series across N periods and
reasoning over it, which is precisely a client-side job.

So the skill is worth building, scoped to **trend and inference**, and
explicitly *not* to period reporting.

---

## The evidence

### 1. The reporting surface is snapshot-shaped

| Report | Shape | Time series? |
|---|---|---|
| `report income` (+`--compare`) | one period, optionally vs. the *immediately* prior one | no |
| `report balance` / `trial` | as-of a date | no |
| `report cashflow` | one period | no |
| `analyze` | one period + as-of position | no |
| `budget report` | one period | no |
| `forecast` | forward projection | forward only |
| `networth` | month-end series | **yes — but only assets / liabilities / net worth** |

`beans/_toolcore/bundle.py:12` (`review_bundle_spec`) is the canonical
"analyst report set" shared by `beans ai review` and the MCP
`beans_review_bundle` tool. It gathers six reports, all period-scoped. There is
no expense-by-category series, no income series, no savings-rate series, and no
ratio series anywhere in the product.

### 2. Building the series is cheap — the *method* is the hard part

Measured on the 14-month test ledger:

```
12 × `beans report income --period YYYY-MM --json`  →  0.94 s, 5,632 bytes total
```

Mechanically trivial. But a naive month-over-month walk is actively dangerous.
The current month is a **stub**. On 2026-09-04, four days into September:

```
report income --period this-month : income 0.00, expenses 1800.00, net -1800.00
analyze      --period this-month : savings_rate null, liquidity_months 4.6
analyze      --period ytd        : savings_rate 50.8%, liquidity_months 19.8
```

A trend that includes the current period reports *"income collapsed to zero and
your runway fell from 19.8 months to 4.6"* — a false alarm about someone's
livelihood, produced from correct numbers read incorrectly. That single trap is
the strongest argument for the skill: what Claude is missing is not tool access,
it is **analyst discipline**.

Other traps the same class of work walks into, all verified against this ledger:

- **One-off vs. drift.** Groceries here climb +$22/month for 14 months (real
  drift). A single $2,000 vet bill would move the same average further and mean
  nothing. Averages alone cannot tell them apart.
- **Stale forecast basis.** `forecast` prices groceries at the 6-month average
  ($720.17/mo) while the last observed month was $786 and rising. The forecast
  is not wrong — it is *average-based on a trending series*, and nothing in the
  product notices.
- **Transfers are not savings.** The $800/mo checking→savings transfer moves no
  income and no expense. Any "savings rate" narrative built by eye off the
  register would double-count it.
- **Trend quality follows data quality.** A ledger with a fat
  `Expenses:Other` bucket or a long-unreconciled account produces category
  trends over noise.

### 3. Cost profile favors a skill over the MCP path

Through MCP, a 12-month series is 12 tool calls — twelve host approvals, twelve
round-trips, twelve JSON blobs in context. Through a skill with a gather script,
it is **one** `Bash` call returning one tidy series. Same numbers, an order of
magnitude less ceremony. This is the mechanical half of the value.

### 4. What it must not duplicate

`beans ai review`, the MCP `review` prompt, and `ai/prompts.py:review_system`
already deliver a CFO-style briefing: headline health, what changed vs. the
prior period, ranked concerns, actionable suggestions, "Not licensed financial
advice." The skill must **start where that stops** — at the second period back —
or the two will produce near-identical output and the user will not know which
to invoke.

---

## Risks, honestly

| Risk | Mitigation |
|---|---|
| Overlaps `beans ai review` / MCP `review` | Scope the description to *multi-period trend and inference*; state the boundary in `SKILL.md` and cross-link both directions. |
| **The `beans-import` skill's description is contradicted.** It currently reads *"Not for reports, budgets, forecasting or financial analysis — those are read-only questions the beans MCP server already answers."* | That sentence becomes false the day this ships. It must be amended in the same change, or the two skills fight over triggering. |
| Inference on personal finance is advice-adjacent | Reuse the existing footer verbatim: `Not licensed financial advice.` Frame findings as observations plus *proposed commands*, never as instructions. |
| Fabricated figures | Same guardrail `ai/prompts.py` already encodes — never compute money in prose, cite only gathered figures. `ai/review.py:_fabrication_warnings` is the in-repo precedent for checking it. |
| Financial math drifting outside the tested product | Put arithmetic in a **script**, not in prose, and test it in `tests/test_skill_scripts.py` (that file already exists for exactly this reason). |
| Privacy | Work from aggregates by default; pull `register`/`search` only for a drill-down the user asked for. `_toolcore/redaction.py` is the existing posture. |

---

## Recommended plan

### Phase 1 — the skill, no product change (ships on its own)

`.claude/skills/beans-report/`, mirroring the `beans-import` layout so the two
read as one family.

```
SKILL.md
scripts/
  series.py       gather N periods of a report into one tidy series
  trend.py        deltas, medians, drift vs. one-off classification
  preflight.py    data-quality gate (see Phase 1c)
references/
  command-reference.md    report surface, period grammar, JSON shapes
  method.md               how to read a series without lying to yourself
  inference-playbook.md   named patterns → what they mean → what to propose
evals/evals.json
```

**1a. Guardrails** (the section that does the real work — model on
`beans-import`'s):

1. **Never include an incomplete period.** Resolve "today" first; the current
   month/quarter is excluded from the trend unless the user asks for it, and if
   included it is labelled *partial* everywhere it appears.
2. **Never compute money in prose.** Figures come from `--json` output; derived
   deltas come from the tested script.
3. **Read-only.** Never `import`, `recur run`, `budget set`, `period close`.
   Proposals are emitted as commands the user runs.
4. **Never assert a trend from fewer than N periods** (suggest 6; 3 minimum,
   and say the confidence is low).
5. **A one-off is not a trend.** Classify before narrating.
6. **State the data-quality caveat** whenever preflight raises one.
7. **Cap the findings.** 3–5 ranked, with a materiality floor — not thirty.
8. **`Not licensed financial advice.`** as the footer.

**1b. Workflow phases** (house style):

- *Phase 0 — Preflight.* `beans --version`, ledger path, `config list`,
  `period status`, `account list`, `recur list`, and today's date. Establish the
  **last complete period**.
- *Phase 1 — Gather.* One `series.py` call → income, expenses by account, net,
  and the ratio set across the horizon, plus `networth`. One Bash call, not N.
- *Phase 2 — Classify.* Drift / step change / one-off / seasonal / noise, with
  an explicit materiality floor (e.g. ignore moves below ~1% of monthly income).
- *Phase 3 — Infer.* The named patterns from the playbook (below).
- *Phase 4 — Report.* Ranked findings, each tied to a figure and a horizon,
  each with a proposed next action.

**1c. Preflight data-quality gate** — worth calling out because it is the
difference between analysis and astrology: share of spend sitting in
`Expenses:Other`, accounts not reconciled recently, months with suspiciously
few transactions, and whether the period is closed. If uncategorized spend
dominates, say the category trend is not usable and stop.

**1d. Tests.** Extend `tests/test_skill_scripts.py` — the precedent is set, and
the reason given there ("a misread sign silently corrupts a month of books")
applies with equal force to a misread trend.

### Phase 2 — promote the series into the product

Once the skill has proved which series matter, add them where they belong:

- `beans report trend --months N --json` — a first-class multi-period series
  (income, expenses by account, net, savings rate; monthly or quarterly), built
  on the same `led.flows()` scan `net_worth_trend` already uses.
- A `get_trend` tool in `_toolcore/tools.py`, so MCP **and** `beans ai` inherit
  it for free.
- Optionally extend `review_bundle_spec` with the trend series.

Then `series.py` becomes a thin fallback for older `beans` versions, and the
skill shrinks to what it should be: method, not plumbing. This ordering matters
— `_toolcore/bundle.py`'s own docstring exists to prevent exactly the drift that
a permanent skill-side reimplementation would create.

### Phase 3 — distribution

- `scripts/install_skill.sh` is hardcoded to `SKILL_NAME="beans-import"`.
  Generalize it to install either or both (`install_skill.sh beans-report`,
  `--all`).
- README: a section beside "Import statements with Claude", and a row in
  `docs/claude-skill-setup.md`'s comparison table — the skill *writes*, the
  server *reads*, and this one *reads across time*.
- A vignette (`docs/vignettes/10-reporting-skill.md`) following the established
  narrative form.

---

## Ways to make it more useful than "summarize trends"

Ranked by value per unit of effort. The first four are what turn a summary into
something worth reading monthly.

1. **Recurring-rule reconciliation → subscription creep.** `beans recur list`
   holds the standing instructions; the series holds what actually happened.
   Reconciling them finds what the ledger cannot report: a rule that says $45/mo
   but actuals at $117 and climbing (price rises, or subscriptions nobody
   cancelled), and — the more valuable direction — **rules that quietly stopped
   firing**. `beans-import` already cross-checks recurring rules; this is the
   read-only mirror of that idea.

2. **Budget *calibration*, not just variance.** `budget report` says you were
   over this month. The series says you were over in 9 of the last 12 — which
   means the budget is fiction, not the spending. Output: proposed
   `beans budget set` commands with numbers derived from the trend, for the user
   to run. Suggest-only, never write.

3. **Trajectory, not just trend.** Join the expense trend to `goal list` and the
   `networth` series to answer the question people actually have: *when does
   this land?* "At the current trajectory the down-payment goal arrives in
   March, not January; the grocery drift alone accounts for five weeks of that."
   That is inference; the rest is arithmetic.

4. **Flag the stale forecast basis.** Compare `forecast`'s per-account monthly
   basis against the trend. Where the basis is an average of a trending series,
   the forecast is systematically low (verified above: $720 basis vs. $786
   actual and rising). Recommend `--method trend`, or a narrower lookback, and
   say by how much the projection moves.

5. **Multi-horizon, level *and* rate.** Report 3 / 6 / 12-month views together.
   One horizon cannot distinguish a step change from an acceleration; three can,
   and the disagreement between them is itself the finding.

6. **A dated, diffable artifact.** Follow the `project-review` precedent: write
   a dated briefing to a path the user picks, in a fixed shape. Then the *next*
   run can read the previous one and close the loop — *"last month I flagged
   rising subscriptions; they rose another $9."* Memory across runs is the
   single biggest differentiator versus the one-shot `review` prompt, and it
   costs almost nothing to add.

7. **Scheduled monthly close.** Pair it with a recurring trigger fired a few
   days after month end (after `beans period close`), so it becomes a monthly
   process rather than something the user remembers to ask for.

8. **A "nothing to report" mode.** A briefing that manufactures four concerns
   every month trains the user to ignore it. If the numbers are boring, the
   correct output is one paragraph saying so. Make that an explicit, allowed —
   and tested — outcome.

9. **Charted output, opt-in.** A small HTML artifact for the series (spend by
   category over time, net-worth trajectory with the goal line) when the user
   wants to look rather than read. Optional; the text briefing is the product.

---

## Bottom line

Build it, scoped to trends and inference across periods, as
`.claude/skills/beans-report/` in the `beans-import` mould: a preflight, one
gather script, a classification step with a materiality floor, and a short
ranked briefing. Ship Phase 1 without touching product code; use what it learns
to justify `beans report trend` in Phase 2. Amend the `beans-import` description
in the same change, and generalize `install_skill.sh`.

The thing that makes it worth building is not that Claude cannot fetch these
reports — it can. It is that reading a financial series correctly has rules, and
without them the first honest-looking answer is that your income went to zero
last Tuesday.

*Not licensed financial advice.*
