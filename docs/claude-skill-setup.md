# The beans skills for Claude Code — install & setup

Two [Claude Code](https://claude.com/claude-code) **agent skills** ship with
this repository. A skill is a set of instructions Claude loads when a job
matches it; both drive the ordinary `beans` CLI, so their figures are the ones
your own statements show.

- **`beans-import`** — gets statement activity into your ledger via
  `categorize`, `rule`, `import`, `reconcile`, through a review-first workflow.
  It writes, but never without showing you a dry run first.
- **`beans-report`** — reads what is already there *across periods*: assembles
  a series `beans` does not keep, separates real drift from one-off spikes and
  noise, and writes a short ranked briefing. Strictly read-only.

Neither is the same thing as the [MCP server](mcp-setup-wsl.md). All three are
complementary and can be installed together:

| | What it is | What it does | Writes? |
|---|---|---|---|
| **MCP server** (`beans mcp`) | A set of tools Claude can call | Answers questions about one period: statements, budgets, forecasts, ratios | Read-only by default |
| **`beans-import` skill** | A procedure Claude follows | Gets a bank or card CSV into the ledger, categorized and reconciled | Yes — after you approve a dry run |
| **`beans-report` skill** | A procedure Claude follows | Reads trends across many periods and briefs you on what changed | Never |

The dividing line: the **server reads** a period on demand, `beans-import`
**writes** a statement in, and `beans-report` **reads across time**. A question
about one month is the server's job; a question about the last twelve is
`beans-report`'s.

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

## 1. Install the skills

From a `beans` checkout:

```bash
git clone https://github.com/rtrimble13/beans.git
cd beans
./scripts/install_skill.sh              # both skills
./scripts/install_skill.sh beans-report # or name just one
./scripts/install_skill.sh --list       # what this repo ships
```

That symlinks each `.claude/skills/<skill>` into `~/.claude/skills/`, which is
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
ln -s "$PWD/.claude/skills/beans-report" ~/.claude/skills/beans-report
```

### Project-scoped instead

If you only ever want the skills while working *in* the beans repository, skip
the install entirely — Claude Code already discovers `.claude/skills/` in the
current project. This is the right choice for developing them and the wrong one
for using them, since that is not where your statements or your ledger live.

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

`beans-import` and `beans-report` should both be listed. If either is not, see
[§5](#5-troubleshooting).

---

## 3. Use them

Just ask. A skill's description is what triggers it, so ordinary phrasing works
— and phrasing is also how you choose between them: a *file* going in is
`beans-import`, a question about *time* is `beans-report`.

### `beans-import`

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

### What `beans-import` will not do

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

### `beans-report`

```
run my monthly financial review — what's been happening?
```
```
are my expenses creeping up, or was that just a bad month?
```
```
how has my savings rate moved this year, and what's driving it?
```

What Claude will do, in order:

1. **Preflight** — resolve the ledger, work out today's date and therefore the
   last *complete* period, check how far your history reaches, and measure how
   much spending is sitting uncategorized. Blockers are reported before any
   analysis, not after.
2. **Gather** — assemble many periods of `report income`, `analyze`, `networth`
   and `budget report` into one series, in a single pass. The figures are
   copied verbatim from `beans --json`; nothing is recomputed.
3. **Classify** — fit each account robustly and label it `drift`, `step`,
   `one-off`, `new`, `stopped` or `stable`. Median-based statistics throughout,
   so a single large bill never becomes a trend.
4. **Infer** — cross the findings against your recurring rules, budgets and
   goals: subscription creep, a payment that quietly lapsed, a budget that is
   wrong rather than a month that was bad, what a drift does to a goal date.
5. **Brief** — three to five ranked findings, each tied to a figure and a
   window, each with a proposed action, plus the caveats.

### What `beans-report` will not do

Also guardrails, not preferences:

- **Never trend a period that has not fully elapsed.** On the 4th of the month,
  that month shows four days of spending and often no salary at all. Run it into
  a twelve-month series and it reads as an income collapse and a runway falling
  by three quarters — both false. The current period is excluded, and if it is
  ever shown it is labelled partial every time.
- **Never write to your ledger.** Not a budget, not a rule, not a period close.
  Recommendations are printed as commands for you to run.
- **Never call one bill a trend**, and never report a lapsed recurring payment
  as a welcome drop in spending.
- **Never present category trends over a ledger that cannot support them.** If
  too much spending sits in `Expenses:Other`, it says so and offers totals.
- **Never manufacture a concern.** "Nothing much changed" is a valid answer, and
  the right one most months.
- **Never assert a trend from fewer than six periods** without saying the
  finding is directional, and never from fewer than three at all.

### Keeping working files private

A prepared CSV lists every merchant you paid that month, and a series file lists
your account totals. Keep both in a directory your version control ignores — the
beans repo ignores `work/` and `*-prepared.csv` for exactly this reason — and
keep your ledger out of any repository you push.

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
| `/skills` does not list a skill | Check `ls -l ~/.claude/skills/`. A dangling symlink means the checkout moved — re-run the install script, or use `--copy`. Restart Claude Code after installing. |
| Claude answers about importing but does not follow the workflow | The skill did not trigger. Say what you want in terms of the ledger — "import this into beans", "categorize this statement" — rather than asking about the file in the abstract. |
| Claude answers a trend question from one period | `beans-report` did not trigger. Ask about a span of time — "over the last year", "what's been changing", "run my monthly review" — rather than naming a single month. |
| `beans-report` says most of your window predates the first transaction | Expected on a young ledger. Ask for fewer periods; a trend needs three at minimum and reads reliably from six. |
| `beans-report` refuses to give category trends | Too much spending is in `Expenses:Other`. Categorize it (`beans categorize`, or the `beans-import` skill) and re-run; totals-level findings are still available meanwhile. |
| A trend briefing looks wrong for the current month | It excludes the month in progress on purpose — a part-elapsed period is not comparable. See §3. |
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

SKILL=~/.claude/skills/beans-report
python3 $SKILL/scripts/preflight.py --months 12       # exit 1 means a blocker
python3 $SKILL/scripts/series.py --months 12 -o work/series.json
python3 $SKILL/scripts/trend.py work/series.json
```

All of them take `--help`. `preflight.py` is the useful one to run first: it
tells you whether your ledger can support a trend read at all.

---

## 6. What's in the skills

```
.claude/skills/beans-import/
├── SKILL.md                        the workflow and its guardrails
├── references/
│   ├── csv-shapes.md               export shapes and the flags each needs
│   ├── triage-playbook.md          reading confidence vs. basis; the traps
│   ├── recurring-overlap.md        rules that collide with a statement
│   └── command-reference.md        exact flags for the commands used
└── scripts/
    ├── inspect_csv.py              derive the column mapping from a file
    ├── normalize_csv.py            rewrite an export into the shape beans reads
    ├── recur_match.py              find recurring rules a statement duplicates
    └── triage.py                   group uncertain rows by merchant

.claude/skills/beans-report/
├── SKILL.md                        the workflow and its guardrails
├── references/
│   ├── method.md                   reading a series without lying to yourself
│   ├── inference-playbook.md       named patterns and what each implies
│   └── command-reference.md        the read-only report surface
└── scripts/
    ├── beans_io.py                 read-only command whitelist, periods, money
    ├── preflight.py                can this ledger support a trend read?
    ├── series.py                   gather N periods into one series
    └── trend.py                    classify drift / step / one-off / …
```

Everything is plain text. Read a `SKILL.md` if you want to know exactly what
Claude has been told to do — and edit it if you want different behaviour. The
scripts are covered by the project's test suite
(`tests/test_skill_scripts.py`), including the arithmetic behind every trend
classification and the read-only whitelist that keeps `beans-report` from
writing.

For start-to-finish walkthroughs with runnable sample data, see the
[import vignette](vignettes/09-claude-skill.md) and the
[trend-briefing vignette](vignettes/10-reporting-skill.md).
