#!/usr/bin/env bash
#
# Install the beans-import skill for Claude Code.
#
# By default it symlinks the skill from this repository into your personal
# skills directory, so the skill is available in every directory you run
# Claude Code from — not just this one — and edits here take effect
# immediately. Use --copy for a standalone install that does not depend on
# the repository staying put.
#
#   ./scripts/install_skill.sh              # symlink into ~/.claude/skills
#   ./scripts/install_skill.sh --copy       # copy instead of symlink
#   ./scripts/install_skill.sh --uninstall  # remove it
#   ./scripts/install_skill.sh --dir PATH   # install somewhere else
#
set -euo pipefail

SKILL_NAME="beans-import"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_ROOT/.claude/skills/$SKILL_NAME"
TARGET_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
MODE="symlink"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --copy)       MODE="copy"; shift ;;
        --uninstall)  MODE="uninstall"; shift ;;
        --dir)        TARGET_DIR="$2"; shift 2 ;;
        -h|--help)    sed -n '3,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

TARGET="$TARGET_DIR/$SKILL_NAME"

if [[ "$MODE" == "uninstall" ]]; then
    if [[ -L "$TARGET" || -d "$TARGET" ]]; then
        rm -rf "$TARGET"
        echo "Removed $TARGET"
    else
        echo "Nothing installed at $TARGET"
    fi
    exit 0
fi

if [[ ! -f "$SOURCE/SKILL.md" ]]; then
    echo "error: $SOURCE/SKILL.md not found — run this from a beans checkout" >&2
    exit 1
fi

mkdir -p "$TARGET_DIR"

# Replace any previous install, whichever form it took.
if [[ -L "$TARGET" || -e "$TARGET" ]]; then
    echo "Replacing existing install at $TARGET"
    rm -rf "$TARGET"
fi

if [[ "$MODE" == "symlink" ]]; then
    ln -s "$SOURCE" "$TARGET"
    echo "Linked $TARGET -> $SOURCE"
    echo "  (edits in the repository take effect immediately)"
else
    cp -R "$SOURCE" "$TARGET"
    echo "Copied $SOURCE -> $TARGET"
    echo "  (re-run this script after pulling to pick up changes)"
fi

echo
if command -v beans >/dev/null 2>&1; then
    echo "beans:  $(command -v beans)  ($(beans --version 2>/dev/null || echo 'version unknown'))"
else
    echo "! beans is not on PATH. The skill drives the beans CLI, so install it:"
    echo "    pip install beans-ledger"
fi

LEDGER="${BEANS_LEDGER:-$HOME/.beans/ledger.db}"
if [[ -f "$LEDGER" ]]; then
    echo "ledger: $LEDGER"
else
    echo "! No ledger at $LEDGER. Create one with \`beans init\`,"
    echo "  or point BEANS_LEDGER at an existing file."
fi

echo
echo "Done. Start Claude Code and ask it to import a statement — for example:"
echo "    \"import my October checking statement from ~/statements/oct.csv\""
echo "Run /skills inside Claude Code to confirm beans-import is listed."
