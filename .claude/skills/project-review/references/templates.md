# Templates — report and backlog files

Follow these structures exactly. Keep both skimmable: a reader should grasp the
verdict in five seconds and find any individual item in one click. Omit empty
sections rather than padding (except the fixed top-level headings of the report,
which should always appear so the reader knows they weren't skipped).

---

## Artifact A — the findings report

Path: `docs/project_review_<YYYYMMDD>.md` (create `docs/` if needed; use today's
date). If that file already exists, append `-2`, `-3`, … and mention it.

````markdown
# Project Review — <project name> — <YYYY-MM-DD>

## Verdict & summary
<3–6 sentences: overall health, the few things that matter most, and an honest
read. Don't manufacture severity to seem rigorous — if the project is in good
shape, say so plainly and name the handful of things worth doing anyway.>

## How this review was scoped
<Calibrate the reader's trust. What did you read in full (e.g. "auth, persistence,
and the request pipeline — read fully and traced")? What did you sample (e.g. "CLI
and scripts — skimmed")? What did you skip and why (e.g. "generated code, vendored
deps, and the 12k-line migrations dir — skipped")? Note language(s)/framework(s)
detected, and whether git history was available for churn analysis.>

## Findings
<Ordered by priority tier (P0 → P3), then severity within tier. One compact block
per finding, using the format below. Each links to its backlog file.>

### [P0] <Finding title> — [001](../backlog/001-<slug>.md)
- **Lens:** <Robustness | Refactoring | Enhancement | Hidden bug>
- **Priority:** P0 · **Impact:** High · **Effort:** Low · **Severity:** Critical · **Confidence:** High
- **Evidence:** `path/to/file.py:88`, `path/to/caller.py:212`
- **Why it matters:** <concrete consequence, not vague>
- **Recommendation:** <the concrete fix or approach>

### [P1] <Finding title> — [002](../backlog/002-<slug>.md)
- **Lens:** Refactoring
- **Priority:** P1 · **Impact:** Medium · **Effort:** Low · **Severity:** — · **Confidence:** High
- **Evidence:** `path/to/a.ts:30`, `path/to/b.ts:55`, …
- **Why it matters:** …
- **Recommendation:** …

<…remaining findings…>

## New feature ideas
<Quarantined here, never interleaved above. Each idea cites the observed evidence
that motivates it. No backlog docs unless the user asked. ~5 max, P2/P3. If the
code offered nothing concrete, say so and keep this short.>

- **<Idea>** (P3) — *Evidence:* `path:line` / TODO / repeated workaround. <One
  line on what it would add and why the evidence points to it.>

## What's done well
<Genuine strengths, with evidence, the same way problems are evidenced. This tells
the team what to preserve and keeps the review balanced. Not filler — name real
things: a clean abstraction, solid test coverage on the core, a well-handled edge
case.>
````

### Notes on the report

- Use the exact `path:line` format so evidence is greppable and links cleanly.
- `Severity` is `—` for refactoring and enhancement findings; only bug/robustness
  findings carry Critical/High/Medium/Low. See `priority-rubric.md`.
- Backlog links depend on delivery mode (see SKILL.md step 6–7):
  - **File-mode (default):** relative link from `docs/` to `backlog/`, i.e.
    `[001](../backlog/001-slug.md)`.
  - **Issue-mode (GitHub, opt-in):** link to the created issue URL instead, e.g.
    `[#42](https://github.com/owner/name/issues/42)`. The report is still written;
    only the backlog *files* are skipped for findings that became issues.
- Only findings within the backlog cap get a backlog item and link; if you list
  additional lower-priority findings beyond the cap, present them without a link
  and note they weren't written up as work items.

---

## Artifact B — one backlog doc per actionable finding

Path: `backlog/<NNN>-<slug>.md` off the project root (create `backlog/` if needed).
Zero-padded sequence + short slug, e.g. `001-null-deref-in-parser.md`. **Before
writing, scan the existing `backlog/` folder and continue the numbering** so reruns
don't collide with or clobber prior work items.

Cap: top ~15 findings by priority unless the user said otherwise. No backlog docs
for new-feature ideas unless explicitly requested.

```markdown
# <Title>

- **Lens:** <Robustness | Refactoring | Enhancement | Hidden bug>
- **Priority:** <P0–P3>
- **Impact:** <Low | Medium | High>
- **Effort:** <Low | Medium | High>
- **Confidence:** <Low | Medium | High>
- **Severity:** <Critical | High | Medium | Low | — for non-defects>

## Problem
<What's wrong and exactly where (`path:line`), with enough evidence to act
without re-discovering it. For a bug, name the trigger condition and the call site
that reaches it. Quote the few relevant lines if it helps.>

## Why it matters
<The concrete consequence — who/what is affected and how. Not "this is bad
practice"; rather "on an empty upload the handler at upload.py:40 throws and the
request 500s instead of returning 400".>

## Proposed change
<The actual fix or approach. Sketch code only where it clarifies the intent;
don't write the whole patch.>

## Acceptance criteria
<How to know the work item is done — observable, checkable conditions. e.g.
"empty input returns 400 with a clear message; a regression test covers it;
existing tests still pass".>

## Risk / blast radius
<What this change touches and what could regress. Call out shared code, public
APIs, migrations, or anything that needs extra care in review/QA.>
```

---

## Artifact B in issue-mode (GitHub, opt-in)

When the user opts to file the backlog as GitHub issues (SKILL.md step 7), each
issue's **body is exactly the file template above** (the `# Title` line becomes the
issue title; the rest becomes the body). `scripts/create_issues.py` appends a hidden
marker for dedup — you don't add it yourself.

Build a `findings.json` for the script (schema is documented at the top of
`scripts/create_issues.py`): one object per finding with `seq`, `slug`, `title`,
`tier`, `lens`, `severity` (or `null`), and `body` (the full work-item markdown).

**Label mapping** the script applies, so you can describe it in the confirmation
prompt:

| Field | Label |
|-------|-------|
| every issue | `project-review` |
| tier | `P0` / `P1` / `P2` / `P3` |
| lens | `bug` / `refactoring` / `enhancement` / `robustness` |
| severity (defects only) | `severity:Critical` … `severity:Low` |

Always run the script with `--dry-run` first and show the user the resulting
created/skipped list before creating anything for real.
