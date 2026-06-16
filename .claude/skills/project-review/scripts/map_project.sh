#!/usr/bin/env bash
# map_project.sh — read-only reconnaissance for a project review.
#
# Prints a structured map of a codebase so the reviewer can pick hotspots before
# reading deeply: language/file breakdown, likely entry points, build/test/config
# files, the largest source files, and (if git is available) the most frequently
# changed files. It writes nothing and changes nothing.
#
# Usage: bash map_project.sh [project-root]   (defaults to current directory)

set -uo pipefail
ROOT="${1:-.}"
cd "$ROOT" 2>/dev/null || { echo "Cannot cd into '$ROOT'"; exit 1; }
ROOT_ABS="$(pwd)"

# Directories that are noise for a review.
PRUNE='-path */.git -o -path */node_modules -o -path */.venv -o -path */venv -o -path */dist -o -path */build -o -path */target -o -path */__pycache__ -o -path */.next -o -path */.idea -o -path */vendor -o -path */.mypy_cache -o -path */.pytest_cache'

echo "=================================================================="
echo "PROJECT MAP: $ROOT_ABS"
echo "=================================================================="

echo
echo "----- README / project intent (first 60 lines of top-level README) -----"
README=$(find . -maxdepth 1 -iname 'readme*' | head -1)
if [ -n "$README" ]; then echo "($README)"; head -60 "$README"; else echo "No top-level README found."; fi

echo
echo "----- Top-level layout (depth 2, dirs) -----"
find . -maxdepth 2 -type d \( $PRUNE \) -prune -o -type d -print 2>/dev/null | sort | head -60

echo
echo "----- File count by extension (source-ish, top 25) -----"
find . -type f \( $PRUNE \) -prune -o -type f -print 2>/dev/null \
  | sed -n 's/.*\.\([A-Za-z0-9_]*\)$/\1/p' | sort | uniq -c | sort -rn | head -25

echo
echo "----- Build / test / config / dependency manifests -----"
find . -maxdepth 3 \( $PRUNE \) -prune -o -type f \( \
  -iname 'package.json' -o -iname 'pyproject.toml' -o -iname 'setup.py' \
  -o -iname 'setup.cfg' -o -iname 'requirements*.txt' -o -iname 'Pipfile' \
  -o -iname 'go.mod' -o -iname 'Cargo.toml' -o -iname 'pom.xml' \
  -o -iname 'build.gradle*' -o -iname 'Makefile' -o -iname 'Dockerfile' \
  -o -iname 'docker-compose*.y*ml' -o -iname '*.cabal' -o -iname 'Gemfile' \
  -o -iname 'tox.ini' -o -iname 'pytest.ini' -o -iname 'jest.config.*' \
  -o -iname '.github' \) -print 2>/dev/null | sort | head -40

echo
echo "----- Likely entry points (main/index/app/cli/server) -----"
find . \( $PRUNE \) -prune -o -type f \( \
  -iname 'main.*' -o -iname 'index.*' -o -iname 'app.*' -o -iname 'cli.*' \
  -o -iname 'server.*' -o -iname '__main__.py' -o -iname 'wsgi.py' \
  -o -iname 'asgi.py' -o -iname 'manage.py' \) -print 2>/dev/null | sort | head -30

echo
echo "----- Largest source files (lines; top 25) -----"
find . \( $PRUNE \) -prune -o -type f \( \
  -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.tsx' -o -name '*.jsx' \
  -o -name '*.go' -o -name '*.rs' -o -name '*.java' -o -name '*.kt' \
  -o -name '*.rb' -o -name '*.php' -o -name '*.c' -o -name '*.cc' \
  -o -name '*.cpp' -o -name '*.h' -o -name '*.hpp' -o -name '*.cs' \
  -o -name '*.scala' -o -name '*.swift' -o -name '*.sh' \) -print 2>/dev/null \
  | xargs wc -l 2>/dev/null | sort -rn | sed '/total$/d' | head -25

echo
echo "----- Churn: most frequently changed files (git, last ~1000 commits) -----"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git log --no-merges -n 1000 --name-only --pretty=format: 2>/dev/null \
    | sed '/^$/d' | sort | uniq -c | sort -rn | head -25
else
  echo "Not a git repository (or git unavailable) — skipping churn analysis."
fi

echo
echo "----- TODO / FIXME / HACK / XXX markers (count, top 20 files) -----"
grep -rInE '\b(TODO|FIXME|HACK|XXX)\b' . \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv \
  --exclude-dir=venv --exclude-dir=dist --exclude-dir=build --exclude-dir=target \
  --exclude-dir=vendor 2>/dev/null | cut -d: -f1 | sort | uniq -c | sort -rn | head -20

echo
echo "=================================================================="
echo "Map complete. Use this as an index, not a substitute for reading."
echo "Pick hotspots: entry points, core modules, largest/churniest files,"
echo "and anything touching auth / input / external systems / persistence."
echo "=================================================================="
