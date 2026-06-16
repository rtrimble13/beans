#!/usr/bin/env bash
# Gather everything needed to review a GitHub PR into one temp directory.
#
# Usage:
#   bash gather_context.sh            # PR associated with the current branch
#   bash gather_context.sh 1423       # PR number
#   bash gather_context.sh https://github.com/org/repo/pull/1423
#
# Output: prints a directory path containing:
#   meta.json   - PR metadata (title, body, author, branches, files, checks...)
#   diff.patch  - full unified diff of the PR
#   files.txt   - changed files with +/- line counts
#   checks.txt  - CI / status check results
#   summary.txt - human-readable header for quick orientation
#
# Falls back gracefully: if gh is missing/unauthenticated, prints guidance and
# exits non-zero so the caller can switch to a local `git diff` review.

set -uo pipefail

ARG="${1:-}"

err() { echo "ERROR: $*" >&2; }

if ! command -v gh >/dev/null 2>&1; then
  err "GitHub CLI 'gh' not found. Install it (https://cli.github.com) or do a"
  err "local review instead: git diff <base-branch>...HEAD"
  exit 2
fi

if ! gh auth status >/dev/null 2>&1; then
  err "gh is not authenticated. Run 'gh auth login', or do a local review:"
  err "  git diff <base-branch>...HEAD"
  exit 2
fi

# Resolve a PR selector gh understands (number, URL, or empty = current branch).
PR_SELECTOR="$ARG"

OUTDIR="$(mktemp -d "${TMPDIR:-/tmp}/pr-review.XXXXXX")"

FIELDS="number,title,body,author,headRefName,baseRefName,state,isDraft,url,additions,deletions,changedFiles,mergeable,labels,files,statusCheckRollup,commits"

if ! gh pr view $PR_SELECTOR --json "$FIELDS" >"$OUTDIR/meta.json" 2>"$OUTDIR/err.txt"; then
  err "Could not load PR. gh said:"
  cat "$OUTDIR/err.txt" >&2
  err "If no PR is associated with this branch, pass a PR number or URL."
  exit 3
fi

# Full diff.
gh pr diff $PR_SELECTOR >"$OUTDIR/diff.patch" 2>/dev/null || \
  err "Warning: could not fetch diff via gh pr diff."

# Derive convenience views from meta.json using python (always available here).
python3 - "$OUTDIR/meta.json" "$OUTDIR" <<'PY'
import json, sys
meta = json.load(open(sys.argv[1]))
out = sys.argv[2]

with open(f"{out}/files.txt", "w") as f:
    for fl in meta.get("files", []):
        f.write(f"+{fl.get('additions',0):<6} -{fl.get('deletions',0):<6} {fl.get('path','')}\n")

with open(f"{out}/checks.txt", "w") as f:
    rollup = meta.get("statusCheckRollup") or []
    if not rollup:
        f.write("No status checks reported.\n")
    for c in rollup:
        name = c.get("name") or c.get("context") or "check"
        state = c.get("conclusion") or c.get("state") or c.get("status") or "?"
        f.write(f"{state:<12} {name}\n")

labels = ", ".join(l.get("name","") for l in meta.get("labels", [])) or "none"
with open(f"{out}/summary.txt", "w") as f:
    f.write(f"PR #{meta.get('number')}: {meta.get('title')}\n")
    f.write(f"Author: {meta.get('author',{}).get('login','?')}  "
            f"State: {meta.get('state')}  Draft: {meta.get('isDraft')}\n")
    f.write(f"Base: {meta.get('baseRefName')}  Head: {meta.get('headRefName')}\n")
    f.write(f"Changes: +{meta.get('additions',0)} / -{meta.get('deletions',0)} "
            f"across {meta.get('changedFiles',0)} files\n")
    f.write(f"Mergeable: {meta.get('mergeable')}  Labels: {labels}\n")
    f.write(f"URL: {meta.get('url')}\n\n")
    body = (meta.get("body") or "").strip()
    f.write("--- PR description ---\n")
    f.write(body if body else "(no description)")
    f.write("\n")
PY

echo "$OUTDIR"
