"""The MCP server: a thin, dependency-free binding over `_toolcore`.

Speaks MCP over stdio, which is newline-delimited JSON-RPC 2.0. Each whitelisted
`_toolcore` tool becomes an MCP tool (annotated ``readOnlyHint``), a
`beans_review_bundle` tool assembles the analyst report set, and a ``review``
prompt carries the CFO-style framing. No third-party dependency: the protocol
is hand-rolled on the standard library.

The host (Claude Desktop / Claude Code) owns inference and approves each tool
call, so there is no LLM client and no agent loop here — the server just
answers tool calls against an open :class:`~beans.ledger.Ledger`.
"""

from __future__ import annotations

import difflib
import json

from beans import __version__
from beans._toolcore import tools as _tools
from beans._toolcore.bundle import assemble_review_bundle
from beans._toolcore.runner import Runner

# Protocol versions this server understands; it echoes back the client's if
# known, otherwise offers its own latest (per the MCP initialize handshake).
KNOWN_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

SERVER_INFO = {"name": "beans", "version": __version__}

# A few core tool names read better with a hand-picked MCP name.
_NAME_OVERRIDES = {"get_analysis": "beans_analyze"}

REVIEW_BUNDLE_TOOL = "beans_review_bundle"

INSTRUCTIONS = (
    "beans exposes a personal double-entry ledger as read-only reporting "
    "tools. Amounts are major-unit decimal strings in the ledger's base "
    "currency; account types follow accounting sign conventions. Prefer the "
    "most specific tool for a question, and pass period strings like 'ytd', "
    "'this-month', or '2026-Q1' straight through. For a financial-health "
    "narrative, call beans_review_bundle once and narrate the result."
)

REVIEW_PROMPT = """\
You are a seasoned personal-finance analyst — think of a CFO briefing a \
household on its own books, compiled by the `beans` ledger.

Call the `beans_review_bundle` tool{period_clause} to gather the income \
statement (with prior-period comparison), balance sheet, cash flow, ratio \
analysis, budget variance, and net-worth trend as one JSON bundle. Then write \
a briefing:
  1. A headline read on overall financial health.
  2. What changed versus the prior period, and why.
  3. 2–4 specific concerns, ranked by importance (budget overruns, thinning
     runway, rising leverage, a falling savings rate).
  4. Concrete, actionable suggestions tied to the actual numbers.

Guardrails: never invent figures — cite only numbers from the bundle; \
distinguish actuals (the ledger) from assumptions (economic/forecast inputs); \
no generic advice unmoored from the data. End with a one-line footer: \
"Not licensed financial advice."\
"""


class ProtocolError(Exception):
    """A JSON-RPC error to return to the client."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def mcp_tool_name(core_name: str) -> str:
    """Map a `_toolcore` tool name onto its `beans_`-prefixed MCP name."""
    if core_name in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[core_name]
    stem = core_name[4:] if core_name.startswith("get_") else core_name
    return f"beans_{stem}"


def _title(mcp_name: str) -> str:
    return mcp_name.removeprefix("beans_").replace("_", " ").title()


class MCPServer:
    """Dispatches MCP JSON-RPC methods against one ledger."""

    def __init__(self, led, *, allow_writes: bool = False, log=None):
        self.led = led
        self.allow_writes = allow_writes
        self.log = log or (lambda _msg: None)
        # The host approves each call before it reaches us, so the runner's own
        # confirm auto-approves — it must never read stdin (that is the
        # JSON-RPC channel). Writes are only present when allow_writes is on.
        self.runner = Runner(led, allow_writes=allow_writes,
                             confirm=lambda _cmd: True)
        self._by_mcp = {mcp_tool_name(name): tool
                        for name, tool in _tools.registry(allow_writes).items()}

    # -- dispatch ------------------------------------------------------------

    def handle(self, message) -> dict | None:
        """Handle one parsed JSON-RPC message; return a response dict, or None
        for notifications (which get no reply)."""
        if not isinstance(message, dict):
            return _error(None, -32600, "Invalid Request")
        method = message.get("method")
        mid = message.get("id")
        is_request = "id" in message and message["id"] is not None

        try:
            handler = self._METHODS.get(method)
            if handler is None:
                if not is_request:
                    return None  # unknown notification: ignore
                if method and method.startswith("notifications/"):
                    return None
                return _error(mid, -32601, f"Method not found: {method}")
            result = handler(self, message.get("params") or {})
        except ProtocolError as exc:
            self.log(f"protocol error in {method}: {exc}")
            return _error(mid, exc.code, str(exc))
        except Exception as exc:  # defensive: never crash the loop
            self.log(f"internal error in {method}: {type(exc).__name__}: {exc}")
            if not is_request:
                return None
            return _error(mid, -32603, f"Internal error: {exc}")

        if not is_request:
            return None  # a notification we recognized but need not answer
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        version = (requested if requested in KNOWN_PROTOCOL_VERSIONS
                   else DEFAULT_PROTOCOL_VERSION)
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }

    def _ping(self, _params: dict) -> dict:
        return {}

    def _noop(self, _params: dict) -> dict:
        return {}

    # -- tools ---------------------------------------------------------------

    def _list_tools(self, _params: dict) -> dict:
        tools = [self._tool_def(name, tool)
                 for name, tool in self._by_mcp.items()]
        tools.append(self._review_bundle_def())
        return {"tools": tools}

    def _tool_def(self, mcp_name: str, tool) -> dict:
        return {
            "name": mcp_name,
            "title": _title(mcp_name),
            "description": tool.description,
            "inputSchema": tool.parameters,
            "outputSchema": {
                "type": "object",
                "description": "The command's JSON result. List results are "
                               "wrapped under a 'result' key.",
            },
            "annotations": {
                "title": _title(mcp_name),
                "readOnlyHint": not tool.writes,
                "destructiveHint": bool(tool.writes),
                "idempotentHint": not tool.writes,
                "openWorldHint": False,
            },
        }

    def _review_bundle_def(self) -> dict:
        return {
            "name": REVIEW_BUNDLE_TOOL,
            "title": "Review Bundle",
            "description": ("Assemble the full analyst report set — income "
                            "statement (with prior-period comparison), balance "
                            "sheet, cash flow, ratio analysis, budget "
                            "variance, and net-worth trend — as one JSON "
                            "bundle for a financial review."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "period": {"type": "string",
                               "description": "period selector: ytd, "
                                              "this-month, 2026-Q1, YYYY-MM, …"},
                    "compare": {"type": "string",
                                "description": "also include this period's "
                                               "income statement"},
                    "focus": {"type": "string", "enum": ["economic"],
                              "description": "add the economic balance sheet"},
                },
            },
            "outputSchema": {"type": "object",
                             "description": "period + a map of statement JSON"},
            "annotations": {"title": "Review Bundle", "readOnlyHint": True,
                            "destructiveHint": False, "idempotentHint": True,
                            "openWorldHint": False},
        }

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ProtocolError(-32602, "arguments must be an object")

        if name == REVIEW_BUNDLE_TOOL:
            bundle = assemble_review_bundle(
                self.runner, period=arguments.get("period"),
                compare=arguments.get("compare"), focus=arguments.get("focus"))
            return _ok_result(bundle)

        tool = self._by_mcp.get(name)
        if tool is None:
            return _tool_error(f"Unknown tool {name!r}.")

        result = self.runner.run(tool.name, arguments)
        if not result.ok:
            return _tool_error(self._augment_error(result.error, arguments))
        return _ok_result(result.data)

    def _augment_error(self, error: str | None, arguments: dict) -> str:
        """Make a failed lookup actionable: on a bad account name, suggest the
        closest real accounts so the model can self-correct."""
        msg = error or "the command failed"
        account = arguments.get("account")
        if account and "account" in msg.lower():
            names = [a.name for a in self.led.accounts(include_closed=True)]
            # Match on leaf names too (the CLI's own fuzzy match keys on the
            # leaf), then report the full account paths.
            leaves = {}
            for name in names:
                leaves.setdefault(name.rsplit(":", 1)[-1], name)
            pool = names + list(leaves)
            suggestions: list[str] = []
            for hit in difflib.get_close_matches(str(account), pool, n=6,
                                                 cutoff=0.5):
                full = hit if ":" in hit else leaves.get(hit, hit)
                if full not in suggestions:
                    suggestions.append(full)
            if suggestions:
                msg += " Did you mean: " + ", ".join(suggestions[:3]) + "?"
        return msg

    # -- prompts -------------------------------------------------------------

    def _list_prompts(self, _params: dict) -> dict:
        return {"prompts": [{
            "name": "review",
            "title": "Financial review",
            "description": "A CFO-style narrative review of your finances: "
                           "health read, what changed, ranked concerns, and "
                           "actionable suggestions.",
            "arguments": [{"name": "period", "required": False,
                           "description": "period to review (e.g. ytd, "
                                          "2026-Q1); defaults to the tool's "
                                          "own default"}],
        }]}

    def _get_prompt(self, params: dict) -> dict:
        name = params.get("name")
        if name != "review":
            raise ProtocolError(-32602, f"Unknown prompt {name!r}")
        period = (params.get("arguments") or {}).get("period")
        clause = f" for the period '{period}'" if period else ""
        text = REVIEW_PROMPT.format(period_clause=clause)
        return {
            "description": "Financial review",
            "messages": [{"role": "user",
                          "content": {"type": "text", "text": text}}],
        }

    _METHODS = {
        "initialize": _initialize,
        "notifications/initialized": _noop,
        "ping": _ping,
        "tools/list": _list_tools,
        "tools/call": _call_tool,
        "prompts/list": _list_prompts,
        "prompts/get": _get_prompt,
        "resources/list": lambda self, _p: {"resources": []},
        "resources/templates/list": lambda self, _p: {"resourceTemplates": []},
    }


def serve(server: MCPServer, instream, outstream) -> None:
    """Run the stdio loop: read newline-delimited JSON-RPC from ``instream``,
    dispatch, and write responses (also newline-delimited) to ``outstream``.
    Only JSON-RPC frames are ever written here — all logging goes to stderr —
    so the stream stays clean across the Windows/WSL boundary."""
    for line in instream:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(outstream, _error(None, -32700, "Parse error"))
            continue
        response = server.handle(message)
        if response is not None:
            _write(outstream, response)


def _write(outstream, obj: dict) -> None:
    outstream.write(json.dumps(obj) + "\n")
    outstream.flush()


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": code, "message": message}}


def _ok_result(data) -> dict:
    structured = data if isinstance(data, dict) else {"result": data}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}],
            "structuredContent": structured}


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}
