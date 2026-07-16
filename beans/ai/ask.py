"""`beans ai ask` — the natural-language command layer.

An agent loop: the model plans, requests whitelisted read-only `beans`
commands, reads their JSON, and answers. Writes, when enabled, are proposed as
exact command lines and confirmed before they run. All figures come from the
existing tested JSON paths, so answers can't drift from what `beans report`
would show — and ``--explain`` makes that auditable.
"""

from __future__ import annotations

import sys

from . import prompts, tools as _tools
from .runner import Runner


def _print_trace(runner: Runner, out) -> None:
    """Show the commands the agent ran and the JSON they returned."""
    if not runner.trace:
        print("(no commands were run)", file=out)
        return
    print("\n── commands run ──────────────────────────────────────────────",
          file=out)
    for res in runner.trace:
        command = "beans " + " ".join(_quote(a) for a in res.argv)
        print(f"\n$ {command}", file=out)
        if res.skipped:
            print("  (declined by user)", file=out)
        elif res.ok:
            print(_indent(res.to_content()), file=out)
        else:
            print(f"  error: {res.error}", file=out)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def dry_run(question: str, cfg, allow_writes: bool, out=None) -> int:
    """Print what *would* be sent without contacting the provider."""
    from . import data_flow_line
    out = out or sys.stdout
    print("── beans ai ask — dry run (no request sent) ──────────────────",
          file=out)
    print(data_flow_line(cfg), file=out)
    print(f"\nQuestion:\n  {question}", file=out)
    print("\nTools the assistant could call (read-only"
          + (" + writes, each confirmed" if allow_writes else "") + "):",
          file=out)
    for tool in _tools.registry(allow_writes).values():
        marker = "  [write]" if tool.writes else ""
        print(f"  • {tool.name}{marker} — {tool.description}", file=out)
    print("\nNothing was sent. Re-run without --dry-run to ask for real.",
          file=out)
    return 0


def run_ask(led, question: str, *, client, cfg, allow_writes: bool = False,
            explain: bool = False, confirm=None, out=None,
            _messages: list | None = None) -> int:
    """Run one question through the agent loop and print the answer.

    ``_messages`` lets the REPL carry conversation context across turns.
    Returns a process exit code.
    """
    out = out or sys.stdout
    runner = Runner(led, allow_writes=allow_writes, confirm=confirm,
                    redact=cfg.redact)
    definitions = _tools.definitions(allow_writes)
    messages = _messages if _messages is not None else []
    messages.append({"role": "user", "content": question})

    answered = False
    for _ in range(cfg.max_iterations):
        resp = client.complete(messages, tools=definitions,
                               system=prompts.ASK_SYSTEM)
        if resp.wants_tools:
            messages.append({
                "role": "assistant",
                "content": resp.text,
                "tool_calls": [{"id": tc.id, "name": tc.name,
                                "arguments": tc.arguments}
                               for tc in resp.tool_calls],
            })
            for tc in resp.tool_calls:
                result = runner.run(tc.name, tc.arguments)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "name": tc.name,
                                 "content": result.to_content()})
            continue
        # A final answer.
        messages.append({"role": "assistant", "content": resp.text or ""})
        print((resp.text or "").strip(), file=out)
        answered = True
        break

    if not answered:
        print(f"(stopped after {cfg.max_iterations} steps without a final "
              "answer — try a more specific question)", file=out)

    if explain:
        _print_trace(runner, out)
    return 0


def run_repl(led, *, client, cfg, allow_writes: bool = False,
             explain: bool = False, confirm=None, out=None,
             input_fn=input) -> int:
    """Interactive question loop that keeps context across turns."""
    out = out or sys.stdout
    messages: list = []
    print("beans ai — interactive. Ask a question, or 'exit' to quit.",
          file=out)
    while True:
        try:
            line = input_fn("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            break
        if not line:
            continue
        if line.lower() in ("exit", "quit", ":q"):
            break
        run_ask(led, line, client=client, cfg=cfg, allow_writes=allow_writes,
                explain=explain, confirm=confirm, out=out,
                _messages=messages)
    return 0
