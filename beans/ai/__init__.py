"""Optional AI assistant for beans.

This subpackage is the *only* part of beans that can reach the network. It is
shipped inside the wheel but is entirely opt-in: nothing here runs unless a
user invokes ``beans ai`` **and** a provider is configured. Because the `[ai]`
extra adds no third-party dependency (the client uses the standard library),
availability is a matter of *configuration*, not of an importable package —
:func:`beans.ai.config.AIConfig.configured` is the gate.

Everything is imported lazily from ``cli.py`` so the base tool never pays for
it.
"""

from __future__ import annotations

from . import config

__all__ = ["config", "privacy_notice", "data_flow_line"]


def data_flow_line(cfg: config.AIConfig) -> str:
    """One-line description of where data goes, for notices and --dry-run."""
    if cfg.is_local:
        return (f"Data flow: the JSON of the read-only beans commands the "
                f"assistant runs is sent to your local model at "
                f"{cfg.base_url} (nothing leaves your machine).")
    return (f"Data flow: the JSON of the read-only beans commands the "
            f"assistant runs is sent to {cfg.provider} "
            f"(model {cfg.model}) over HTTPS.")


def privacy_notice(cfg: config.AIConfig) -> str:
    """The one-time, plain-language notice shown before data first leaves the
    machine."""
    return (
        "\n── beans ai — privacy notice ─────────────────────────────────\n"
        "AI features send financial data off your machine. Specifically:\n"
        f"  • {data_flow_line(cfg)}\n"
        "  • Only the output of read-only reporting commands is sent; the\n"
        "    ledger file itself is never uploaded.\n"
        "  • Nothing is written to your ledger without a per-command\n"
        "    confirmation you approve.\n"
        "  • Use --dry-run to see exactly what would be sent without\n"
        "    sending anything, or point --base-url at a local model to keep\n"
        "    everything on-box. Turn on `beans ai config set ai.redact true`\n"
        "    to scrub payee/description text before it is sent.\n"
        "──────────────────────────────────────────────────────────────\n"
    )
