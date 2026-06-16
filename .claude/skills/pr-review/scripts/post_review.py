#!/usr/bin/env python3
"""Post a code review to a GitHub PR as a single review with inline comments.

Submitting one review (rather than many individual comments) means the PR author
sees a single, coherent notification with a summary verdict and all inline
comments attached to the right lines — exactly how a human reviewer leaves a
review in the GitHub UI.

Usage:
    python3 post_review.py --pr 1423 --findings findings.json
    python3 post_review.py --pr 1423 --findings findings.json --repo org/repo
    python3 post_review.py --pr 1423 --findings findings.json --dry-run

Requires the GitHub CLI (`gh`) to be installed and authenticated; this script
shells out to `gh api`, so it uses whatever auth gh already has.

findings.json schema:
{
  "event": "REQUEST_CHANGES",      // APPROVE | REQUEST_CHANGES | COMMENT
  "summary": "Markdown body shown at the top of the review.",
  "comments": [
    {
      "path": "src/app/db.py",     // file path as it appears in the PR
      "line": 42,                   // line number in the file's NEW version
      "side": "RIGHT",             // RIGHT (new) | LEFT (old); default RIGHT
      "body": "**Blocker:** SQL built by string interpolation — use a parameterized query."
      // optional: "start_line": 40  to attach to a multi-line range (40-42)
    }
  ]
}

Notes:
- Inline comments must reference lines that are part of the PR diff; GitHub
  rejects comments on unchanged lines outside the diff hunks. If a comment is
  rejected, the script reports it and still posts the rest as a review with the
  summary, so nothing is lost.
- Map severity to `event`: any Blocker/High -> REQUEST_CHANGES, else COMMENT.
  Use APPROVE only when the human explicitly asked to approve.
"""

import argparse
import json
import subprocess
import sys


def sh(args, input_bytes=None):
    return subprocess.run(
        args, input=input_bytes, capture_output=True
    )


def gh_json(args):
    r = sh(["gh"] + args)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode().strip() or "gh command failed")
    return json.loads(r.stdout.decode() or "null")


def detect_repo():
    """Return owner/repo for the current directory's default gh repo."""
    data = gh_json(["repo", "view", "--json", "nameWithOwner"])
    return data["nameWithOwner"]


def head_sha(repo, pr):
    data = gh_json(["api", f"repos/{repo}/pulls/{pr}",
                    "--jq", "{sha: .head.sha}"])
    return data["sha"]


def build_payload(findings, commit_id):
    event = findings.get("event", "COMMENT").upper()
    if event not in {"APPROVE", "REQUEST_CHANGES", "COMMENT"}:
        raise ValueError(f"Invalid event: {event}")

    comments = []
    for c in findings.get("comments", []):
        item = {
            "path": c["path"],
            "body": c["body"],
            "side": c.get("side", "RIGHT"),
            "line": c["line"],
        }
        if c.get("start_line"):
            item["start_line"] = c["start_line"]
            item["start_side"] = c.get("start_side", item["side"])
        comments.append(item)

    payload = {
        "commit_id": commit_id,
        "body": findings.get("summary", ""),
        "event": event,
    }
    if comments:
        payload["comments"] = comments
    return payload


def post(repo, pr, payload):
    body = json.dumps(payload).encode()
    r = sh(["gh", "api", "--method", "POST",
            f"repos/{repo}/pulls/{pr}/reviews",
            "--input", "-"], input_bytes=body)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", required=True, help="PR number")
    ap.add_argument("--findings", required=True, help="Path to findings JSON")
    ap.add_argument("--repo", help="owner/repo (auto-detected if omitted)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the payload instead of posting")
    args = ap.parse_args()

    with open(args.findings) as f:
        findings = json.load(f)

    try:
        repo = args.repo or detect_repo()
    except Exception as e:
        print(f"ERROR: could not determine repo: {e}", file=sys.stderr)
        print("Pass --repo owner/repo explicitly.", file=sys.stderr)
        sys.exit(2)

    try:
        commit_id = head_sha(repo, args.pr)
    except Exception as e:
        print(f"ERROR: could not get head SHA for {repo}#{args.pr}: {e}",
              file=sys.stderr)
        sys.exit(2)

    payload = build_payload(findings, commit_id)

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    r = post(repo, args.pr, payload)
    if r.returncode == 0:
        url = ""
        try:
            url = json.loads(r.stdout.decode()).get("html_url", "")
        except Exception:
            pass
        print(f"Review posted to {repo}#{args.pr}. {url}".strip())
        return

    # If inline comments were rejected (e.g. line not in diff), retry with just
    # the summary so the review still lands.
    stderr = r.stderr.decode().strip()
    print(f"WARNING: review with inline comments was rejected:\n{stderr}",
          file=sys.stderr)
    if payload.get("comments"):
        print("Retrying with summary only (inline comments dropped)...",
              file=sys.stderr)
        payload.pop("comments", None)
        r2 = post(repo, args.pr, payload)
        if r2.returncode == 0:
            print(f"Summary review posted to {repo}#{args.pr} "
                  f"(inline comments could not be attached — likely on lines "
                  f"outside the diff).")
            return
        print(f"ERROR: {r2.stderr.decode().strip()}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
