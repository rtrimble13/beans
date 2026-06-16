# Priority rubric — impact × effort → tier, plus severity for defects

The central design decision of this skill: **do not rank everything on a single
severity scale.** Severity answers "how bad is it if this breaks?" — which only
makes sense for defects. Most of a project backlog is refactors and enhancements,
where the right question is "how much value, for how much work?" Forcing those onto
a severity scale produces a misleading ranking that buries cheap high-value wins
under scary-sounding edge cases.

So score on two axes, derive a tier, and tag defects with a severity as a second
signal.

## Step 1 — Score Impact and Effort

**Impact** — how much value does fixing/doing this deliver?

- **High** — affects correctness, security, data integrity, or many users/call
  sites; or removes a major source of ongoing friction or risk.
- **Medium** — meaningful improvement to a real but bounded area; noticeable but
  not critical.
- **Low** — minor or localized improvement; nice polish.

**Effort** — how much work to do it well, including tests and review?

- **Low** — a contained change, roughly hours; little blast radius.
- **Medium** — a focused piece of work, roughly a day or two; touches a few
  modules.
- **High** — a substantial change, multiple days or more; wide blast radius or
  needs design.

## Step 2 — Derive the Priority tier

| | | |
|---|---|---|
| **P0** | High impact **and** (it's a defect **or** low effort) | Do first. A high-impact bug/robustness defect, or a high-impact win that's cheap. |
| **P1** | High impact / medium effort, **or** medium impact / low effort | Strong ROI; schedule soon. |
| **P2** | Everything else worth doing. | The default home for solid-but-not-urgent work. |
| **P3** | Nice-to-have / speculative. | Includes most new-feature ideas. |

Reserve **P0** for things that genuinely warrant dropping current work: a real
Critical/High defect, or a high-impact fix so cheap there's no reason to wait.
Don't inflate — if everything is P0, the ranking is useless.

## Step 3 — Tag defects with Severity (second axis)

For the **bug** and **robustness** lenses only, also assign a severity, because for
defects the cost-of-not-fixing is the dominant factor and it should drive the tier:

- **Critical** — data loss/corruption, security hole, crash/hang, or broken core
  behavior on a realistic input or path. A Critical defect is P0.
- **High** — a real bug on a plausible edge case, or a significant robustness gap
  (e.g. an unhandled failure mode on a hot path). High defects are P0 or P1.
- **Medium** — a narrower edge case, or a robustness gap with limited blast radius.
- **Low** — a minor defect, unlikely conditions, small consequence.

Refactoring and enhancement findings do **not** get a severity — leave it as `—`.
Forcing a severity onto "this module is hard to test" is exactly the category error
this rubric exists to prevent.

## Step 4 — Order the report

Order findings by **priority tier first (P0 → P3), then by severity within tier**
(Critical → Low; un-severitied items sort after severitied ones of the same tier).
This puts the must-do defects at the very top, followed by the high-ROI work,
which is the order a team actually wants to pull from.

## Confidence (orthogonal to all of the above)

Every finding also carries a **Confidence** (High/Medium/Low) reflecting how sure
you are the finding is real and correctly diagnosed — separate from how important
it is. A high-impact, low-confidence finding is still worth reporting, but say what
would confirm it. Don't let confidence and severity blur together: a confirmed
small bug is high-confidence/low-severity; a suspected data-loss race is
low-confidence/critical-severity.

## Worked examples

- *Unparameterized SQL built from a request param, confirmed reachable from a
  public handler.* Impact High, Effort Low, defect, Severity Critical → **P0**.
- *Auth check missing on one admin endpoint; exploit needs an existing session.*
  Impact High, Effort Low, Severity High → **P0**.
- *Core service has no retry/timeout around its one external dependency; an outage
  there hangs every request.* Robustness, Impact High, Effort Medium, Severity
  High → **P1**.
- *The same date-parsing logic is copy-pasted in 6 files and has already drifted.*
  Refactor, Impact Medium, Effort Low, no severity → **P1**.
- *A 400-line request handler mixing transport, validation, and business logic;
  works but is hard to change and test.* Refactor, Impact Medium, Effort High → **P2**.
- *CLI prints a stack trace instead of a friendly message on bad input.*
  Enhancement, Impact Low, Effort Low → **P2**.
- *Off-by-one in a debug-only log line.* Bug, Impact Low, Effort Low, Severity Low
  → **P3**.
