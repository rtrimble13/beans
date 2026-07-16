"""Resolve the AI configuration: provider, model, endpoint, key, and
privacy preferences.

Settings live in the ledger's `meta` table under an ``ai.*`` keyspace, so the
whole AI surface — commands, flags, and settings — is one tidy namespace that
grows without touching the rest of the tool. Values resolve in this order,
most specific first:

    CLI flag (on the `ai` group)  →  `beans ai config` setting (ai.*)
        →  environment variable  →  built-in default
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Provider identifiers.
ANTHROPIC = "anthropic"
OPENAI = "openai"
PROVIDERS = (ANTHROPIC, OPENAI)

# Built-in defaults. Anthropic is the out-of-the-box provider; a current,
# capable model is chosen so the agent loop and the analyst narrative both
# work well without the user picking a model.
DEFAULT_PROVIDER = ANTHROPIC
DEFAULT_MODELS = {
    ANTHROPIC: "claude-sonnet-5",
    OPENAI: "gpt-4o",
}
DEFAULT_BASE_URLS = {
    ANTHROPIC: "https://api.anthropic.com",
    OPENAI: "https://api.openai.com/v1",
}

# Bounds that mirror the existing runaway guards in the codebase
# (MAX_RUN_PER_RULE, MAX_SCHEDULE_MONTHS): cap the agent loop and the
# per-response token budget so a stuck model can't loop or spend forever.
DEFAULT_MAX_ITERATIONS = 8
DEFAULT_MAX_TOKENS = 2048

# Keys under the ai.* namespace that `beans ai config` accepts.
CONFIG_KEYS = (
    "ai.provider",
    "ai.model",
    "ai.base_url",
    "ai.max_tokens",
    "ai.max_iterations",
    "ai.redact",
    "ai.privacy_ack",
)


@dataclass
class AIConfig:
    """A fully-resolved AI configuration for one invocation."""

    provider: str = DEFAULT_PROVIDER
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    redact: bool = False
    dry_run: bool = False
    privacy_ack: bool = False
    # Where the key came from, for the privacy notice (env var name or None).
    key_source: str | None = None
    _meta: dict = field(default_factory=dict, repr=False)

    @property
    def is_local(self) -> bool:
        """A non-default base URL points the OpenAI-compatible adapter at a
        local model (Ollama, LM Studio, vLLM), where no hosted key is sent."""
        if self.provider != OPENAI:
            return False
        return bool(self.base_url) and self.base_url != DEFAULT_BASE_URLS[OPENAI]

    @property
    def configured(self) -> bool:
        """True when a request could actually be made: a key is resolved, or
        the endpoint is a local model that needs none."""
        return bool(self.api_key) or self.is_local

    def missing_reason(self) -> str:
        """A short, accurate explanation of why AI is unavailable."""
        env = ("ANTHROPIC_API_KEY" if self.provider == ANTHROPIC
               else "OPENAI_API_KEY")
        return (
            "beans ai needs the optional AI extra and a provider key.\n"
            "  Install:   pip install \"beans-ledger[ai]\"\n"
            f"  Configure: set {env} (or BEANS_AI_KEY) in your environment,\n"
            "             or run `beans ai config set ai.base_url <url>` to\n"
            "             point at a local model (e.g. Ollama). See\n"
            "             `beans ai config` and `beans ai` for the details."
        )


def _env_key(provider: str) -> tuple[str | None, str | None]:
    """Return (api_key, source-env-var-name) for a provider from the
    environment. BEANS_AI_KEY overrides the provider-specific variable."""
    candidates = ["BEANS_AI_KEY"]
    if provider == ANTHROPIC:
        candidates.append("ANTHROPIC_API_KEY")
    else:
        candidates.append("OPENAI_API_KEY")
    for name in candidates:
        value = os.environ.get(name)
        if value:
            return value, name
    return None, None


def _meta_get(led, key: str) -> str | None:
    return led.get_meta(key) if led is not None else None


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def resolve(args=None, led=None) -> AIConfig:
    """Resolve an :class:`AIConfig` from CLI flags, stored ai.* settings,
    the environment, and built-in defaults, in that precedence."""

    def flag(name):
        return getattr(args, name, None) if args is not None else None

    provider = (flag("provider")
                or _meta_get(led, "ai.provider")
                or DEFAULT_PROVIDER)
    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER

    model = (flag("model")
             or _meta_get(led, "ai.model")
             or DEFAULT_MODELS[provider])
    base_url = (flag("base_url")
                or _meta_get(led, "ai.base_url")
                or DEFAULT_BASE_URLS[provider])

    api_key, key_source = _env_key(provider)

    cfg = AIConfig(
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key or "",
        max_tokens=_as_int(_meta_get(led, "ai.max_tokens"),
                            DEFAULT_MAX_TOKENS),
        max_iterations=_as_int(_meta_get(led, "ai.max_iterations"),
                               DEFAULT_MAX_ITERATIONS),
        redact=_as_bool(_meta_get(led, "ai.redact")),
        dry_run=bool(flag("dry_run")),
        privacy_ack=_as_bool(_meta_get(led, "ai.privacy_ack")),
        key_source=key_source,
    )
    return cfg
