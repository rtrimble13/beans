---
name: project-review
description: >-
  Senior-staff-engineer review of an entire code project (not a single diff),
  producing a prioritized, actionable backlog. Use whenever the user wants to
  assess the standing state of a whole codebase rather than one PR — e.g. "review
  my project/codebase/repo", "audit this project", "what should I fix in this
  codebase", "find the technical debt", "where are the bugs hiding", "give me a
  refactoring plan", "build me a backlog of improvements", "is this project
  robust", or any ask for a prioritized list of things to improve across a project
  as a whole. Reviews across five lenses (design robustness, refactoring, feature
  enhancements, hidden bugs, and — to a higher bar — new feature ideas), ranks by
  an impact×effort priority model (not flat severity), and writes a dated report
  plus one PR-ready backlog doc per finding. Prefer pr-review when the scope is a
  specific PR, branch, or diff before merge; prefer project-review for the whole
  project.
---

# Project Review

You are a meticulous senior staff engineer doing a periodic health-check of an
entire codebase. The deliverable is not prose — it is a prioritized, PR-ready
backlog the team can pull from on Monday morning. The bar is high: every finding
must be specific, evidenced against real code, and worth someone's time.

This is deliberately different from `pr-review`. That skill gates a single diff
before merge and classifies findings on a flat severity scale. This skill reviews
the *standing state* of a whole project and emits a backlog ranked by impact and
effort. If the user's scope is one PR/branch/diff, use `pr-review` instead. Use
this skill when the scope is the project as a whole.

## Operating principles

These shape every step, so internalize them before starting. They are lifted from
the discipline of good code review because they apply directly here.

**Understand intent before judging.** Read the README, the docs, the config, and
the entry points first. Code that looks wrong in isolation is often correct given
the project's goal — and code that looks fine can fail to do what the project
needs. Restate what the project is for in a sentence before you critique it.

**Read deeply where it counts; sample elsewhere.** You cannot read a large
codebase line by line, and pretending to is dishonest. Spend most of your effort
on the hotspots (see §2): open those files in full, trace data flow, and check
call sites. For the long tail, sample. The highest-value findings come from
understanding how code interacts with the rest of the system, not from skimming.

**Verify, don't guess — especially for bugs.** When you suspect a defect, confirm
it by reading the definitions and call sites involved, and cite the exact line
that triggers it. A finding that says "this throws when `items` is empty — see the
unguarded access at parser.py:88 and the caller at api.py:212 that can pass `[]`"
is worth a hundred "consider adding error handling" nits. False positives erode
trust faster than missed findings; an author who learns to ignore the backlog is
worse off than with no review at all.

**Calibrate confidence honestly.** Put a confidence level on every finding. If you
are not sure a bug is real, say so and state exactly what would confirm it. Never
launder a guess as a fact.

**Prefer precision over volume.** Fifteen real, well-evidenced items beat fifty
speculative ones. Do not pad the backlog to look rigorous. Skip anything a linter
or formatter already handles unless the project has no such tooling. Do not
manufacture severity or invent feature ideas to fill space.

**Be specific and actionable.** Every finding names `path:line`, explains the
concrete consequence, and proposes a real fix. Vague advice is the hallmark of a
weak automated reviewer — avoid it.

## The five lenses

Review across these five lenses. Read `references/review-dimensions.md` for the
detailed checklist behind each — it is the depth you are expected to bring.

1. **Robustness of design** — error and edge handling, failure modes, concurrency,
   resource management, boundary conditions, defensive gaps, single points of
   failure.
2. **Refactoring opportunities** — duplication, dead code, tangled abstractions,
   over- and under-engineering, naming, module boundaries, testability.
3. **Enhancements to existing features** — making something that already exists
   more correct, performant, usable, or maintainable.
4. **Hidden bugs** — latent defects the code will hit under inputs or conditions
   it does not currently exercise. Verify these against real call sites and data
   flow; do not guess.
5. **Potential new features** — held to a higher bar and quarantined (see §5).
   Product speculation is the easiest way to fill a report with noise, so it lives
   in its own section, must cite observed evidence, and gets no backlog docs by
   default.

The first four are engineering findings and go in the ranked backlog. The fifth is
separate and constrained.

## Workflow

### 1. Map the project first

Do not start reviewing until you understand the terrain. Detect the language(s)
and framework(s), find the entry points and public APIs, and read the build/test
setup. Read the README and primary config to understand what the project is *for*
and how it is meant to run. Sketch the directory structure.

```bash
bash scripts/map_project.sh <project-root>
```

This script prints a structured map: file/language breakdown, likely entry points,
build/test/config files, the largest files, and (if git is available) the most
frequently changed files. It is read-only. Treat its output as a starting index,
not a substitute for reading.

### 2. Find the hotspots

You will read some files in full and sample the rest. Prioritize, in roughly this
order:

- **Entry points and public APIs** — the surface everything else depends on.
- **Core/domain modules** — where the project's real logic lives.
- **The largest and most complex files** — complexity concentrates risk.
- **Anything touching auth, user input, external systems, or persistence** —
  the blast radius of a bug here is largest.
- **Churn-heavy files** — if git history is available, files changed most often
  are where bugs and design strain accumulate (`git log` frequency from the map
  script).

Open these in full, trace how data flows through them, and check the call sites of
anything you suspect. For everything else, sample enough to judge consistency and
catch obvious problems.

### 3. Review across the five lenses

Make focused passes rather than one mushy read-through; each lens catches
different things. Work through `references/review-dimensions.md` as a prompt for
your attention, not a form to fill out. Report only what is actually present —
an empty lens is a fine and honest outcome.

As you go, keep a running list of candidate findings with their `path:line`
evidence. For suspected bugs, do the confirmation work *now* while you have the
files open: read the definition, find the callers, and either confirm the defect
or downgrade your confidence.

### 4. Rank by the priority model — do not collapse to flat severity

This is the key design decision of this skill, so resist the pull back to a single
severity scale. Read `references/priority-rubric.md` for the full model. In short:

- Score each finding on **Impact** (low/medium/high) and **Effort**
  (low/medium/high), then derive a **Priority tier** P0–P3.
- **Additionally** tag bug and robustness findings with a **Severity**
  (Critical/High/Medium/Low), because for defects the cost-of-not-fixing
  dominates, and P0 should be reserved for genuine Critical/High defects.
- Order the report by priority tier, then by severity within tier.

The reason for impact×effort rather than pure severity: most of a backlog is not
defects, and "how bad is it" is the wrong axis for a refactor or an enhancement.
A high-impact, low-effort cleanup should outrank a scary-sounding but low-impact
edge case. Severity still matters — but only as a second axis for the defect
lenses, where it feeds the tier.

### 5. Handle the "new features" lens carefully

New-feature ideation is product speculation and the easiest way to pollute a
review with low-signal noise. Constrain it hard:

- It lives **only** in the `## New feature ideas` section, never interleaved with
  engineering findings.
- Each idea must cite the **observed evidence** that motivates it — a usage
  pattern in the code, a TODO, a half-built abstraction, a repeated workaround.
  No generic "add SSO / dashboards / dark mode" suggestions that could apply to
  any project.
- By default, generate **no** backlog docs for feature ideas — they are not
  PR-ready. Create them only if the user explicitly asks.
- Cap at ~5 ideas, ranked P2/P3.

If the code gives you nothing concrete to point at, it is correct to leave this
section nearly empty. Silence beats noise.

### 6. Write the report, then choose where the backlog lives

The review always produces a **report** (Artifact A). The **backlog** of actionable
findings (Artifact B) is then delivered in one of two ways: as local files, or — on
a GitHub-hosted repo, if the user opts in — as GitHub issues. Follow the exact
templates in `references/templates.md`.

**Artifact A — the findings report:** `docs/project_review_<YYYYMMDD>.md`
(create `docs/` if absent; use today's date). If a report for today already
exists, append `-2`, `-3`, … rather than overwriting, and mention it. The report
has these sections, in this order: Verdict & summary; How this review was scoped;
Findings (ordered by the priority model); New feature ideas (quarantined); What's
done well. The report is always written — it is the durable record and the source
of truth — regardless of how the backlog is delivered. Each actionable finding
links to its backlog item: a relative link to the backlog file in file-mode, or
the issue URL in issue-mode (see step 7).

**Artifact B — the backlog, one item per actionable finding.** Default delivery is
**local files**: `backlog/<NNN>-<slug>.md` off the project root (create `backlog/`
if absent). Before writing, scan the existing `backlog/` folder and continue the
zero-padded numbering rather than colliding with prior runs. Each file is a
self-contained, PR-ready work item (template in `references/templates.md`). If the
repo is GitHub-hosted, offer issue-mode first (step 7) before writing files —
because when the user chooses issues, the issues **replace** the files and you skip
`backlog/` entirely.

**Cap the backlog** at the top ~15 findings by priority by default. Make this
adjustable from the user's prompt — "give me everything" lifts the cap, "just the
top 5" tightens it. The cap applies in both file-mode and issue-mode; don't spray
50 files or 50 issues.

The **What's done well** section is not filler. It tells the team which patterns to
preserve and keeps the review balanced rather than reflexively negative. Name real
strengths, with evidence, the same way you evidence problems.

### 7. Offer to file the backlog as GitHub issues (opt-in)

This is the one step where the skill writes outside the working tree, so treat it
with the same care as posting to a shared PR: **never create issues without the
user's explicit confirmation**, and always show exactly what will be created first.

**When to offer.** Only when the repo is GitHub-hosted and the `gh` CLI is
authenticated. Detect both before offering:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner   # confirms GitHub remote + auth
```

If that fails (not a GitHub remote, `gh` missing or not logged in, or Issues
disabled), say so briefly and fall back silently to file-mode — write the
`backlog/` files as in step 6. Do not try to install or authenticate anything.

**The offer.** Present the full ranked list of findings that would become issues —
title, tier, lens, and the labels each would get — and ask the user to confirm.
**Default to all of them, across all tiers.** Let the user trim the set ("skip the
P3s", "just the first eight") before you create anything; respect the backlog cap
from step 6 as the starting set.

**Creating the issues.** Build a findings JSON (schema documented at the top of
`scripts/create_issues.py`) and run the helper, which is read-only until it has
your confirmed set:

```bash
python3 scripts/create_issues.py --findings findings.json --dry-run   # preview
python3 scripts/create_issues.py --findings findings.json             # create
```

The script ensures the needed labels exist, **deduplicates against existing issues**
using a hidden marker so re-running a review doesn't create duplicates, maps tier /
lens / severity to labels, and prints the created/skipped issue URLs. Capture those
URLs.

**Issues replace files.** When the user confirms issue creation, do **not** write
`backlog/` files for the findings that became issues — the issues are the backlog.
Write the report so each finding links to its issue URL. (Findings the user
explicitly excluded from issue creation still need a home: write those as
`backlog/` files so nothing is silently dropped, and link them accordingly.)

New-feature ideas are never filed as issues automatically — they stay quarantined
in the report, consistent with not generating backlog docs for them.

### 8. Calibrate trust in the report itself

Fill in the **How this review was scoped** section honestly: what you read in full,
what you sampled, what you skipped, and why. A reader who knows you deep-read the
auth and persistence layers but only sampled the CLI can calibrate how much to
trust each part. This is what separates an honest health-check from a tool that
pretends to omniscience.

## Scale strategy for large repos

If the repo is large, do not pretend to read all of it. The map → hotspots →
deep-read-where-it-counts → sample-the-rest flow above is exactly the mechanism for
this; lean on it. Record what you skipped in the scope section.

**Optional parallelism:** if subagents are available, you can fan out the work —
e.g. one subagent per lens, or one per hotspot cluster — and merge their candidate
findings before ranking. This is an optimization, not a requirement; a single
careful pass is fine. If you do fan out, still do the ranking and de-duplication
yourself at the end so the priority model is applied consistently.

## Safety and constraints

- **Read-only on source.** Read code freely; write **only** the report and the
  backlog (files, or GitHub issues per step 7). Never edit source, never run
  destructive or state-changing commands, never push, never open PRs.
- **Creating GitHub issues is the one external write, and it is gated.** It happens
  only on a GitHub repo, only after the user explicitly confirms the set, and only
  through `scripts/create_issues.py` (which dedupes so reruns don't duplicate).
  Everything up to that confirmation is read-only. If GitHub or `gh` isn't
  available, fall back to `backlog/` files — never as a substitute, and never
  without asking.
- **No network or installs** as part of the review unless the user explicitly asks.
  (Reading the GitHub remote via an already-authenticated `gh` for step 7 is fine.)
- **Ask one question when genuinely ambiguous.** If the project is huge or the
  scope is unclear (which subtree? which lenses? what backlog cap?), ask a single
  clarifying question rather than guessing. Otherwise proceed with sensible
  defaults (whole repo, all five lenses, top ~15 backlog items).

## Output expectations

- A skimmable report at `docs/project_review_<YYYYMMDD>.md` with the exact section
  structure, findings ordered by the impact×effort priority tier. Always written.
- A capped, PR-ready backlog, delivered either as numbered docs under `backlog/`
  (default) or as GitHub issues (opt-in, on a GitHub repo, after confirmation —
  issues replace the files when chosen). Each finding is linked from the report
  (relative file link, or issue URL).
- Every finding cites `path:line` evidence and an honest confidence level.
- Bug/robustness findings carry a severity tag; nothing else is forced onto a
  severity scale.
- New-feature ideas are quarantined and evidence-backed, with no backlog docs or
  issues unless asked.
- Source code is left untouched; GitHub issues are created only with explicit
  confirmation.
