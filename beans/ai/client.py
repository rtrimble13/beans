"""A thin, provider-agnostic LLM client built on the standard library only.

The `[ai]` extra adds *no* runtime dependency: HTTP is done with
``urllib.request``. Two adapters share one small interface —
:meth:`LLMClient.complete` — so `ask` and `review` never see provider
differences:

* :class:`AnthropicClient` — the Messages API (default provider).
* :class:`OpenAIClient`    — any OpenAI-compatible endpoint, which also
  covers local models (Ollama, LM Studio, vLLM) via a custom ``base_url``.

Messages are exchanged in one normalized shape so the callers stay
provider-neutral::

    {"role": "user",      "content": "text"}
    {"role": "assistant", "content": "text"|None,
                          "tool_calls": [{"id", "name", "arguments": {...}}]}
    {"role": "tool",      "tool_call_id": "...", "name": "...",
                          "content": "json string"}

`complete()` returns a :class:`Response` carrying the assistant text and any
tool calls the model wants run.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from beans.utils import BeansError

from . import config as _config

ANTHROPIC_VERSION = "2023-06-01"
REQUEST_TIMEOUT = 120  # seconds; a generous cap, not a tuning knob


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Response:
    """A normalized model response."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    raw: dict | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    """POST a JSON body and return the parsed JSON response, translating
    transport and API errors into a clean :class:`BeansError`."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            pass
        msg = _extract_error(detail) or exc.reason or "request failed"
        raise BeansError(f"AI provider error ({exc.code}): {msg}")
    except urllib.error.URLError as exc:
        raise BeansError(
            f"could not reach the AI provider at {url}: {exc.reason} "
            "(check your network, --base-url, or a running local model)"
        )
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise BeansError("AI provider returned a non-JSON response")


def _extract_error(detail: str) -> str:
    """Pull a human message out of an error body when possible."""
    if not detail:
        return ""
    try:
        obj = json.loads(detail)
    except json.JSONDecodeError:
        return detail[:200]
    err = obj.get("error")
    if isinstance(err, dict):
        return err.get("message", "") or str(err)
    if isinstance(err, str):
        return err
    return obj.get("message", "") or detail[:200]


class LLMClient:
    """Interface shared by the adapters."""

    def complete(self, messages: list[dict], tools: list[dict] | None = None,
                 system: str | None = None) -> Response:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, cfg: _config.AIConfig):
        self.cfg = cfg

    def complete(self, messages, tools=None, system=None) -> Response:
        payload = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "messages": self._to_wire(messages),
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t["name"], "description": t["description"],
                 "input_schema": t["parameters"]}
                for t in tools
            ]
        headers = {
            "content-type": "application/json",
            "x-api-key": self.cfg.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        raw = _post_json(f"{self.cfg.base_url}/v1/messages", headers, payload)
        return self._parse(raw)

    @staticmethod
    def _to_wire(messages: list[dict]) -> list[dict]:
        """Convert normalized history to Anthropic content blocks, merging
        runs of tool results into a single user message (tool results are
        user-role blocks in the Messages API)."""
        wire: list[dict] = []
        pending_tool: list[dict] = []

        def flush_tools():
            if pending_tool:
                wire.append({"role": "user", "content": list(pending_tool)})
                pending_tool.clear()

        for m in messages:
            role = m["role"]
            if role == "tool":
                pending_tool.append({
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                })
                continue
            flush_tools()
            if role == "assistant":
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    blocks.append({
                        "type": "tool_use", "id": tc["id"],
                        "name": tc["name"], "input": tc["arguments"],
                    })
                wire.append({"role": "assistant", "content": blocks})
            else:  # user
                wire.append({"role": "user", "content": m["content"]})
        flush_tools()
        return wire

    @staticmethod
    def _parse(raw: dict) -> Response:
        text_parts, calls = [], []
        for block in raw.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(id=block["id"], name=block["name"],
                                      arguments=block.get("input", {})))
        return Response(
            text="".join(text_parts) or None,
            tool_calls=calls,
            stop_reason=raw.get("stop_reason", ""),
            raw=raw,
        )


class OpenAIClient(LLMClient):
    def __init__(self, cfg: _config.AIConfig):
        self.cfg = cfg

    def complete(self, messages, tools=None, system=None) -> Response:
        wire = []
        if system:
            wire.append({"role": "system", "content": system})
        wire.extend(self._to_wire(messages))
        payload = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "messages": wire,
        }
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t["name"],
                              "description": t["description"],
                              "parameters": t["parameters"]}}
                for t in tools
            ]
        headers = {"content-type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        raw = _post_json(f"{self.cfg.base_url}/chat/completions",
                         headers, payload)
        return self._parse(raw)

    @staticmethod
    def _to_wire(messages: list[dict]) -> list[dict]:
        wire = []
        for m in messages:
            role = m["role"]
            if role == "tool":
                wire.append({"role": "tool",
                             "tool_call_id": m["tool_call_id"],
                             "content": m["content"]})
            elif role == "assistant":
                entry = {"role": "assistant",
                         "content": m.get("content") or None}
                if m.get("tool_calls"):
                    entry["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"],
                                      "arguments": json.dumps(tc["arguments"])}}
                        for tc in m["tool_calls"]
                    ]
                wire.append(entry)
            else:
                wire.append({"role": "user", "content": m["content"]})
        return wire

    @staticmethod
    def _parse(raw: dict) -> Response:
        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message", {})
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                arguments = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(id=tc.get("id", ""),
                                  name=fn.get("name", ""),
                                  arguments=arguments))
        return Response(
            text=message.get("content"),
            tool_calls=calls,
            stop_reason=choice.get("finish_reason", ""),
            raw=raw,
        )


def build_client(cfg: _config.AIConfig) -> LLMClient:
    """Instantiate the adapter for the resolved provider."""
    if cfg.provider == _config.ANTHROPIC:
        return AnthropicClient(cfg)
    return OpenAIClient(cfg)
