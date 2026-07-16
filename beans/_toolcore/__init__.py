"""Transport-agnostic tool core shared by the AI and MCP surfaces.

This package holds the pieces that are independent of *how* a caller reaches
the ledger — the read-only command whitelist (`tools`), the in-process
executor that runs those commands against an open `Ledger` and captures their
JSON (`runner`), and optional free-text redaction (`redaction`).

`beans.ai` (an in-process agent loop) and `beans.mcp` (a stdio MCP server for
external hosts like Claude Desktop / Claude Code) are two bindings over this
same core, so tool behavior stays identical across both surfaces.
"""

from __future__ import annotations

from . import redaction, runner, tools

__all__ = ["tools", "runner", "redaction"]
