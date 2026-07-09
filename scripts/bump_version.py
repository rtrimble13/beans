#!/usr/bin/env python3
"""Set the project version and (optionally) create the release git tag.

The single source of truth for the version is ``beans/__init__.py``'s
``__version__`` string; ``pyproject.toml`` reads it dynamically. This script
rewrites that one string, then commits the change and creates an annotated
``vX.X.X`` git tag so the release workflow can pick it up.

Usage::

    python scripts/bump_version.py v1.2.3
    python scripts/bump_version.py v1.2.3 --push          # also push commit + tag
    python scripts/bump_version.py v1.2.3 --no-commit      # just edit the file
    python scripts/bump_version.py --show                  # print current version

Versions must be given in ``vX.X.X`` form (a leading ``v`` followed by a
PEP 440-compatible release number such as ``1.2.3`` or ``1.2.3rc1``). The
``v`` prefix is used for the git tag; the ``__version__`` string stores the
number without it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = ROOT / "beans" / "__init__.py"

# vMAJOR.MINOR.PATCH with an optional PEP 440 pre/post/dev suffix, e.g.
# v1.2.3, v1.2.3rc1, v2.0.0.dev1.
VERSION_RE = re.compile(
    r"^v(?P<num>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|\.post\d+|\.dev\d+)?)$"
)
_VERSION_LINE_RE = re.compile(
    r'^(?P<prefix>__version__\s*=\s*")(?P<ver>[^"]*)(?P<suffix>")',
    re.MULTILINE,
)


def _fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"bump_version: error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def read_current_version() -> str:
    text = INIT_FILE.read_text()
    m = _VERSION_LINE_RE.search(text)
    if not m:
        _fail(f"could not find __version__ in {INIT_FILE}")
    return m.group("ver")


def write_version(number: str) -> None:
    text = INIT_FILE.read_text()
    new_text, n = _VERSION_LINE_RE.subn(
        lambda m: f'{m.group("prefix")}{number}{m.group("suffix")}', text
    )
    if n != 1:
        _fail(f"expected exactly one __version__ assignment, found {n}")
    INIT_FILE.write_text(new_text)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        _fail(
            f"`git {' '.join(args)}` failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def ensure_clean_worktree() -> None:
    status = git("status", "--porcelain")
    if status:
        _fail(
            "working tree is not clean; commit or stash changes before "
            "bumping the version (or pass --no-commit)"
        )


def tag_exists(tag: str) -> bool:
    out = subprocess.run(
        ["git", "tag", "--list", tag], cwd=ROOT, capture_output=True, text=True
    )
    return bool(out.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bump_version",
        description="Set the project version and create the release git tag.",
    )
    parser.add_argument(
        "version", nargs="?",
        help="new version in vX.X.X form (e.g. v1.2.3)",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="print the current version and exit",
    )
    parser.add_argument(
        "--no-commit", action="store_true",
        help="edit beans/__init__.py but do not commit or tag",
    )
    parser.add_argument(
        "--no-tag", action="store_true",
        help="commit the version bump but do not create a git tag",
    )
    parser.add_argument(
        "--push", action="store_true",
        help="push the commit and tag to origin after creating them",
    )
    parser.add_argument(
        "--remote", default="origin",
        help="remote to push to with --push (default: origin)",
    )
    args = parser.parse_args(argv)

    if args.show:
        print(f"v{read_current_version()}")
        return 0

    if not args.version:
        parser.error("a version argument is required (e.g. v1.2.3)")

    m = VERSION_RE.match(args.version)
    if not m:
        _fail(
            f"'{args.version}' is not a valid version; expected vX.X.X "
            "(e.g. v1.2.3)"
        )
    number = m.group("num")
    tag = f"v{number}"

    if not args.no_commit:
        ensure_clean_worktree()
        if not args.no_tag and tag_exists(tag):
            _fail(f"tag {tag} already exists")

    current = read_current_version()
    if current == number and not args.no_commit:
        _fail(f"version is already {tag}; nothing to do")

    write_version(number)
    print(f"Set beans/__init__.py version: {current} -> {number}")

    if args.no_commit:
        print("Skipped commit/tag (--no-commit); file edited in place.")
        return 0

    git("add", str(INIT_FILE.relative_to(ROOT)))
    git("commit", "-m", f"Release {tag}")
    print(f"Committed version bump for {tag}")

    if not args.no_tag:
        git("tag", "-a", tag, "-m", f"Release {tag}")
        print(f"Created annotated tag {tag}")

    if args.push:
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        if branch == "HEAD":
            _fail(
                "cannot --push from a detached HEAD; check out a branch first "
                f"(the commit and tag {tag} were created locally)"
            )
        git("push", args.remote, branch)
        print(f"Pushed commit to {args.remote}/{branch}")
        if not args.no_tag:
            git("push", args.remote, tag)
            print(f"Pushed tag {tag} to {args.remote}")
    else:
        hint = f"git push {args.remote} HEAD"
        if not args.no_tag:
            hint += f" && git push {args.remote} {tag}"
        print(f"\nNext: {hint}")
        print("Pushing the tag triggers the release workflow.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
