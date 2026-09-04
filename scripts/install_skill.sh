#!/usr/bin/env bash
#
# Install the beans agent skills for Claude Code.
#
# Two skills ship with this repository and install independently:
#
#   beans-import   gets a bank/card CSV into the ledger, categorized and
#                  reconciled. Writes — after you approve a dry run.
#   beans-report   reads trends across periods and writes a briefing.
#                  Strictly read-only.
#
# By default both are symlinked into your personal skills directory, so they
# are available in every directory you run Claude Code from — not just this
# one — and edits here take effect immediately. Use --copy for a standalone
# install that does not depend on the repository staying put.
#
#   ./scripts/install_skill.sh                    # both, symlinked
#   ./scripts/install_skill.sh beans-report       # just one
#   ./scripts/install_skill.sh --copy             # copy instead of symlink
#   ./scripts/install_skill.sh --uninstall        # remove them
#   ./scripts/install_skill.sh --list             # what this repo ships
#   ./scripts/install_skill.sh --dir PATH         # install somewhere else
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_ROOT="$REPO_ROOT/.claude/skills"
TARGET_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
MODE="symlink"

# The skills this repository ships. `pr-review` and `project-review` are
# development tooling for the repo itself, not part of the product, so they
# are deliberately not installed into a user's personal skills directory.
AVAILABLE=(beans-import beans-report)
REQUESTED=()

usage() { sed -n '3,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --copy)       MODE="copy"; shift ;;
        --uninstall)  MODE="uninstall"; shift ;;
        --list)       printf '%s\n' "${AVAILABLE[@]}"; exit 0 ;;
        --all)        shift ;;   # the default; accepted for clarity
        --dir)        TARGET_DIR="$2"; shift 2 ;;
        -h|--help)    usage; exit 0 ;;
        -*)           echo "unknown option: $1" >&2; exit 2 ;;
        *)
            found=""
            for skill in "${AVAILABLE[@]}"; do
                [[ "$1" == "$skill" ]] && found="$1"
            done
            if [[ -z "$found" ]]; then
                echo "unknown skill: $1" >&2
                echo "available: ${AVAILABLE[*]}" >&2
                exit 2
            fi
            REQUESTED+=("$found"); shift ;;
    esac
done

if [[ ${#REQUESTED[@]} -eq 0 ]]; then
    REQUESTED=("${AVAILABLE[@]}")
fi

mkdir -p "$TARGET_DIR"

for SKILL_NAME in "${REQUESTED[@]}"; do
    SOURCE="$SKILL_ROOT/$SKILL_NAME"
    TARGET="$TARGET_DIR/$SKILL_NAME"

    if [[ "$MODE" == "uninstall" ]]; then
        if [[ -L "$TARGET" || -d "$TARGET" ]]; then
            rm -rf "$TARGET"
            echo "Removed $TARGET"
        else
            echo "Nothing installed at $TARGET"
        fi
        continue
    fi

    if [[ ! -f "$SOURCE/SKILL.md" ]]; then
        echo "error: $SOURCE/SKILL.md not found — run this from a beans checkout" >&2
        exit 1
    fi

    # Replace any previous install, whichever form it took.
    if [[ -L "$TARGET" || -e "$TARGET" ]]; then
        echo "Replacing existing install at $TARGET"
        rm -rf "$TARGET"
    fi

    if [[ "$MODE" == "symlink" ]]; then
        ln -s "$SOURCE" "$TARGET"
        echo "Linked $TARGET -> $SOURCE"
    else
        cp -R "$SOURCE" "$TARGET"
        echo "Copied $SOURCE -> $TARGET"
    fi
done

[[ "$MODE" == "uninstall" ]] && exit 0

if [[ "$MODE" == "symlink" ]]; then
    echo "  (edits in the repository take effect immediately)"
else
    echo "  (re-run this script after pulling to pick up changes)"
fi

echo
if command -v beans >/dev/null 2>&1; then
    echo "beans:  $(command -v beans)  ($(beans --version 2>/dev/null || echo 'version unknown'))"
else
    echo "! beans is not on PATH. The skills drive the beans CLI, so install it:"
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
echo "Done. Start Claude Code and ask, for example:"
for SKILL_NAME in "${REQUESTED[@]}"; do
    case "$SKILL_NAME" in
        beans-import)
            echo "    \"import my October checking statement from ~/statements/oct.csv\"" ;;
        beans-report)
            echo "    \"run my monthly financial review — what's been happening?\"" ;;
    esac
done
echo "Run /skills inside Claude Code to confirm they are listed."
