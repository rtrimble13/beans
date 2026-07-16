"""Tests for the optional MCP server.

Everything here is offline: the server is driven either through its in-process
`serve` loop with string streams, or as a real subprocess over a pipe. No
network, no host, no MCP SDK. The Windows/WSL boundary itself can't be
exercised in CI, so that smoke test is marked `boundary` and skipped.
"""

import io
import json
import subprocess
import sys
from datetime import date

import pytest

from beans import cli
from beans.ledger import Ledger
from beans.models import Posting
from beans.mcp.server import MCPServer, mcp_tool_name, serve
from beans.mcp import doctor
from beans.mcp.__main__ import run_server


# -- fixtures ----------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "mcp.db", create=True)
    led.initialize(currency="USD")
    _seed(led)
    yield led
    led.close()


def _seed(led):
    def acct(name):
        return led.find_account(name).id

    led.add_transaction(
        date(2026, 1, 5), "Paycheck",
        [Posting(account_id=acct("Assets:Checking"), amount=400000),
         Posting(account_id=acct("Income:Salary"), amount=-400000)])
    led.add_transaction(
        date(2026, 1, 12), "Dinner",
        [Posting(account_id=acct("Expenses:Food:Dining"), amount=5000),
         Posting(account_id=acct("Assets:Checking"), amount=-5000)],
        payee="Trattoria")


def drive(server, *frames):
    """Feed JSON-RPC frames through the stdio serve loop; return responses."""
    instream = io.StringIO("\n".join(json.dumps(f) for f in frames) + "\n")
    out = io.StringIO()
    serve(server, instream, out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line]


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}}


def _call(name, arguments=None, mid=9):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


# -- handshake ---------------------------------------------------------------


def test_initialize_negotiates(ledger):
    [resp] = drive(MCPServer(ledger), INIT)
    result = resp["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert "tools" in result["capabilities"]
    assert "prompts" in result["capabilities"]
    assert result["serverInfo"]["name"] == "beans"


def test_initialize_falls_back_on_unknown_version(ledger):
    frame = dict(INIT)
    frame["params"] = {**INIT["params"], "protocolVersion": "1999-01-01"}
    [resp] = drive(MCPServer(ledger), frame)
    assert resp["result"]["protocolVersion"] == "2025-06-18"


def test_notification_gets_no_response(ledger):
    resps = drive(MCPServer(ledger),
                  {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resps == []


def test_unknown_method_errors(ledger):
    [resp] = drive(MCPServer(ledger),
                   {"jsonrpc": "2.0", "id": 5, "method": "no/such"})
    assert resp["error"]["code"] == -32601


# -- tools -------------------------------------------------------------------


def test_tools_list_annotations(ledger):
    [resp] = drive(MCPServer(ledger),
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = {t["name"]: t for t in resp["result"]["tools"]}
    assert "beans_income_statement" in tools
    assert "beans_review_bundle" in tools
    inc = tools["beans_income_statement"]
    assert inc["annotations"]["readOnlyHint"] is True
    assert inc["annotations"]["openWorldHint"] is False
    assert inc["inputSchema"]["type"] == "object"
    assert "outputSchema" in inc


def test_write_tools_absent_by_default(ledger):
    [resp] = drive(MCPServer(ledger),
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert not any(n.startswith("beans_record_") for n in names)


def test_write_tools_present_with_allow_writes(ledger):
    server = MCPServer(ledger, allow_writes=True)
    [resp] = drive(server,
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "beans_record_expense" in names
    rec = next(t for t in resp["result"]["tools"]
               if t["name"] == "beans_record_expense")
    assert rec["annotations"]["readOnlyHint"] is False
    assert rec["annotations"]["destructiveHint"] is True


def test_tool_call_matches_cli_json(ledger):
    [resp] = drive(MCPServer(ledger),
                   _call("beans_income_statement", {"period": "2026"}))
    result = resp["result"]
    assert result.get("isError") is not True
    assert "structuredContent" in result

    buf = io.StringIO()
    cli.main(["report", "income", "--json", "--period", "2026"],
             led=ledger, capture=buf)
    assert result["structuredContent"] == json.loads(buf.getvalue())


def test_list_tool_wraps_array_result(ledger):
    # tx list returns a JSON array; structuredContent must be an object.
    [resp] = drive(MCPServer(ledger), _call("beans_list_transactions", {}))
    result = resp["result"]
    assert isinstance(result["structuredContent"], dict)
    assert isinstance(result["structuredContent"]["result"], list)


def test_bad_account_suggests_matches(ledger):
    [resp] = drive(MCPServer(ledger),
                   _call("beans_register", {"account": "Groceries-typo"}))
    result = resp["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "Did you mean" in text
    assert "Expenses:Food:Groceries" in text


def test_review_bundle_tool(ledger):
    [resp] = drive(MCPServer(ledger), _call("beans_review_bundle", {}))
    bundle = resp["result"]["structuredContent"]
    assert bundle["statements"]["income_statement"]["report"] \
        == "income_statement"
    assert "net_worth" in bundle["statements"]


def test_unknown_tool_is_tool_error(ledger):
    [resp] = drive(MCPServer(ledger), _call("beans_nonsense", {}))
    assert resp["result"]["isError"] is True


def test_server_survives_argparse_exit(ledger):
    # A tool argument that trips argparse (which raises SystemExit) must not
    # tear down the stdio loop: a later request in the same session must still
    # get a response.
    resps = drive(
        MCPServer(ledger),
        _call("beans_search", {"query": "-tax-"}, mid=8),
        _call("beans_income_statement", {"period": "2026"}, mid=9),
    )
    by_id = {r["id"]: r for r in resps}
    assert by_id[8]["result"]["isError"] is True     # reported, not crashed
    assert by_id[9]["result"].get("isError") is not True  # loop survived
    assert "structuredContent" in by_id[9]["result"]


# -- prompts -----------------------------------------------------------------


def test_prompts_list_and_get(ledger):
    server = MCPServer(ledger)
    [lst] = drive(server,
                  {"jsonrpc": "2.0", "id": 3, "method": "prompts/list"})
    assert lst["result"]["prompts"][0]["name"] == "review"

    [got] = drive(server, {"jsonrpc": "2.0", "id": 4, "method": "prompts/get",
                           "params": {"name": "review",
                                      "arguments": {"period": "2026-Q1"}}})
    text = got["result"]["messages"][0]["content"]["text"]
    assert "beans_review_bundle" in text
    assert "2026-Q1" in text


def test_prompts_get_unknown_errors(ledger):
    [resp] = drive(MCPServer(ledger),
                   {"jsonrpc": "2.0", "id": 4, "method": "prompts/get",
                    "params": {"name": "nope"}})
    assert resp["error"]["code"] == -32602


# -- name mapping ------------------------------------------------------------


def test_mcp_tool_name_mapping():
    assert mcp_tool_name("get_income_statement") == "beans_income_statement"
    assert mcp_tool_name("list_transactions") == "beans_list_transactions"
    assert mcp_tool_name("search") == "beans_search"
    assert mcp_tool_name("get_analysis") == "beans_analyze"


# -- entry point guards ------------------------------------------------------


def test_run_server_rejects_mnt_path(capsys):
    code = run_server(file="/mnt/c/Users/me/ledger.db")
    assert code == 2
    assert "/mnt" in capsys.readouterr().err


def test_run_server_missing_ledger(tmp_path, capsys):
    code = run_server(file=str(tmp_path / "nope.db"))
    assert code == 2
    assert "no ledger" in capsys.readouterr().err


# -- doctor ------------------------------------------------------------------


def test_doctor_passes_on_good_ledger(tmp_path, capsys):
    db = tmp_path / "led.db"
    cli.main(["--file", str(db), "init"])
    capsys.readouterr()
    code = doctor.run_doctor(file=str(db))
    out = capsys.readouterr().out
    assert code == 0
    assert "All checks passed" in out
    assert "stdout cleanliness" in out


def test_doctor_flags_mnt(capsys):
    code = doctor.run_doctor(file="/mnt/c/ledger.db")
    out = capsys.readouterr().out
    assert code == 1
    assert "Windows mount" in out


# -- stdout-cleanliness regression (subprocess) ------------------------------


def test_subprocess_stdout_is_pure_jsonrpc(tmp_path):
    """Guards Hazard 1 permanently: spawn the entry point and assert every
    stdout line is a JSON-RPC frame (no banners, prints, or warnings)."""
    db = tmp_path / "led.db"
    cli.main(["--file", str(db), "init"])
    frames = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18",
                               "capabilities": {},
                               "clientInfo": {"name": "t", "version": "0"}}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n")
    proc = subprocess.run(
        [sys.executable, "-m", "beans.mcp", "--file", str(db)],
        input=frames, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, "server produced no output"
    ids = []
    for line in lines:
        obj = json.loads(line)  # raises if any line is not JSON
        assert obj["jsonrpc"] == "2.0"
        ids.append(obj.get("id"))
    assert 1 in ids and 2 in ids


@pytest.mark.boundary
def test_wsl_boundary_smoke():  # pragma: no cover
    """Placeholder for the manual Windows→WSL smoke test; see
    docs/mcp-setup-wsl.md. Skipped by default (needs a real boundary)."""
    pytest.skip("manual boundary test; run with -m boundary on Windows+WSL")
