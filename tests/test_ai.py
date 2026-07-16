"""Tests for the optional AI assistant.

Everything here is offline: a scripted mock client stands in for a real
provider, so the agent loop, the in-process tool runner, write-gating, and the
review bundle are all exercised deterministically with no network and no key.
The one real-provider smoke test is marked `live` and skipped by default.
"""

import io
import json
from datetime import date

import pytest

from beans import cli
from beans.ai import config as ai_config
from beans.ai import ask as ai_ask
from beans.ai import redaction, review as ai_review
from beans.ai.client import Response, ToolCall
from beans.ai.runner import Runner
from beans.ledger import Ledger
from beans.models import Posting


# -- fixtures ----------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "ai.db", create=True)
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
        date(2026, 1, 12), "Dinner out",
        [Posting(account_id=acct("Expenses:Food:Dining"), amount=5000,
                 ),
         Posting(account_id=acct("Assets:Checking"), amount=-5000)],
        payee="Trattoria")
    led.add_transaction(
        date(2026, 2, 3), "Groceries",
        [Posting(account_id=acct("Expenses:Food:Groceries"), amount=12000),
         Posting(account_id=acct("Assets:Checking"), amount=-12000)],
        payee="Whole Foods")


class MockClient:
    """Returns scripted responses in order; records the messages it saw."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete(self, messages, tools=None, system=None):
        # Copy so later mutation of the shared history doesn't rewrite history.
        self.calls.append([dict(m) for m in messages])
        return self._responses.pop(0)


# -- config ------------------------------------------------------------------


def test_config_defaults(ledger, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BEANS_AI_KEY", raising=False)
    cfg = ai_config.resolve(None, ledger)
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-sonnet-5"
    assert not cfg.configured


def test_config_precedence_flag_over_meta_over_env(ledger, monkeypatch):
    ledger.set_meta("ai.provider", "openai")
    ledger.set_meta("ai.model", "meta-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class Args:
        provider = None
        model = None
        base_url = None
        dry_run = False

    cfg = ai_config.resolve(Args(), ledger)
    assert cfg.provider == "openai"          # from meta
    assert cfg.model == "meta-model"         # from meta
    assert cfg.api_key == "sk-test"          # from env
    assert cfg.key_source == "OPENAI_API_KEY"

    Args.model = "flag-model"
    cfg = ai_config.resolve(Args(), ledger)
    assert cfg.model == "flag-model"         # flag wins


def test_config_local_needs_no_key(ledger, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BEANS_AI_KEY", raising=False)
    ledger.set_meta("ai.provider", "openai")
    ledger.set_meta("ai.base_url", "http://localhost:11434/v1")
    cfg = ai_config.resolve(None, ledger)
    assert cfg.is_local
    assert cfg.configured                    # local model needs no key


# -- capture/led refactor ----------------------------------------------------


def test_main_capture_reuses_ledger(ledger):
    buf = io.StringIO()
    code = cli.main(["analyze", "--json"], led=ledger, capture=buf)
    assert code == 0
    data = json.loads(buf.getvalue())
    assert data["report"] == "analysis"
    # The caller-supplied ledger stays open for reuse.
    assert ledger.db is not None
    assert ledger.get_meta("currency") == "USD"


# -- runner / tools ----------------------------------------------------------


def test_runner_matches_direct_json(ledger):
    runner = Runner(ledger)
    result = runner.run("get_income_statement", {"period": "2026"})
    assert result.ok

    buf = io.StringIO()
    cli.main(["report", "income", "--json", "--period", "2026"],
             led=ledger, capture=buf)
    assert result.data == json.loads(buf.getvalue())


def test_runner_builds_expected_argv(ledger):
    runner = Runner(ledger, allow_writes=True)
    line = runner.command_line(
        "record_expense",
        {"amount": "12.50", "category": "Dining Out", "source": "Checking"})
    assert line == 'beans spend 12.50 "Dining Out" --from Checking'


def test_runner_unknown_tool(ledger):
    runner = Runner(ledger)
    result = runner.run("record_expense", {"amount": "1", "category": "X"})
    assert not result.ok  # write tool absent without allow_writes


def test_runner_captures_error_detail(ledger, capsys):
    # A failing command's real error must reach the model (not a generic
    # "exited 1") and must NOT leak onto the user's stderr mid-conversation.
    runner = Runner(ledger)
    result = runner.run("get_register", {"account": "NoSuchAccount"})
    assert not result.ok
    assert "NoSuchAccount" in result.error
    assert "beans: error:" not in result.error   # prefix stripped
    captured = capsys.readouterr()
    assert "NoSuchAccount" not in captured.err    # nothing leaked to stderr


def test_runner_malformed_tool_call(ledger):
    # A call missing a required argument must not crash the loop.
    runner = Runner(ledger)
    result = runner.run("search", {})          # required "query" omitted
    assert not result.ok
    assert "invalid arguments" in result.error
    assert "declined" not in result.to_content()


def test_ask_survives_malformed_then_recovers(ledger):
    # The agent emits a bad call, gets the error, then a good one and answers.
    client = MockClient([
        Response(tool_calls=[ToolCall("t1", "get_register", {})],  # no account
                 stop_reason="tool_use"),
        Response(tool_calls=[ToolCall("t2", "get_analysis", {})],
                 stop_reason="tool_use"),
        Response(text="Here's your summary.", stop_reason="end_turn"),
    ])
    out = io.StringIO()
    code = ai_ask.run_ask(ledger, "how am I doing?", client=client,
                          cfg=ai_config.resolve(None, ledger), out=out)
    assert code == 0
    assert "Here's your summary." in out.getvalue()
    # The model saw the invalid-arguments error for the first call.
    assert any("invalid arguments" in m.get("content", "")
               for m in client.calls[1] if m["role"] == "tool")


def test_search_tool_roundtrip(ledger):
    runner = Runner(ledger)
    result = runner.run("search", {"query": "Whole Foods"})
    assert result.ok
    assert any("Groceries" in p["account"]
               for txn in result.data for p in txn["postings"])


# -- ask agent loop ----------------------------------------------------------


def test_ask_agent_loop(ledger):
    client = MockClient([
        Response(text="Let me check.",
                 tool_calls=[ToolCall("t1", "get_analysis", {})],
                 stop_reason="tool_use"),
        Response(text="Your savings rate is healthy.",
                 stop_reason="end_turn"),
    ])
    out = io.StringIO()
    code = ai_ask.run_ask(ledger, "how am I doing?", client=client,
                          cfg=ai_config.resolve(None, ledger), out=out)
    assert code == 0
    assert "savings rate is healthy" in out.getvalue()
    # Second model call must have received the tool result.
    second = client.calls[1]
    assert any(m["role"] == "tool" and m["name"] == "get_analysis"
               for m in second)


def test_ask_explain_trace(ledger):
    client = MockClient([
        Response(tool_calls=[ToolCall("t1", "list_accounts", {})],
                 stop_reason="tool_use"),
        Response(text="Done.", stop_reason="end_turn"),
    ])
    out = io.StringIO()
    ai_ask.run_ask(ledger, "list accounts", client=client,
                   cfg=ai_config.resolve(None, ledger), explain=True, out=out)
    text = out.getvalue()
    assert "commands run" in text
    assert "beans account list --json" in text


def test_ask_write_gating_confirm_yes(ledger):
    client = MockClient([
        Response(tool_calls=[ToolCall(
            "w1", "record_expense",
            {"amount": "25", "category": "Expenses:Food:Dining"})],
            stop_reason="tool_use"),
        Response(text="Recorded.", stop_reason="end_turn"),
    ])
    before = len(ledger.transactions())
    ai_ask.run_ask(ledger, "spend 25 on dining", client=client,
                   cfg=ai_config.resolve(None, ledger), allow_writes=True,
                   confirm=lambda cmd: True, out=io.StringIO())
    assert len(ledger.transactions()) == before + 1


def test_ask_write_gating_confirm_no(ledger):
    client = MockClient([
        Response(tool_calls=[ToolCall(
            "w1", "record_expense",
            {"amount": "25", "category": "Expenses:Food:Dining"})],
            stop_reason="tool_use"),
        Response(text="Okay, skipped.", stop_reason="end_turn"),
    ])
    before = len(ledger.transactions())
    ai_ask.run_ask(ledger, "spend 25 on dining", client=client,
                   cfg=ai_config.resolve(None, ledger), allow_writes=True,
                   confirm=lambda cmd: False, out=io.StringIO())
    assert len(ledger.transactions()) == before   # nothing written
    # The model was told the user declined.
    assert any(m["role"] == "tool" and "declined" in m["content"]
               for m in client.calls[1])


def test_ask_iteration_cap(ledger):
    # A model that always asks for another tool must be bounded.
    responses = [Response(tool_calls=[ToolCall(f"t{i}", "get_analysis", {})],
                          stop_reason="tool_use") for i in range(20)]
    client = MockClient(responses)
    cfg = ai_config.resolve(None, ledger)
    cfg.max_iterations = 3
    out = io.StringIO()
    ai_ask.run_ask(ledger, "loop forever", client=client, cfg=cfg, out=out)
    assert "stopped after 3 steps" in out.getvalue()
    assert len(client.calls) == 3


def test_ask_dry_run_sends_nothing(ledger):
    cfg = ai_config.resolve(None, ledger)
    out = io.StringIO()
    ai_ask.dry_run("what's my net worth?", cfg, allow_writes=False, out=out)
    text = out.getvalue()
    assert "Nothing was sent" in text
    assert "get_networth" in text


# -- review ------------------------------------------------------------------


def test_review_bundle_assembles_reports(ledger):
    bundle = ai_review.assemble_bundle(ledger, period="2026")
    stmts = bundle["statements"]
    assert stmts["income_statement"]["report"] == "income_statement"
    assert stmts["balance_sheet"]["report"] == "balance_sheet"
    assert "net_worth" in stmts


def test_ask_tool_results_honor_redaction(ledger):
    # list_transactions returns payees; with redaction on, the JSON fed back
    # to the model must have them scrubbed while amounts survive.
    cfg = ai_config.resolve(None, ledger)
    cfg.redact = True
    client = MockClient([
        Response(tool_calls=[ToolCall("t1", "list_transactions", {})],
                 stop_reason="tool_use"),
        Response(text="done", stop_reason="end_turn"),
    ])
    ai_ask.run_ask(ledger, "list my transactions", client=client, cfg=cfg,
                   out=io.StringIO())
    tool_msg = next(m for m in client.calls[1] if m["role"] == "tool")
    assert "Whole Foods" not in tool_msg["content"]   # payee scrubbed
    assert "[redacted:" in tool_msg["content"]
    assert "120.00" in tool_msg["content"]            # amount survives


def test_review_prose(ledger):
    client = MockClient([Response(text="You are doing fine.\n"
                                       "Not licensed financial advice.")])
    out = io.StringIO()
    ai_review.run_review(ledger, client=client,
                         cfg=ai_config.resolve(None, ledger), out=out)
    assert "doing fine" in out.getvalue()


def test_review_structured_json(ledger):
    findings = {
        "period": "2026", "health": "stable", "headline": "Solid.",
        "changes": [], "concerns": [], "suggestions": ["Keep saving."],
    }
    client = MockClient([Response(text=json.dumps(findings))])
    out = io.StringIO()
    ai_review.run_review(ledger, client=client,
                         cfg=ai_config.resolve(None, ledger),
                         structured=True, out=out)
    assert json.loads(out.getvalue())["health"] == "stable"


def test_review_structured_strips_code_fence(ledger):
    findings = {"period": "2026", "health": "strong", "headline": "ok",
                "changes": [], "concerns": [], "suggestions": []}
    client = MockClient([Response(
        text="```json\n" + json.dumps(findings) + "\n```")])
    out = io.StringIO()
    ai_review.run_review(ledger, client=client,
                         cfg=ai_config.resolve(None, ledger),
                         structured=True, out=out)
    assert json.loads(out.getvalue())["health"] == "strong"


def test_review_fabrication_warning(ledger, capsys):
    findings = {
        "period": "2026", "health": "watch", "headline": "hmm",
        "changes": [{"metric": "savings_rate", "from": 99999.99,
                     "to": 88888.88, "note": "invented"}],
        "concerns": [], "suggestions": [],
    }
    client = MockClient([Response(text=json.dumps(findings))])
    ai_review.run_review(ledger, client=client,
                         cfg=ai_config.resolve(None, ledger),
                         structured=True, out=io.StringIO())
    err = capsys.readouterr().err
    assert "was not found in the bundle" in err


# -- redaction ---------------------------------------------------------------


def test_redaction_scrubs_free_text():
    data = [{"payee": "Whole Foods", "description": "weekly shop",
             "postings": [{"account": "Expenses:Food", "amount": "120.00"}]}]
    scrubbed = redaction.scrub(data)
    assert scrubbed[0]["payee"].startswith("[redacted:")
    assert scrubbed[0]["description"].startswith("[redacted:")
    # Structure and amounts survive; account names are structural, kept.
    assert scrubbed[0]["postings"][0]["account"] == "Expenses:Food"
    assert scrubbed[0]["postings"][0]["amount"] == "120.00"


# -- provider wire translation (no network) ----------------------------------


def _history():
    return [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "checking",
         "tool_calls": [{"id": "t1", "name": "get_analysis",
                         "arguments": {"period": "2026"}}]},
        {"role": "tool", "tool_call_id": "t1", "name": "get_analysis",
         "content": "{\"ok\": true}"},
    ]


def test_anthropic_wire_and_parse():
    from beans.ai.client import AnthropicClient
    wire = AnthropicClient._to_wire(_history())
    assert wire[0] == {"role": "user", "content": "hi"}
    assert wire[1]["role"] == "assistant"
    assert wire[1]["content"][1]["type"] == "tool_use"
    # The tool result is folded into a following user message.
    assert wire[2]["role"] == "user"
    assert wire[2]["content"][0]["type"] == "tool_result"

    raw = {"stop_reason": "tool_use", "content": [
        {"type": "text", "text": "hmm"},
        {"type": "tool_use", "id": "x", "name": "search",
         "input": {"query": "food"}}]}
    resp = AnthropicClient._parse(raw)
    assert resp.text == "hmm"
    assert resp.tool_calls[0].name == "search"
    assert resp.tool_calls[0].arguments == {"query": "food"}


def test_openai_wire_and_parse():
    from beans.ai.client import OpenAIClient
    wire = OpenAIClient._to_wire(_history())
    assert wire[1]["tool_calls"][0]["function"]["name"] == "get_analysis"
    assert wire[2]["role"] == "tool"
    assert wire[2]["tool_call_id"] == "t1"

    raw = {"choices": [{"finish_reason": "tool_calls", "message": {
        "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "search", "arguments": "{\"query\": \"food\"}"}}]}}]}
    resp = OpenAIClient._parse(raw)
    assert resp.tool_calls[0].name == "search"
    assert resp.tool_calls[0].arguments == {"query": "food"}


# -- graceful degradation via the CLI ----------------------------------------


def test_cli_ai_degrades_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BEANS_AI_KEY", raising=False)
    db = tmp_path / "led.db"
    assert cli.main(["--file", str(db), "init"]) == 0
    code = cli.main(["--file", str(db), "ai", "ask", "hi"])
    out = capsys.readouterr().out
    assert code == 0
    assert "beans-ledger[ai]" in out


def test_cli_ai_config_roundtrip(tmp_path, capsys):
    db = tmp_path / "led.db"
    cli.main(["--file", str(db), "init"])
    assert cli.main(["--file", str(db), "ai", "config", "set",
                     "ai.provider", "openai"]) == 0
    capsys.readouterr()
    cli.main(["--file", str(db), "ai", "config", "get", "ai.provider"])
    assert capsys.readouterr().out.strip() == "openai"


# -- live smoke test (opt-in) ------------------------------------------------


@pytest.mark.live
def test_live_ask_smoke(ledger):
    """Exercises a real provider; run with `pytest -m live` and a key set."""
    from beans.ai.client import build_client
    cfg = ai_config.resolve(None, ledger)
    if not cfg.configured:
        pytest.skip("no provider configured")
    client = build_client(cfg)
    out = io.StringIO()
    ai_ask.run_ask(ledger, "what is my total income in 2026?",
                   client=client, cfg=cfg, out=out)
    assert out.getvalue().strip()
