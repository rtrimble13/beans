# Evaluation — removing `beans ai` and `beans mcp` in favour of a skill

**Date:** 2026-09-04
**Question:** Should `beans ai` and the MCP server be removed, with their
features merged into the proposed `beans-report` skill?
**Branch:** `claude/reporting-skill-evaluation-n4csum`
**Companion to:** [`reporting_skill_evaluation_20260904.md`](reporting_skill_evaluation_20260904.md)
**Method:** read `beans/ai/`, `beans/mcp/`, `beans/_toolcore/` in full; traced
every import boundary and measured the footprint.

---

## Verdict

**No — and the framing hides the real question.**

A skill cannot absorb these features, because it is not the same kind of thing.
`beans ai` and `beans mcp` expose **capability** — tools over a ledger, reachable
by whatever is driving. A skill encodes **procedure** — how to do a job well with
capability that already exists. `beans-import` is the proof already in the repo:
it did not replace `beans import`, it drives it. A `SKILL.md` cannot be a
JSON-RPC server, and it cannot be an LLM client.

There *is* a real problem underneath the question — after the reporting skill
there would be four overlapping "use AI with beans" entry points and four README
sections. But the fix for that is positioning, not amputation. And if a cut is
genuinely wanted, the candidate is `beans ai`, justified by *"beans should be
provably offline"* — not by *"the skill covers it,"* which is false.

---

## Why merging is not technically possible

### 1. The skill needs a local shell, so it needs Claude Code

The proposed skill works the way `beans-import` works: it shells out to
`beans … --json`. That requires an agent with local shell access. In practice
that is Claude Code.

| Surface | Who it serves | Survives the merge? |
|---|---|---|
| `beans ai` | a bare terminal, scripts, SSH, cron — and **local models** (Ollama / LM Studio / vLLM) with nothing leaving the machine | no |
| `beans mcp` | **Claude Desktop** and any other MCP host (an open protocol, many clients) | no |
| skill | Claude Code, with a shell | yes |

The README targets Claude Desktop explicitly, and `docs/mcp-setup-wsl.md` exists
solely to solve the WSL/Windows boundary *for Desktop users*. Merging does not
consolidate three audiences into one — it deletes two of them and keeps the one
that requires a specific commercial CLI.

### 2. It inverts the project's stated identity

beans' headline claim is *"No dependencies — the core is pure Python standard
library and fully offline; data lives in a single SQLite file you own."* Both
optional surfaces honour it: `pyproject.toml` declares `ai = []` and `mcp = []`
— **zero** third-party dependencies, because the HTTP client is `urllib` and the
JSON-RPC transport is hand-rolled.

Replacing them with a skill makes every AI capability in beans require
installing a commercial CLI from one vendor, plus a subscription. That is a
*heavier* dependency than the one it replaces, on a tool whose entire pitch is
that you own the data and the stack.

### 3. It is a safety regression, specifically for a ledger

The MCP server's read-only boundary is **structural**, not advisory:
`registry(allow_writes)` (`beans/_toolcore/tools.py:247`) returns `READ_TOOLS`
only, and `beans-mcp` defaults `allow_writes=False`. Without the flag the server
has no write tool to call. There is nothing to instruct, and nothing to forget.

A skill driving Bash has a full shell. Its guardrails are prose — which is why
`beans-import` needs eleven numbered rules to keep Claude from writing to a
financial record. Trading an enforced boundary for an instructed one is a
downgrade, and it is the wrong direction for the one part of this project where
mistakes are expensive eleven months later.

---

## What removal would actually buy

Measured, not estimated:

| Component | Lines | Notes |
|---|---:|---|
| `beans/ai/` | 881 | client 273, config 167, review 151, ask 130, prompts 112, init 48 |
| `beans/mcp/` | 620 | server 329, doctor 178, `__main__` 102, init 11 |
| `beans/_toolcore/` | 533 | **shared substrate** — tools 257, runner 165, bundle 58, redaction 36 |
| **Total** | **2,034** | ~19% of a 10,920-line codebase |
| Tests | 52 of 361 | 30 in `test_ai.py`, 22 in `test_mcp.py` |
| CLI coupling | 10 lazy imports | `beans/cli.py:1280–1420`; the surface is already well isolated |

Three genuine costs would go away:

1. **The model-ID treadmill.** `beans/ai/config.py:27` and `:31` hardcode
   `claude-sonnet-5`, `gpt-4o`, and provider base URLs. Model names rot; these
   need maintaining forever. Neither MCP nor a skill has this problem — the host
   owns the model.
2. **The only network-reaching code in the project.** `beans/ai/` is it. Deleting
   it would make beans *provably* offline rather than offline-by-configuration —
   a genuinely strong property for a financial tool, and one you can state
   without an asterisk.
3. **Four overlapping entry points.** This is the legitimate grievance behind the
   question, and it is real.

Against that, note the low coupling cost: ten lazy imports and a clean package
boundary mean these features are nearly free to *keep*. The maintenance burden is
concentrated almost entirely in `beans/ai/`'s provider adapters, not in the
surface area as a whole.

---

## Is there a cut worth making?

Yes — but it is a different question than the one asked: *should beans ship its
own LLM client at all?*

**`beans mcp` — keep, unconditionally.** It is the cheapest surface per unit of
reach: 620 lines, a thin binding over `_toolcore`, no network code of its own, no
model IDs to rot, and it serves every MCP host rather than one product. It should
be the last thing cut, not the first.

**`beans ai` — the only defensible removal candidate**, and only if you accept
losing terminal-only users and the local-model story (`beans ai ask` against
Ollama with nothing leaving the box is a capability *no* hosted-agent path
replaces). Two things to know before deciding:

- **Partial cuts save almost nothing.** `client.py` (273), `config.py` (167) and
  `prompts.py` (112) are shared by both subcommands, so dropping only `ask` (130
  lines) or only `review` (151) keeps the entire treadmill. It is all or nothing.
- **`_toolcore` survives either way**, because MCP depends on it — including
  `bundle.py`, which backs the `beans_review_bundle` tool. The one casualty is
  `redaction.py`: MCP never enables it (`beans/mcp/server.py:96` builds its
  `Runner` without `redact`), so scrubbing is an `ai`-only feature and would go
  with it.

**If the model-ID rot is the actual irritant**, fix that narrowly instead: drop
the `DEFAULT_MODELS` pins in favour of "provider default, or you must set one."
That is roughly twenty lines, not eight hundred and eighty-one.

---

## What I would do instead

The problem is positioning. It is about a day of documentation work, and it
solves the thing that actually bothers a user.

1. **One "beans + AI" section in the README**, replacing three parallel ones,
   opening with a decision table:

   | You want to… | Use |
   |---|---|
   | ask from a terminal, a script, or a local model, with no other software | `beans ai` |
   | ask from Claude Desktop, Claude Code, or any MCP host | `beans mcp` |
   | have Claude *do a job* — import a statement, run a trend briefing | a skill |

2. **State the boundary in each skill's description.** The `beans-import`
   description already disclaims reporting and must be amended when the
   reporting skill lands (see the companion evaluation).

3. **Build the reporting skill on the CLI**, as `beans-import` does — and have it
   say so when MCP is the better tool for a one-off question. Complementary, not
   competing.

4. **Keep `_toolcore` as the single source of truth.** It already prevents the
   `ai`/MCP drift its own docstring warns about. If `beans report trend` lands
   (companion evaluation, Phase 2), all three surfaces inherit it at once — which
   is the argument for keeping the layered design rather than collapsing it.

---

## If you remove `beans ai` anyway

A defensible sequence, should the offline-by-construction argument win:

1. Announce it in `README.md` and `docs/MANUAL.md` one minor release ahead;
   `beans ai` prints a deprecation line above its normal output.
2. Point the notice at the two replacements by audience: MCP for anyone with a
   host, and — honestly — *nothing* for terminal-only and local-model users. Do
   not claim the skill replaces it for them; it does not.
3. Delete `beans/ai/` and `tests/test_ai.py`, drop the `ai` extra from
   `pyproject.toml` (and from the `all` aggregate), and move `redaction.py` out
   of `_toolcore` or delete it with its last consumer.
4. Fold `docs/vignettes/07-ai-assistant.md` into the MCP vignette rather than
   deleting the worked examples — the questions it demonstrates are still the
   questions people have.
5. Update the headline: beans becomes a tool that *cannot* make a network
   request. Say it plainly — that is the whole return on the change.

Keep `beans mcp` in every scenario.

---

## Bottom line

Do not merge. The skill cannot hold these features: it needs a shell that only
Claude Code provides, it would replace a zero-dependency design with a
single-vendor one, and it would swap an enforced read-only boundary for an
instructed one on a financial record.

Keep MCP unconditionally — it is 620 lines and the widest reach in the project.
Fix the four-entry-points confusion with one README section and a decision table.
If `beans ai`'s provider treadmill is the real cost, either unpin the model
defaults (twenty lines) or remove the whole subpackage on its own merits — as a
deliberate choice to make beans provably offline, which is a good argument, and
not because a skill covers it, which is not true.
