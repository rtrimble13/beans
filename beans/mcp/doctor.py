"""`beans mcp doctor` — a boundary self-check for the WSL/Desktop topology.

Turns the usual opaque "server disconnected" failure into specific, fixable
messages. Run inside WSL. This is a human-facing command, so it prints to
stdout normally — it is never mixed into a live protocol stream.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

from beans.ledger import Ledger, ledger_path
from .server import DEFAULT_PROTOCOL_VERSION

CHECK = "  [check]"
OK = "    ok  "
WARN = "   warn "
FAIL = "   FAIL "


def run_doctor(file: str | None = None, out=None) -> int:
    """Run all checks; return 0 if none failed, 1 otherwise."""
    out = out or sys.stdout
    failures = 0
    warnings = 0

    def emit(line=""):
        print(line, file=out)

    emit("beans mcp doctor — checking the MCP server setup")
    emit("=" * 55)

    # 1. Entry point resolves.
    emit("\n1. Entry point")
    entry = shutil.which("beans-mcp")
    if entry:
        emit(f"{OK} beans-mcp → {entry}")
    else:
        warnings += 1
        entry = f"{sys.executable} -m beans.mcp"
        emit(f"{WARN} `beans-mcp` not on PATH. Install the extra "
             "(`pip install \"beans-ledger[mcp]\"`) so the console script")
        emit(f"        exists, or use: {entry}")

    # 2. Ledger reachable and on the Linux filesystem.
    emit("\n2. Ledger")
    path = ledger_path(file)
    if str(path).startswith("/mnt/"):
        failures += 1
        emit(f"{FAIL} {path} is on a Windows mount (/mnt). SQLite locking "
             "there is slow and unreliable —")
        emit("        move the ledger to the Linux filesystem, e.g. "
             "~/.beans/ledger.db.")
    elif not path.exists():
        warnings += 1
        emit(f"{WARN} no ledger at {path} yet — run `beans init` "
             "(or pass --file).")
    elif not os.access(path, os.R_OK):
        failures += 1
        emit(f"{FAIL} ledger at {path} is not readable.")
    else:
        emit(f"{OK} {path} (readable, on the Linux filesystem)")

    # 3. stdout cleanliness — spawn the real entry point and assert only
    #    JSON-RPC comes back (catches MOTD/profile/import-time leakage).
    emit("\n3. stdout cleanliness")
    clean, detail, proto = _check_stdout_clean(file, path)
    if clean:
        emit(f"{OK} only JSON-RPC on stdout (initialize + tools/list)")
    else:
        failures += 1
        emit(f"{FAIL} stdout is contaminated — a host would see a broken "
             "stream.")
        for line in detail.splitlines():
            emit(f"        {line}")

    # 4. Distro hint + ready-to-paste config.
    emit("\n4. Claude Desktop config (Windows side)")
    emit("        Find your distro name in PowerShell: wsl -l -v")
    emit("        Paste this into claude_desktop_config.json (adjust distro):")
    emit(_config_snippet(entry, path))

    # 5. Transport/version.
    emit("\n5. Transport")
    emit(f"{OK} zero-dependency stdlib JSON-RPC (no MCP SDK required)")
    emit(f"        protocol version: {proto or DEFAULT_PROTOCOL_VERSION}")

    emit("\n" + "=" * 55)
    if failures:
        emit(f"{failures} check(s) FAILED, {warnings} warning(s). "
             "Fix the failures above before registering the server.")
        return 1
    emit(f"All checks passed{f' ({warnings} warning(s))' if warnings else ''}. "
         "The server is ready to register.")
    return 0


def _check_stdout_clean(file, path):
    """Spawn the entry point, exchange initialize + tools/list, and verify
    stdout contains only well-formed JSON-RPC frames. Returns
    (clean, detail, negotiated_protocol)."""
    tmp = None
    ledger_arg = file
    try:
        if not path.exists() or str(path).startswith("/mnt/"):
            # No usable ledger; make a throwaway one so the server can start.
            tmp = tempfile.mkdtemp(prefix="beans-mcp-doctor-")
            db = os.path.join(tmp, "ledger.db")
            led = Ledger(db, create=True)
            led.initialize(currency="USD")
            led.close()
            ledger_arg = db

        cmd = _entry_cmd(ledger_arg)
        frames = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": DEFAULT_PROTOCOL_VERSION,
                                   "capabilities": {},
                                   "clientInfo": {"name": "doctor",
                                                  "version": "0"}}}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "method":
                          "notifications/initialized"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2,
                          "method": "tools/list", "params": {}}) + "\n"
        )
        proc = subprocess.run(cmd, input=frames, capture_output=True,
                              text=True, timeout=30)
        proto = None
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                return (False,
                        f"non-JSON line on stdout:\n{line[:200]}", None)
            if obj.get("jsonrpc") != "2.0":
                return (False, f"not a JSON-RPC frame:\n{line[:200]}", None)
            result = obj.get("result") or {}
            if "protocolVersion" in result:
                proto = result["protocolVersion"]
        if proc.returncode not in (0, None):
            # A non-zero exit with clean stdout usually means a startup error
            # printed to stderr (e.g. /mnt guard); surface it.
            return (bool(proto), (proc.stderr.strip()
                                  or "server exited non-zero"), proto)
        return (True, "", proto)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _entry_cmd(ledger_arg):
    entry = shutil.which("beans-mcp")
    base = [entry] if entry else [sys.executable, "-m", "beans.mcp"]
    if ledger_arg:
        base += ["--file", str(ledger_arg)]
    return base


def _config_snippet(entry, path):
    exe = entry if entry and not entry.startswith(sys.executable) else \
        "/home/you/.venvs/beans/bin/beans-mcp"
    snippet = {
        "mcpServers": {
            "beans": {
                "command": "wsl.exe",
                "args": ["-d", "Ubuntu", "--", exe, "--file", str(path)],
            }
        }
    }
    return "\n".join("        " + line
                     for line in json.dumps(snippet, indent=2).splitlines())
