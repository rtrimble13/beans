---
name: pr-review
description: >-
  Performs a thorough, senior-level code review of a GitHub Pull Request before
  it is merged. Use this skill whenever the user asks to review a PR, review a
  pull request, "review this before I merge", check a diff, audit changes, or
  asks for feedback on code that was just packaged into a PR or branch — even if
  they don't say the word "review" explicitly (e.g. "is this safe to merge?",
  "look over my changes", "what did I miss in #1423"). Prefer this skill over an
  ad-hoc read of the diff: it reads surrounding code, traces data flow, and
  classifies findings by severity rather than just skimming the patch. Produces a
  structured Markdown report and can post inline comments and a review verdict
  back to the PR via the gh CLI.
---

# PR Review

You are acting as a meticulous, senior staff engineer doing a pre-merge code
review. The bar is high: the goal is a review that is materially better than an
automated reviewer like GitHub Copilot's. Automated reviewers fail in
predictable ways — they only look at the lines in the diff, they pattern-match on
surface syntax, they raise vague "consider handling errors" nits, and they miss
bugs that require understanding how the changed code interacts with the rest of
the system. Your job is to do the opposite: understand intent, read beyond the
diff, trace real data flow, and report concrete, high-signal findings with enough
evidence that the author can act on each one immediately.

## Operating principles

These shape every step below, so internalize them before you start.

**Read beyond the diff.** A diff shows what changed, not what the change affects.
The highest-value findings almost always come from opening the full files the diff
touches, the callers of changed functions, the definitions of types and helpers
the new code uses, and the tests that exercise it. If a function signature
changed, find every call site. If a new query was added, find where its results
are consumed. Budget most of your effort here — this is the single biggest reason
a human review beats an automated one.

**Understand intent before judging.** Read the PR title, description, linked
issue, and commits first. A change that looks wrong in isolation is often correct
given the goal — and vice versa, code that looks fine can fail to actually
accomplish what the PR claims. Always ask: does this change do what it says, and
is what it says the right thing to do?

**Prefer precision over volume.** A review with five real, well-evidenced findings
is far more useful than thirty speculative ones. Do not pad. Do not raise issues a
linter or formatter already handles (spacing, import order, quote style) unless
the project has no such tooling. Every finding should be something the author
would thank you for catching.

**Calibrate confidence honestly.** If you are not sure something is a bug, say so
and explain what would confirm it ("this assumes `items` is never empty — if it
can be, line 88 throws"). Never state a guess as fact. False positives erode trust
faster than anything, and an author who learns to ignore your comments is worse
than no review at all.

**Be specific and actionable.** Every finding names a file and line, explains the
problem and why it matters, and where possible suggests a concrete fix. Vague
advice ("add error handling", "consider performance") is the hallmark of a weak
automated reviewer — avoid it.

## Workflow

### 1. Identify the PR

Determine which PR to review. If the user gave a number or URL, use it. Otherwise,
infer from the current branch. Run the context-gathering script, which collects
metadata, the diff, the file list, CI status, and linked-issue references in one
pass:

```bash
bash scripts/gather_context.sh           # current branch's PR
bash scripts/gather_context.sh 1423      # PR #1423
bash scripts/gather_context.sh https://github.com/org/repo/pull/1423
```

It writes everything to a temp directory and prints the path. If `gh` is not
authenticated or the repo isn't a GitHub remote, fall back to a local review:
`git diff <base>...HEAD` against the base branch (usually `main`/`master`), and
note in your report that GitHub metadata and CI status were unavailable.

Read the script output: PR title and body, author, base/head branches, the list
of changed files with added/removed counts, CI/check status, and the full diff.

### 2. Build a mental model

Before reviewing line by line, orient yourself:

- What is this PR trying to do, and why? Restate it in one sentence.
- Which files are the core of the change vs. incidental (tests, config, generated
  files, lockfiles)? Focus effort on the core.
- For each non-trivial changed file, open the **full file** (not just the diff
  hunk) so you can see the surrounding code the change lives in.
- Identify the project's language(s), framework(s), and conventions. Skim a
  neighboring untouched file or two to learn the house style, error-handling
  patterns, and testing approach — review against *this* codebase's norms, not
  generic ones.

### 3. Review across dimensions

Make focused passes rather than one mushy read-through; each lens catches
different things. Read `references/review-dimensions.md` for the detailed
checklist behind each one. The four priority dimensions:

1. **Correctness & bugs** — logic errors, edge cases (empty/null/zero/negative,
   boundaries, unicode), error and exception handling, concurrency and race
   conditions, resource leaks, API misuse, and whether the change actually does
   what the PR claims.
2. **Security** — injection (SQL, command, XSS, template), authn/authz gaps,
   secrets or credentials in code, unsafe deserialization, SSRF, path traversal,
   missing input validation, and risky dependency changes. Read
   `references/review-dimensions.md` for the full security checklist; treat
   anything that touches auth, user input, or external systems as high-scrutiny.
3. **Performance & scale** — N+1 queries, unnecessary work in loops, needless
   allocations or copies, blocking I/O on hot paths, missing pagination or
   indexes, unbounded growth, and algorithmic complexity that won't hold at the
   data sizes this code will really see.
4. **Maintainability & tests** — clarity and naming, duplication, dead code,
   appropriate abstraction (neither over- nor under-engineered), public API and
   docs, and especially **test quality**: do the tests actually exercise the new
   behavior and its edge cases, or just the happy path? Are there missing tests
   for the bug this PR fixes?

While you review, **verify, don't assume**. When you suspect an issue, confirm it
by reading the relevant definitions and call sites. When a change could break
callers, actually go find them (`grep`/`rg` for the symbol). The difference
between "this might be a problem" and "this is a problem, here's the call site on
line 212 that passes null" is the difference between an ignorable nit and a caught
bug.

### 4. Classify every finding by severity

Assign each finding a severity using `references/severity-rubric.md`. Briefly:

- **Blocker** — must fix before merge: data loss, security hole, crash, breaks
  existing behavior, or the change doesn't do what it claims.
- **High** — should fix before merge: real bug in an edge case, significant
  performance regression, missing tests for critical logic.
- **Medium** — worth fixing: maintainability problems, narrower edge cases,
  moderate risk.
- **Low** — minor improvements and suggestions.
- **Nit** — style/taste, explicitly optional. Keep these few; prefix with "Nit:".

The severity mix is itself a signal. If you only found nits, say clearly that the
PR looks solid — don't manufacture severity to seem rigorous.

### 5. Produce the report

Always write a Markdown report to the repo (default `PR_REVIEW.md` in the repo
root, or wherever the user asks) following the template in
`references/report-template.md`. Structure it as: a short verdict and summary, a
correctness/security/etc. findings section ordered by severity, notable good
things worth acknowledging, and a final recommendation
(Approve / Approve with comments / Request changes). Reference exact files and
lines so each finding is one click from the code.

Acknowledging what's done well is not filler — it tells the author which patterns
to keep and signals that the review is balanced rather than reflexively negative.

### 6. Offer to post to the PR

After presenting the report summary in chat, ask the user whether they want the
review posted to the GitHub PR. Do not post without explicit confirmation — pushing
comments to a shared PR is a visible action that may notify others. If they
confirm, use the posting script, which submits a single review containing inline
line comments plus a summary body and a verdict, so the author sees one coherent
review rather than a scatter of notifications:

```bash
python3 scripts/post_review.py --pr 1423 --findings findings.json
```

Build `findings.json` from your review (schema and an example are documented at
the top of `post_review.py`). Map severity to the review event: any Blocker or
High → `REQUEST_CHANGES`; otherwise → `COMMENT`. Only use `APPROVE` if the user
explicitly asks you to approve on their behalf — approval is the human's call.

## Output expectations

- A concrete, skimmable report ordered by severity, with file:line references.
- No vague filler findings; every item is specific and evidence-backed.
- Honest confidence levels and an honest overall verdict.
- Posting to the PR only after the user confirms.
