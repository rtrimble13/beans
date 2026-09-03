# The `beans-import` skill for Claude Code — install & setup

`beans-import` is a [Claude Code](https://claude.com/claude-code) **agent
skill**: a set of instructions Claude loads when you ask it to get statement
activity into your ledger. It drives the ordinary `beans` CLI —
`categorize`, `rule`, `import`, `reconcile` — through a review-first workflow,
and it never writes to your ledger without showing you a dry run first.

It is **not** the same thing as the [MCP server](mcp-setup-wsl.md). The two are
complementary and can be installed together:

| | What it is | What it does | Writes? |
|---|---|---|---|
| **MCP server** (`beans mcp`) | A set of tools Claude can call | Answers questions about your finances: statements, budgets, forecasts, ratios | Read-only by default |
| **`beans-import` skill** | A procedure Claude follows | Gets a bank or card CSV into the ledger, categorized and reconciled | Yes — after you approve a dry run |

---

## 0. Prerequisites

You need `beans` installed and a ledger to import into.

```bash
pip install beans-ledger        # or pip install -e . from a checkout
beans --version
beans init                      # if you don't have a ledger yet
```

Claude Code must be able to run `beans` — so install both in the same place. If
you use WSL (see [§4](#4-wsl-notes)), that means **inside WSL**, and you run
`claude` inside WSL too.

---

## 1. Install the skill

From a `beans` checkout:

```bash
git clone https://github.com/rtrimble13/beans.git
cd beans
./scripts/install_skill.sh
```

That symlinks `.claude/skills/beans-import` into `~/.claude/skills/`, which is
your **personal** skills directory. Two things follow from that:

- The skill is available in **every** directory you run Claude Code from — not
  just the repository. This matters, because your ledger and your statement
  downloads almost certainly live somewhere else.
- Because it is a symlink, edits in the checkout take effect immediately. Pull
  the repo and you have the new version; no reinstall.

Prefer a copy that does not depend on the checkout staying where it is:

```bash
./scripts/install_skill.sh --copy      # re-run after pulling to update
```

Other options:

```bash
./scripts/install_skill.sh --dir /path/to/skills   # somewhere else entirely
./scripts/install_skill.sh --uninstall             # remove it
```

The script reports whether `beans` is on your PATH and whether it can find a
ledger, so a broken setup shows up now rather than mid-import.

### Doing it by hand

The script does no magic. This is all it is:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/.claude/skills/beans-import" ~/.claude/skills/beans-import
```

### Project-scoped instead

If you only ever want the skill while working *in* the beans repository, skip
the install entirely — Claude Code already discovers `.claude/skills/` in the
current project. This is the right choice for developing the skill and the
wrong one for using it, since that is not where your statements live.

---

## 2. Verify

```bash
cd ~                       # deliberately not the repo
claude
```

Then, inside Claude Code:

```
/skills
```

`beans-import` should be listed. If it is not, see
[§5](#5-troubleshooting).

---

## 3. Use it

Just ask. The skill's description is what triggers it, so ordinary phrasing
works:

```
import my October checking statement from ~/statements/oct.csv
```
```
categorize this credit card export and tell me what needs a decision
```
```
reconcile my checking account against the statement I just imported
```

What Claude will do, in order:

1. **Preflight** — check which ledger it is about to touch, confirm the account
   name resolves, and check whether the period is closed.
2. **Read the file** — work out the column mapping, date format and sign
   convention from the file itself, and tell you what it found. Statements
   whose shape `beans` cannot read directly (`MM/DD/YYYY` dates, split
   debit/credit columns) are normalized into a working copy first; your
   original is never modified.
3. **Categorize** — `beans categorize`, which writes nothing to the ledger, and
   produces a prepared CSV.
4. **Triage** — the part worth having help with. Claude groups the uncertain
   rows by merchant, searches your register for context, tells thin evidence
   apart from genuinely conflicting evidence, and flags the traps that a
   confidence score cannot catch — transfers between your own accounts,
   refunds, and credit-card payments booked as income.
5. **Propose** — a table of every suggested account and rule. **Nothing has
   been written at this point.** You approve, amend or reject.
6. **Import** — a dry run first, shown to you, then the real import once you
   say go.
7. **Prove it** — reconcile line by line against the original statement, so
   what got written is checked against what the bank says.

### What it will not do

These are guardrails written into the skill, not preferences:

- No import without showing you a dry run and getting a go-ahead **in that same
  turn**. Approving one statement does not approve the next.
- Never `--learn`, which would write history-inferred accounts nobody reviewed.
- Never `--no-dedupe` unless you have said a duplicate is intended.
- Never an account name that is not already in your chart of accounts.
- Never an edit to your original export.
- Never reopening a closed accounting period on its own.

Confidence scores rank your attention; `beans` deliberately has no auto-accept
threshold, and the skill does not invent one.

### Keeping working files private

A prepared CSV lists every merchant you paid that month. Keep working copies in
a directory your version control ignores — the beans repo ignores `work/` and
`*-prepared.csv` for exactly this reason — and keep your ledger out of any
repository you push.

---

## 4. WSL notes

The skill runs `beans` as a subprocess, so **`beans` and `claude` must be on
the same side of the WSL boundary.** Install both inside WSL and run `claude`
from a WSL shell. That is the supported path, and there is nothing further to
configure.

If you run Claude Code on native Windows against a ledger inside WSL, the skill
cannot reach `beans` — the CLI calls would need a `wsl.exe` wrapper the skill
does not add. Use Claude Code inside WSL instead. (The **MCP server** does
support the boundary, via a wrapper in the host config;
[`docs/mcp-setup-wsl.md`](mcp-setup-wsl.md) covers it.)

Windows-side statement downloads are reachable from WSL under `/mnt/c/`:

```bash
ls /mnt/c/Users/YOU/Downloads/*.csv
```

Copy the file into your WSL home before working on it if you would rather not
have Claude reading around your Windows profile.

---

## 5. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `/skills` does not list `beans-import` | Check `ls -l ~/.claude/skills/beans-import`. A dangling symlink means the checkout moved — re-run the install script, or use `--copy`. Restart Claude Code after installing. |
| Claude answers about importing but does not follow the workflow | The skill did not trigger. Say what you want in terms of the ledger — "import this into beans", "categorize this statement" — rather than asking about the file in the abstract. |
| `beans: command not found` in Claude's output | `beans` is not on the PATH Claude Code inherits. Check `command -v beans` in the *same shell* you launch `claude` from; if you use a virtualenv, activate it before launching. |
| Claude is importing into the wrong ledger | The skill reports which ledger it resolved during preflight. Set `BEANS_LEDGER`, or tell Claude the path — it passes `beans -f PATH`. |
| `invalid date: '10/02/2026'` | Expected: `beans` accepts only `YYYY-MM-DD`. The skill's `normalize_csv.py` rewrites the file; ask Claude to normalize it first. |
| `column 'date' not found` | Your export uses different header names. The skill's `inspect_csv.py` derives the right `--date-col`/`--desc-col`/`--amount-col` flags from the file. |
| Every amount has the wrong sign | A card export reporting purchases as positive. `--invert` fixes it; the skill detects this and asks you to confirm. |
| Duplicates skipped that you wanted imported | Deduplication keys on `(date, account, amount)`. It is doing its job on an overlapping statement period. If you genuinely want the duplicate, say so — the skill will not pass `--no-dedupe` on its own. |

### Running the skill's helpers by hand

They are ordinary scripts and work outside Claude Code, which is the fastest way
to check whether a problem is the statement or the setup:

```bash
SKILL=~/.claude/skills/beans-import
python3 $SKILL/scripts/inspect_csv.py statement.csv
python3 $SKILL/scripts/normalize_csv.py statement.csv -o work/clean.csv
python3 $SKILL/scripts/triage.py work/prepared.csv
```

---

## 6. What's in the skill

```
.claude/skills/beans-import/
├── SKILL.md                        the workflow and its guardrails
├── references/
│   ├── csv-shapes.md               export shapes and the flags each needs
│   ├── triage-playbook.md          reading confidence vs. basis; the traps
│   └── command-reference.md        exact flags for the commands used
└── scripts/
    ├── inspect_csv.py              derive the column mapping from a file
    ├── normalize_csv.py            rewrite an export into the shape beans reads
    └── triage.py                   group uncertain rows by merchant
```

Everything is plain text. Read `SKILL.md` if you want to know exactly what
Claude has been told to do — and edit it if you want it to behave differently.
The scripts are covered by the project's test suite (`tests/test_skill_scripts.py`).

For a start-to-finish walkthrough with runnable sample data, see the
[Claude skill vignette](vignettes/09-claude-skill.md).
