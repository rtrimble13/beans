#!/usr/bin/env python3
"""
create_issues.py — file a project-review backlog as GitHub issues, safely.

This is the ONLY part of the project-review skill that writes outside the working
tree. It is invoked only after the user has explicitly confirmed which findings to
file. It is idempotent: each finding carries a hidden marker, and an issue is
created only if no existing issue (open or closed) already carries that marker, so
re-running a review does not create duplicates.

USAGE
    python3 create_issues.py --findings findings.json [--dry-run] [--repo owner/name]
                             [--out results.json]

    --dry-run   Print what would be created/skipped, create nothing. Always run
                this first and show the user.
    --repo      Override the target repo (default: auto-detected from the cwd's
                GitHub remote via `gh`).
    --out       Write the results JSON here (default: stdout only).

REQUIREMENTS
    The `gh` CLI must be installed and authenticated, and the repo must be hosted
    on GitHub with Issues enabled. If `gh repo view` fails, this script exits
    non-zero with a clear message; the caller should fall back to writing
    backlog/ files instead.

INPUT — findings.json
    {
      "findings": [
        {
          "seq": 1,
          "slug": "sql-injection-in-get-task",
          "title": "SQL injection in db.get_task",
          "tier": "P0",                 // P0 | P1 | P2 | P3
          "lens": "Hidden bug",         // Robustness | Refactoring | Enhancement | Hidden bug
          "severity": "Critical",       // Critical|High|Medium|Low for defects; null/"-" otherwise
          "body": "## Problem\n...full markdown work item (the backlog template)..."
        }
      ]
    }

OUTPUT — results JSON
    {
      "repo": "owner/name",
      "dry_run": false,
      "results": [
        {"slug": "...", "action": "created"|"skipped-existing"|"would-create",
         "url": "https://github.com/...", "title": "..."}
      ]
    }
"""

import argparse
import json
import subprocess
import sys

MARKER_FMT = "<!-- project-review:{slug} -->"

# label name -> hex color (GitHub label colors, no leading '#')
TIER_COLORS = {"P0": "b60205", "P1": "d93f0b", "P2": "fbca04", "P3": "0e8a16"}
SEVERITY_COLORS = {
    "Critical": "b60205", "High": "d93f0b", "Medium": "fbca04", "Low": "c2e0c6",
}
LENS_LABELS = {
    "robustness": ("robustness", "1d76db"),
    "refactoring": ("refactoring", "5319e7"),
    "refactor": ("refactoring", "5319e7"),
    "enhancement": ("enhancement", "0e8a16"),
    "hidden bug": ("bug", "b60205"),
    "bug": ("bug", "b60205"),
}
BASE_LABEL = ("project-review", "5319e7")


def run(cmd, input_text=None, check=True):
    """Run a command, return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd, input=input_text, capture_output=True, text=True
        )
    except FileNotFoundError:
        print(f"ERROR: `{cmd[0]}` not found. Install/authenticate the GitHub CLI "
              f"(`gh`) or fall back to backlog/ files.", file=sys.stderr)
        sys.exit(3)
    if check and p.returncode != 0:
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def detect_repo(override):
    if override:
        return override
    rc, out, err = run(["gh", "repo", "view", "--json", "nameWithOwner",
                        "-q", ".nameWithOwner"], check=True)
    if rc != 0 or not out:
        print("ERROR: could not resolve a GitHub repo from this directory.\n"
              f"  gh said: {err or '(no output)'}\n"
              "  Not a GitHub remote, `gh` not authenticated, or Issues disabled.\n"
              "  Fall back to writing backlog/ files.", file=sys.stderr)
        sys.exit(2)
    return out


def labels_for(finding):
    labels = [BASE_LABEL]
    tier = finding.get("tier")
    if tier in TIER_COLORS:
        labels.append((tier, TIER_COLORS[tier]))
    lens = (finding.get("lens") or "").strip().lower()
    if lens in LENS_LABELS:
        labels.append(LENS_LABELS[lens])
    sev = finding.get("severity")
    if sev in SEVERITY_COLORS:
        labels.append((f"severity:{sev}", SEVERITY_COLORS[sev]))
    # de-dupe by name, preserve order
    seen, out = set(), []
    for name, color in labels:
        if name not in seen:
            seen.add(name)
            out.append((name, color))
    return out


def ensure_labels(repo, label_pairs, dry_run):
    if dry_run:
        return
    for name, color in label_pairs:
        # --force creates or updates without erroring if it already exists.
        run(["gh", "label", "create", name, "--color", color,
             "--repo", repo, "--force"], check=False)


def existing_issue(repo, marker):
    """Return the URL of an existing issue carrying the marker, or None."""
    rc, out, err = run(
        ["gh", "issue", "list", "--repo", repo, "--state", "all",
         "--search", f'"{marker}"', "--json", "number,url,title", "--limit", "50"],
        check=False,
    )
    if rc != 0 or not out:
        return None
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return None
    return items[0]["url"] if items else None


def main():
    ap = argparse.ArgumentParser(description="File project-review findings as GitHub issues.")
    ap.add_argument("--findings", required=True)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.findings) as f:
        data = json.load(f)
    findings = data.get("findings", [])
    if not findings:
        print("No findings to file.", file=sys.stderr)
        sys.exit(0)

    repo = detect_repo(args.repo)

    # Pre-create every label this batch needs.
    all_labels = {}
    for fnd in findings:
        for name, color in labels_for(fnd):
            all_labels[name] = color
    ensure_labels(repo, list(all_labels.items()), args.dry_run)

    results = []
    for fnd in findings:
        slug = fnd["slug"]
        marker = MARKER_FMT.format(slug=slug)
        title = fnd["title"]
        label_names = [n for n, _ in labels_for(fnd)]

        url = existing_issue(repo, marker)
        if url:
            results.append({"slug": slug, "action": "skipped-existing",
                            "url": url, "title": title})
            continue

        if args.dry_run:
            results.append({"slug": slug, "action": "would-create", "url": None,
                            "title": title, "labels": label_names})
            continue

        body = fnd.get("body", "").rstrip() + "\n\n" + marker
        cmd = ["gh", "issue", "create", "--repo", repo, "--title", title,
               "--body-file", "-"]
        for n in label_names:
            cmd += ["--label", n]
        rc, out, err = run(cmd, input_text=body, check=False)
        if rc != 0:
            results.append({"slug": slug, "action": "error", "url": None,
                            "title": title, "error": err})
        else:
            results.append({"slug": slug, "action": "created",
                            "url": out.strip(), "title": title})

    output = {"repo": repo, "dry_run": args.dry_run, "results": results}
    text = json.dumps(output, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)

    # Human-readable summary to stderr so stdout stays parseable.
    created = sum(1 for r in results if r["action"] == "created")
    would = sum(1 for r in results if r["action"] == "would-create")
    skipped = sum(1 for r in results if r["action"] == "skipped-existing")
    errored = sum(1 for r in results if r["action"] == "error")
    verb = "Would create" if args.dry_run else "Created"
    n = would if args.dry_run else created
    print(f"[{repo}] {verb} {n} issue(s); skipped {skipped} existing; "
          f"{errored} error(s).", file=sys.stderr)
    for r in results:
        line = f"  - {r['action']:18s} {r['slug']}"
        if r.get("url"):
            line += f"  {r['url']}"
        if r.get("error"):
            line += f"  ERROR: {r['error']}"
        print(line, file=sys.stderr)

    print(text)
    sys.exit(1 if errored else 0)


if __name__ == "__main__":
    main()
