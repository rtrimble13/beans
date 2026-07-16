# Using beans from Claude (MCP) — WSL setup guide

`beans` ships an optional **MCP server** that exposes your ledger as read-only
tools and a `review` prompt, so **Claude Desktop** and **Claude Code** can read
your finances and answer questions directly. The host (Claude) owns the model;
`beans` just answers tool calls. No API key lives in `beans`, and there is no
embedded LLM.

This guide targets one specific, common topology:

> **`beans` runs in WSL/Ubuntu. Claude Desktop runs in native Windows. Claude
> Code runs on the command line (recommended: inside WSL).**

The server code is identical for every host — only *registration* differs. The
Windows→WSL boundary is the only hard part, so most of this guide is about
crossing it cleanly.

> **Local-first, read-only by default.** The server runs on *your* machine next
> to the ledger file and never reaches the network. It exposes read-only tools
> only; writes are opt-in (`--allow-writes`) and, even then, the host asks you
> to approve every call.

---

## 0. Install

Inside WSL:

```bash
pip install "beans-ledger[mcp]"
```

The `[mcp]` extra adds **no** third-party dependency — the MCP protocol is
implemented on the Python standard library. It exists to give you the
`beans-mcp` command and mark the feature as opted-in.

## 1. Run the doctor first

The single highest-leverage step. Inside WSL:

```bash
beans mcp doctor
```

```
beans mcp doctor — checking the MCP server setup
=======================================================

1. Entry point
    ok   beans-mcp → /home/you/.venvs/beans/bin/beans-mcp

2. Ledger
    ok   /home/you/.beans/ledger.db (readable, on the Linux filesystem)

3. stdout cleanliness
    ok   only JSON-RPC on stdout (initialize + tools/list)

4. Claude Desktop config (Windows side)
        Find your distro name in PowerShell: wsl -l -v
        Paste this into claude_desktop_config.json (adjust distro):
        {
          "mcpServers": {
            "beans": {
              "command": "wsl.exe",
              "args": [ "-d", "Ubuntu", "--",
                        "/home/you/.venvs/beans/bin/beans-mcp",
                        "--file", "/home/you/.beans/ledger.db" ]
            }
          }
        }

5. Transport
    ok   zero-dependency stdlib JSON-RPC (no MCP SDK required)
        protocol version: 2025-06-18
```

`doctor` prints the two things every config needs — your **absolute
`beans-mcp` path** and your **ledger path** — and it *actually starts the
server* to confirm nothing contaminates stdout (check 3). Copy the snippet it
prints; it already has your real paths filled in.

Find your distro name for the `-d` flag from **Windows PowerShell**:

```powershell
wsl -l -v
```

---

## 2. Claude Desktop (Windows → WSL) — the primary case

Claude Desktop is a native Windows app, so it must cross into WSL via
`wsl.exe`. Edit `claude_desktop_config.json` (on the **Windows** side —
Claude Desktop → Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "beans": {
      "command": "wsl.exe",
      "args": [
        "-d", "Ubuntu",
        "--",
        "/home/you/.venvs/beans/bin/beans-mcp",
        "--file", "/home/you/.beans/ledger.db"
      ]
    }
  }
}
```

- Replace `Ubuntu` with your distro (from `wsl -l -v`) and both paths with your
  real ones (from `beans mcp doctor`).
- **Direct exec** of `beans-mcp` — no `bash -l`/`bash -i` wrapper — keeps
  stdout clean (see Hazard 1 below).
- The ledger path is explicit and on the Linux filesystem (Hazards 2–3).

Restart Claude Desktop. `beans` should appear as a connected MCP server with
its tools available.

---

## 3. Claude Code inside WSL — the recommended dev case

When Claude Code runs **inside WSL**, there is no boundary at all — register the
server directly:

```bash
claude mcp add beans --scope user -- beans-mcp --file ~/.beans/ledger.db
claude mcp list          # verify
```

This is the clean path for day-to-day use.

---

## 4. Claude Code on native Windows — fallback

If you run Claude Code on Windows instead, mirror the Desktop wrapper:

```bash
claude mcp add-json beans '{
  "command": "wsl.exe",
  "args": ["-d","Ubuntu","--","/home/you/.venvs/beans/bin/beans-mcp","--file","/home/you/.beans/ledger.db"]
}'
```

---

## 5. Manual boundary smoke test (optional)

To prove the crossing works before involving a host, run this from **Windows
PowerShell**. Expect a single clean JSON-RPC response — no banners, no stray
text:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' |
  wsl.exe -d Ubuntu -- /home/you/.venvs/beans/bin/beans-mcp --file /home/you/.beans/ledger.db
```

If you get JSON back, the boundary is sound. If you get silence or banner text,
work through the troubleshooting table.

---

## 6. Troubleshooting — the three boundary hazards

| Symptom | Hazard | Fix |
|---|---|---|
| Host shows an opaque **"server disconnected"**; the smoke test prints a banner/MOTD or other text before the JSON | **1 — stdout contamination.** MCP over stdio requires *only* JSON-RPC on stdout. | Invoke `beans-mcp` **directly** (as above), never via `bash -l`/`bash -i` — a login/interactive shell prints the MOTD and sources `~/.bashrc`. `beans mcp doctor` check 3 reproduces this locally. |
| Server starts but reads the **wrong ledger** (or "no ledger" errors) | **2 — path/env translation.** Windows env vars don't reliably cross into WSL. | Pass the ledger as an explicit **Linux** path with `--file /home/you/.beans/ledger.db`. (Env alternative: `WSLENV`, see below — but `--file` is preferred.) |
| Server is slow, hangs, or reports lock/IO errors | **3 — SQLite on `/mnt/c`.** SQLite locking over the `/mnt` 9p mount is slow and unreliable. | Keep the ledger on the Linux filesystem (`~/.beans/…`). `beans-mcp` **refuses** a `--file` under `/mnt/` with guidance. |
| Wrong or renamed distro | — | Use `-d <Distro>` with the exact name from `wsl -l -v`. |
| `beans-mcp: command not found` in the config | — | Use the **absolute** path from `beans mcp doctor` (Windows can't resolve WSL's PATH). |

### Env-var alternative to `--file` (optional)

Instead of `--file`, you can propagate `BEANS_LEDGER` into WSL. In the Desktop
config's `env` block set both `BEANS_LEDGER` (a Linux path) and
`WSLENV=BEANS_LEDGER` (no `/p` flag — the value is already a Linux path and must
**not** be translated). The explicit `--file` arg is preferred for being
self-contained and translation-proof.

---

## 7. What the server exposes

Read-only tools (each maps 1:1 to a `beans … --json` command and returns
structured JSON):

`beans_income_statement`, `beans_balance_sheet`, `beans_cashflow`,
`beans_analyze`, `beans_list_transactions`, `beans_search`, `beans_register`,
`beans_budget_report`, `beans_forecast`, `beans_networth`,
`beans_list_accounts`, `beans_economic_balance_sheet`, and
`beans_review_bundle` (assembles the full analyst report set in one call).

A **`review`** prompt carries the CFO-style analyst framing; invoke it in the
host and Claude will call `beans_review_bundle` and narrate a briefing.

### Writes (advanced, off by default)

Add `--allow-writes` to the launch command to enable a small set of mutating
tools (record an expense/income/transfer). Even then, the **host** prompts you
to approve each call — confirmation lives in Claude Desktop/Code, not in
`beans`. Leave this off unless you specifically want it.

---

## Quick reference — finding your specifics

```bash
command -v beans-mcp        # absolute entry-point path for the config
beans mcp doctor            # validates path, ledger, and stdout cleanliness
```
```powershell
wsl -l -v                   # (PowerShell) your distro name for -d
```
