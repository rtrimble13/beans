# Report template

Write the review to a Markdown file (default `PR_REVIEW.md`). Follow this
structure. Keep it skimmable: a reader should grasp the verdict in five seconds
and find any individual issue in one click. Order findings by severity within each
section. Omit empty sections rather than padding them.

```markdown
# Code Review — PR #<number>: <title>

**Verdict:** <Approve | Approve with comments | Request changes>
**Reviewed:** <N> files changed (+<added> / -<removed>) · CI: <passing|failing|n/a>

## Summary
<2–4 sentences: what the PR does, your overall assessment, and the headline
reason for the verdict. If you're requesting changes, name the blocking issues
here.>

## Findings

### 🔴 Blockers
- **[file/path.py:42] <one-line title>** — <what's wrong, why it matters, and a
  concrete fix or the exact condition that triggers it. Cite the call site or
  definition that confirms it.>

### 🟠 High
- **[file/path.ts:88] <title>** — <detail + suggested fix.>

### 🟡 Medium
- **[file/path.go:17] <title>** — <detail.>

### 🔵 Low
- **[file/path.js:9] <title>** — <detail.>

### ⚪ Nits
- Nit: **[file/path.css:3]** <detail.>

## What's done well
<1–4 genuine positives: good test coverage, a clean abstraction, a well-handled
edge case. This is signal, not flattery — it tells the author what to keep.>

## Recommendation
<Restate the verdict and the shortest path to merge: e.g. "Address the two
blockers (SQL injection on line 42, missing auth check on line 60) and this is
good to go." If approving, say so plainly.>
```

Notes:
- Use the exact `[path:line]` format so findings are greppable and link cleanly.
- If you reviewed without GitHub metadata (local-only fallback), say so under
  Summary and drop the CI line.
- If a finding is a suspicion rather than a confirmed bug, mark it: "(unconfirmed —
  depends on whether `x` can be null)". Honesty about confidence is part of the
  quality bar.
