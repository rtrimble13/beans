"""In-process execution of whitelisted tools.

Crucially we do **not** shell out to a `beans` subprocess per tool call.
Instead :meth:`Runner.run` calls ``cli.main(argv, led=..., capture=...)``
against the already-open :class:`~beans.ledger.Ledger`, capturing the JSON the
command prints. That is fast, reuses one SQLite connection, and keeps every
tool call reading exactly what ``beans <cmd> --json`` would produce.

Mutating tools are gated: before a write runs, the runner shows the exact
command line and asks for confirmation. Nothing touches the ledger unless the
user says yes.
"""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import dataclass

from beans.utils import BeansError

from . import tools as _tools


@dataclass
class ToolResult:
    name: str
    argv: list[str]
    ok: bool
    data: object = None
    error: str | None = None
    skipped: bool = False

    def to_content(self) -> str:
        """The JSON string fed back to the model as the tool result."""
        if self.skipped:
            return json.dumps({"ok": False,
                               "declined": True,
                               "note": "The user declined to run this "
                                       "command; do not retry it."})
        if not self.ok:
            return json.dumps({"ok": False, "error": self.error})
        return json.dumps({"ok": True, "result": self.data})


def _default_confirm(command: str) -> bool:
    """Interactive confirmation prompt for a write, mirroring the y/N prompts
    used elsewhere in the tool."""
    print(f"\nI'd run:  {command}")
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


class Runner:
    """Executes tool calls against one ledger, capturing their JSON."""

    def __init__(self, led, *, allow_writes: bool = False, confirm=None,
                 redact: bool = False):
        self.led = led
        self.registry = _tools.registry(allow_writes)
        self.confirm = confirm if confirm is not None else _default_confirm
        self.redact = redact
        # An auditable trace of every tool executed this session.
        self.trace: list[ToolResult] = []

    def command_line(self, name: str, arguments: dict) -> str:
        """The `beans …` command a tool call maps to, for display."""
        tool = self.registry.get(name)
        if tool is None:
            return f"beans {name}"
        argv = tool.build_argv(arguments or {})
        return "beans " + " ".join(_quote(a) for a in argv)

    def run(self, name: str, arguments: dict) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            result = ToolResult(name=name, argv=[], ok=False,
                                error=f"unknown or unavailable tool {name!r}")
            self.trace.append(result)
            return result

        argv = tool.build_argv(arguments or {})

        if tool.writes:
            command = "beans " + " ".join(_quote(a) for a in argv)
            if not self.confirm(command):
                result = ToolResult(name=name, argv=argv, ok=False,
                                    skipped=True)
                self.trace.append(result)
                return result

        result = self.run_argv(name, argv)
        self.trace.append(result)
        return result

    def run_argv(self, name: str, argv: list[str]) -> ToolResult:
        """Execute a beans `argv` in-process and capture its result. Used both
        for whitelisted tool calls and for the review bundle's fixed reports;
        does no write-confirmation, so callers gate mutating commands via
        :meth:`run`."""
        from beans import cli  # local import avoids an import cycle

        buffer = io.StringIO()
        errbuf = io.StringIO()
        try:
            # main() prints a failed command's "beans: error: …" to stderr and
            # returns 1 rather than raising; capture stderr too so that detail
            # reaches the model (to self-correct) instead of leaking onto the
            # user's terminal mid-conversation.
            with contextlib.redirect_stderr(errbuf):
                code = cli.main(argv, led=self.led, capture=buffer)
        except BeansError as exc:
            return ToolResult(name=name, argv=argv, ok=False, error=str(exc))
        except Exception as exc:  # defensive: never let a tool crash the loop
            return ToolResult(name=name, argv=argv, ok=False,
                              error=f"{type(exc).__name__}: {exc}")
        output = buffer.getvalue().strip()
        if code != 0:
            error = errbuf.getvalue().strip() or output
            # Drop the "beans: error: " prefix main() adds, for a clean message.
            error = error.replace("beans: error: ", "", 1)
            return ToolResult(name=name, argv=argv, ok=False,
                              error=error or f"command exited {code}")
        # Read-only tools emit JSON; the confirmed write shortcuts (spend,
        # earn, transfer) print a human confirmation line — keep that as-is.
        if output:
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                data = {"output": output}
        else:
            data = None
        if self.redact:
            from . import redaction
            data = redaction.scrub(data)
        return ToolResult(name=name, argv=argv, ok=True, data=data)


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg
