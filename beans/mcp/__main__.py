"""Entry point for the `beans-mcp` console script.

Builds the server, opens the ledger, and runs the stdio loop. All diagnostics
go to **stderr** so stdout carries only JSON-RPC frames (Hazard 1). The ledger
path is taken explicitly from ``--file`` (Hazard 2) and rejected if it lives
under a Windows mount (Hazard 3).
"""

from __future__ import annotations

import argparse
import logging
import sys

from beans import __version__
from beans.ledger import Ledger, ledger_path
from beans.utils import BeansError

from .server import MCPServer, serve


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beans-mcp",
        description="MCP stdio server exposing the beans ledger as tools.",
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--file", "-f", metavar="PATH",
        help="ledger file (a Linux path; default: $BEANS_LEDGER or "
             "~/.beans/ledger.db). Keep it on the Linux filesystem, not "
             "under /mnt/.")
    writes = parser.add_mutually_exclusive_group()
    writes.add_argument("--allow-writes", action="store_true",
                        help="enable mutating tools (default: off). Even so, "
                             "the host approves each call.")
    writes.add_argument("--read-only", dest="allow_writes",
                        action="store_false",
                        help="read-only (the default; for clarity in configs)")
    parser.set_defaults(allow_writes=False)
    parser.add_argument("--log-level", default="warning",
                        choices=["debug", "info", "warning", "error"],
                        help="stderr log verbosity (default: warning)")
    return parser


def run_server(*, file: str | None = None, allow_writes: bool = False,
               log_level: str = "warning") -> int:
    """Open the ledger and serve MCP over stdin/stdout. Returns an exit code;
    only returns when stdin closes."""
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, log_level.upper(), logging.WARNING),
        format="beans-mcp: %(levelname)s: %(message)s",
    )
    log = logging.getLogger("beans.mcp")

    path = ledger_path(file)
    if _under_windows_mount(path):
        print(f"beans-mcp: error: ledger path {path} is on a Windows mount "
              "(/mnt). SQLite locking over /mnt is slow and unreliable — keep "
              "the ledger on the Linux filesystem, e.g. ~/.beans/ledger.db.",
              file=sys.stderr)
        return 2
    if not path.exists():
        print(f"beans-mcp: error: no ledger at {path} — run `beans init` "
              "first, or pass --file with a Linux path.", file=sys.stderr)
        return 2

    try:
        led = Ledger(path)
    except BeansError as exc:
        print(f"beans-mcp: error: {exc}", file=sys.stderr)
        return 2

    mode = "read-write" if allow_writes else "read-only"
    log.info("serving %s over stdio (%s)", path, mode)
    server = MCPServer(led, allow_writes=allow_writes,
                       log=lambda m: log.warning("%s", m))
    try:
        serve(server, sys.stdin, sys.stdout)
    except KeyboardInterrupt:
        pass
    finally:
        led.close()
    return 0


def _under_windows_mount(path) -> bool:
    # /mnt/c, /mnt/d, … are the WSL DrvFs mounts of Windows drives.
    return str(path).startswith("/mnt/")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_server(file=args.file, allow_writes=args.allow_writes,
                      log_level=args.log_level)


if __name__ == "__main__":
    sys.exit(main())
