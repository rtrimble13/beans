"""Optional MCP server for beans.

Exposes the ledger as read-only tools and a `review` prompt over an MCP stdio
server, so hosts like Claude Desktop and Claude Code can drive `beans`
directly. The host owns inference — there is no LLM client and no agent loop
here (that is the orthogonal `[ai]` feature). The protocol is hand-rolled on
the standard library, so the `[mcp]` extra adds no third-party dependency.

Everything is imported lazily from `cli.py`, and the server runs inside WSL
next to the ledger's SQLite file; see `docs/mcp-setup-wsl.md`.
"""
