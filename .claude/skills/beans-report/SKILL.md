---
name: beans-report
description: >-
  Read trends and draw inferences across time from a beans double-entry ledger —
  "are my expenses creeping up", "what changed over the last six months", "how
  has my savings rate moved this year", "is my grocery spend drifting", "why is
  my runway shrinking", "am I on track for my goal", "run my monthly financial
  review". Gathers many periods of `beans report income`, `analyze`, `networth`
  and `budget report` into one series, separates real drift from one-off spikes
  and noise, reconciles actuals against the ledger's `beans recur` rules and
  budgets, and writes a short ranked briefing in which every figure came from a
  command you can re-run. Strictly read-only — it never writes to the ledger.
  Not for importing or categorizing statements (that is the beans-import skill),
  and not for a single period's numbers: one statement, one balance, one month's
  budget variance are questions `beans report`, the beans MCP server or
  `beans ai review` already answer directly.
---

# beans — trends & inference

You are reading someone's **financial history** and telling them what it means.
The numbers are not in doubt — `beans` computes them, and every one is already
correct. What is in doubt is the story, and a confident wrong story about
someone's money is worse than no story at all.

Your value here is *discipline*, not retrieval. Claude can already fetch any
`beans` report. What it cannot do without this skill is know that a four-day-old
month is not a collapse in income, that one vet bill is not a trend, and that a
category series over a ledger with a fat `Expenses:Other` bucket is a chart of
filing habits rather than of spending.

## What this skill is not for

- **A single period.** "What did I spend in August", "show me my balance sheet",
  "am I over budget this month" — answer those with a direct `beans` command,
  the MCP server, or `beans ai ask`. Reaching for a twelve-month series to
  answer a one-month question wastes everyone's time.
- **The raw series itself.** `beans report trend` prints it, and
  `beans_trend` returns it over MCP. If the user only wants the numbers side
  by side, run that one command and show it. This skill is the *reading* of a
  series — data quality, classification, inference, a ranked briefing — not
  the fetching of one.
- **A period-over-period briefing.** `beans ai review` and the MCP `review`
  prompt already do current-vs-prior. This skill starts at the *second* period
  back. If the question is "how did last month go", say so and hand it over.
- **Writing anything.** Import, categorize, budget changes, closing a period —
  all of that belongs to `beans-import` or to the user at their own prompt.

## Guardrails

Non-negotiable. If following a guardrail conflicts with what you were asked,
say so and stop — do not quietly pick the more impressive path.

1. **Never include a period that has not fully elapsed.** `beans report trend`
   and `series.py` both exclude it by default; do not override that with
   `--include-partial` to "get the latest data". On the 4th of the month, the current month reports four days of
   spending and often no salary at all: run it into a trend and you will report
   that someone's income collapsed and their runway fell by three quarters.
   Both are false. If a partial period is shown for any reason, label it
   *partial* every single time it appears.
2. **Never do money arithmetic in prose.** Every figure you state comes from a
   `beans --json` report or from `trend.py`, both of which are tested. Do not
   subtract two numbers in your head and present the result as a finding.
3. **Read-only, always.** Never run `import`, `tx add`, `tx void`, `spend`,
   `earn`, `budget set`, `rule add`, `recur run`, `period close`, or `undo`.
   `beans_io.assert_read_only` enforces this for the scripts; you are held to it
   too. Recommendations are emitted as commands *for the user to run*.
4. **Six periods to assert a trend; three to say anything at all.** Below six,
   every finding is explicitly "directional, on N periods". Below three, refuse
   and say what you would need.
5. **A one-off is not a trend.** Classify before you narrate. `trend.py`
   distinguishes `drift`, `step`, `one-off`, `new`, `stopped` and `stable` —
   use its word, not a more dramatic one.
6. **Never read a failed command as a zero.** A gap in the series is a gap.
   `series.py` records `null` and an error; report the gap, do not average over
   it.
7. **State the data-quality caveat whenever preflight raises one.** If
   `preflight.py` blocks, the category findings are not usable — say so plainly
   and offer the totals, which usually still are.
8. **Three to five findings, ranked, above the materiality floor.** A briefing
   that manufactures a concern for every account trains the reader to ignore it.
   `trend.py` already filters; do not reinstate what it dropped.
9. **"Nothing much changed" is a valid, and sometimes the correct, answer.**
   If the numbers are boring, say so in a paragraph and stop. Do not go looking
   for something alarming to justify the run.
10. **Aggregates by default.** Work from statements and series. Only reach for
    `register` or `search` — which return payee and description text — when the
    user asks you to drill into a specific finding.
11. **Every claim ties to a figure and a window.** "Groceries are up" is not a
    finding. "Groceries drifted +$242/month over the 12 months to August 2026,
    now $786" is.
12. **End with:** `Not licensed financial advice.`

## Phase 0 — Preflight

Establish what is true before reading anything into it. Never guess the ledger.

```sh
cd .claude/skills/beans-report/scripts
./preflight.py --months 12                 # add -f PATH for a non-default ledger
```

It reports, and you must read: the resolved ledger path, currency and decimals,
**today's date and the last complete period**, how far the ledger's history
actually reaches, how much spending is sitting uncategorized, which periods look
suspiciously sparse, whether the books are closed through a date, and whether
recurring rules, budgets and goals exist to reconcile against.

Exit status 1 means a **blocker**. The two that matter:

- *Uncategorized spending above the limit* — per-category trends are not
  meaningful. Say so, offer totals-only findings, and suggest `beans categorize`
  (or the `beans-import` skill) as the fix.
- *Too little history* — fewer than three covered periods. Say what you would
  need and stop.

Warnings are not blockers, but every one of them belongs in the briefing's
caveats. A window that reaches back before the first transaction is padded with
structural zeros; narrow it rather than trending them.

## Phase 1 — Gather

One call. Not twelve.

```sh
./series.py --months 12 -o /tmp/series.json                 # totals + accounts
./series.py --months 12 --ratios --budgets -o /tmp/series.json
./series.py --grain quarter --periods 8 -o /tmp/series.json
```

`series.py` calls `beans report trend --json` and copies its figures verbatim —
it does no arithmetic, so every number it emits can be traced to a command you
can re-run. On a beans older than 1.1 it falls back to one `report income` per
period and assembles the same shape; the `source` field says which ran, and
nothing downstream changes. Add `--ratios` for `beans analyze` per period
(savings rate, liquidity runway, leverage) and `--budgets` for per-period
budget variance. Check `errors` and `empty_periods` before going further.

## Phase 2 — Classify

```sh
./trend.py /tmp/series.json -o /tmp/trend.json
./trend.py /tmp/series.json --scope expenses --floor-pct 2
```

`trend.py` fits each series robustly — a median-of-pairwise-slopes line and
median-absolute-deviation noise bands, so a single spike moves neither — and
returns one classification per account:

| Verdict | What it means | What it usually is |
|---|---|---|
| `drift` | a sustained slope, clear of the noise | prices creeping, lifestyle creep |
| `step` | one level change, flat either side | a raise, a rent increase, a new plan |
| `one-off` | a single period far off the median | a bill, a repair, a holiday |
| `new` | absent, then present and recurring | a subscription that started |
| `stopped` | recurring, then absent | **a payment that quietly lapsed** |
| `stable` | nothing distinguishable from noise | say nothing about it |

Two thresholds gate every finding, and they are different questions. **Scale**
asks whether a move is distinguishable from the series' own noise. **Materiality**
asks whether it is big enough for a person to care — by default 1% of typical
period income. Both must be cleared. `immaterial_count` tells you how many real
but small moves were dropped; mention the count, not the list.

Read `references/method.md` before overriding any of this.

## Phase 3 — Infer

Classification is arithmetic. This is the part that is worth reading. Work
through `references/inference-playbook.md`; the patterns that pay for the run:

- **Subscription creep and lapsed payments.** Cross the `new` / `stopped` /
  `drift` findings against `beans recur list`. A rule that says $45 against
  actuals of $117 and climbing is a price rise or a subscription nobody
  cancelled. A rule that stopped firing is money you may still owe — or a
  service you are no longer getting. `beans` cannot notice either.
- **Budget calibration, not variance.** `budget report` says you were over this
  month. The series says you were over in nine of twelve — which means the
  budget is fiction, not the spending. Propose `beans budget set` lines with
  numbers from the trend; never run them.
- **Trajectory.** Join the expense trend to `beans goal list` and the
  `net_worth` series: *when* does the goal land at this trajectory, and which
  finding moved the date? That is the inference people actually want.
- **A stale forecast basis.** `beans forecast` prices each account at its
  historical *average*. Where the same account shows `drift`, the average is
  behind the latest level and the projection understates. Say by how much, and
  suggest `--method trend`.
- **Level and rate, over three horizons.** Run 3, 6 and 12 periods. One horizon
  cannot tell a step from an acceleration; three can, and where they disagree,
  the disagreement is itself the finding.

## Phase 4 — Brief

Short. Ranked. Every line tied to a figure.

```
TREND BRIEFING — 12 months to August 2026        (September excluded: in progress)

Headline: <one sentence: what is actually happening>

1. <finding> — <figure, window, classification> → <what it implies> → <proposed action>
2. …
3. …

Caveats: <preflight warnings, gaps, short history, immaterial count>
Not licensed financial advice.
```

Rules for the prose:

- Name the classification. "Groceries are drifting up" and "groceries stepped up
  in March" are different claims and only one is true.
- Give the window with every figure. A number without a window is not a finding.
- Separate **actuals** (the ledger) from **assumptions** (forecast and economic
  inputs — discount rate, horizon, growth). Say which is which whenever you lean
  on one.
- Propose commands, do not run them.
- If the user asked about one thing, lead with that thing even if something else
  ranked higher — then mention the higher one.

### Writing it down

If the user wants a record, write the briefing to a dated file they name
(`trend-briefing-YYYY-MM.md` is a reasonable default) in the fixed shape above.
The payoff is on the *next* run: read the previous briefing first and close the
loop — *"last month I flagged rising subscriptions; they rose another $9"*.
That memory across runs is the thing a one-shot review cannot do. Never write
into the beans repository or anywhere near the ledger without being asked.

## After the briefing

Offer, do not perform:

- Drill into any finding — `beans register <account> --period <P>` for the
  transactions behind it.
- Re-run at a different horizon or grain.
- The commands the findings imply (`beans budget set …`, `beans recur …`),
  written out for the user to run.
- If a finding depends on categorization the ledger does not have, hand off to
  the `beans-import` skill.

## References

- `references/method.md` — how a series is read without lying to yourself: the
  partial-period trap, robust statistics, scale vs materiality, and the traps
  that survive them.
- `references/inference-playbook.md` — named patterns, what each implies, and
  the command to propose.
- `references/command-reference.md` — the read-only report surface, the period
  grammar, which commands have `--json` and which do not.
- `scripts/preflight.py`, `scripts/series.py`, `scripts/trend.py` — all three
  take `--help`; the arithmetic is covered by `tests/test_skill_scripts.py`.
