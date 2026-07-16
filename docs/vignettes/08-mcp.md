# Using beans from Claude (MCP)

**What you'll accomplish:** connect `beans` to **Claude Desktop** and **Claude
Code** through an optional **MCP server**, so you can ask about your finances in
plain language and Claude reads the answers straight from your ledger — no
copy-paste, no API key in `beans`, nothing leaving your machine. You'll run the
one-command setup check, register the server, and use both a tool and the
`review` prompt.

**Prerequisites:** comfort with [Getting started](01-getting-started.md), and
`beans` installed in **WSL/Ubuntu**. This vignette follows the common topology
where `beans` lives in WSL while Claude Desktop runs on native Windows.

> The MCP server is **opt-in and read-only by default.** It runs on your
> machine next to the ledger and never reaches the network — Claude (the host)
> owns the model; `beans` just answers tool calls.

```sh
export BEANS_LEDGER=/tmp/mcp-demo.db
```

## 1. Install the extra

Inside WSL:

```sh
pip install "beans-ledger[mcp]"
```

The `[mcp]` extra adds **no** third-party dependency — the MCP protocol is
implemented on the Python standard library. It gives you the `beans-mcp`
command and marks the feature as opted-in.

## 2. A small ledger to explore

```sh
beans init
beans tx add --date 2026-01-01 --desc 'Opening balances' \
  --post Assets:Checking 6000 --post Assets:Savings 12000 \
  --post 'Equity:Opening Balances'
beans earn 6000 Salary --date 2026-01-15
beans spend 1800 Rent   --date 2026-01-02
beans spend 420  Dining --date 2026-01-20
```

## 3. Run the doctor

This is the highest-leverage step for the WSL/Windows boundary. It prints the
exact paths your host config needs and *actually starts the server* to confirm
nothing corrupts the protocol stream:

```sh
beans mcp doctor
```

```
beans mcp doctor — checking the MCP server setup
=======================================================

1. Entry point
    ok   beans-mcp → /home/you/.venvs/beans/bin/beans-mcp

2. Ledger
    ok   /home/you/.beans/mcp-demo.db (readable, on the Linux filesystem)

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
                        "--file", "/home/you/.beans/mcp-demo.db" ]
            }
          }
        }

5. Transport
    ok   zero-dependency stdlib JSON-RPC (no MCP SDK required)
        protocol version: 2025-06-18
```

All green — the server is ready to register.

## 4. Register the server

**Claude Code inside WSL** (recommended — no boundary to cross):

```sh
claude mcp add beans --scope user -- beans-mcp --file ~/.beans/mcp-demo.db
claude mcp list
```

**Claude Desktop on Windows:** paste the snippet the doctor printed into
`claude_desktop_config.json` (Settings → Developer → Edit Config), adjusting the
distro name from `wsl -l -v`, then restart Claude Desktop. The full walkthrough
— including the native-Windows Claude Code fallback and a troubleshooting table
keyed to the three boundary hazards — is in
[`docs/mcp-setup-wsl.md`](../mcp-setup-wsl.md).

## 5. See what the server exposes

You can inspect the tool list without a host by piping two frames through the
server (this is exactly what the doctor's check 3 automates):

```sh
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"x","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | beans-mcp --file ~/.beans/mcp-demo.db | python -m json.tool
```

The server offers read-only tools that map 1:1 onto `beans` reports:

```
beans_income_statement    beans_search           beans_networth
beans_balance_sheet       beans_register         beans_list_accounts
beans_cashflow            beans_budget_report    beans_economic_balance_sheet
beans_analyze             beans_forecast         beans_review_bundle
beans_list_transactions
```

Each returns both text and `structuredContent`, so Claude gets machine-readable
JSON identical to `beans <command> --json`.

## 6. Ask questions in the host

Once registered, just talk to Claude. It picks the right tool and reads your
actual numbers:

> **You:** How much did I spend on dining in January, and am I saving enough?
>
> **Claude** *(calls `beans_income_statement` and `beans_analyze`)*: In January
> you spent **$420.00** on dining. Your income was $6,000.00 against $2,220.00
> of expenses, a **savings rate of 63%** — comfortably healthy…

Because every figure comes from a `beans` tool call, the numbers match your
statements exactly — Claude isn't estimating.

## 7. Run the `review` prompt

The server also exposes a **`review`** prompt — the CFO-style analyst framing.
In Claude Desktop, choose the `beans` server's **review** prompt (or ask Claude
to "run the beans review"); it calls `beans_review_bundle` once to gather the
income statement, balance sheet, cash flow, ratios, budget variance, and
net-worth trend, then narrates a briefing: a headline health read, what changed,
ranked concerns, and concrete suggestions — ending with a "not licensed
financial advice" note.

## 8. Writes (optional, off by default)

By default the server is strictly read-only. If you want Claude to *record*
transactions, launch it with `--allow-writes`:

```sh
beans-mcp --file ~/.beans/mcp-demo.db --allow-writes
```

Even then, the **host** prompts you to approve each mutating call — the
confirmation lives in Claude Desktop/Code, and the money math is always done by
`beans`, never by the model. Leave it off unless you specifically want it.

## Where to go next

- [`docs/mcp-setup-wsl.md`](../mcp-setup-wsl.md) — the complete setup and
  troubleshooting guide for the WSL/Windows boundary.
- The [MANUAL's `mcp` section](../MANUAL.md#mcp--mcp-server-optional) — every
  flag, the tool list, and the privacy posture.

When you're done, just delete the scratch ledger file.
