#!/usr/bin/env python3
"""Shared plumbing for the beans-economic scripts.

Deliberately standalone rather than importing beans-report's `beans_io`: the
skills install independently into `~/.claude/skills/`, so one may be present
without the other. The overlap is a few dozen lines and the alternative is a
dependency a user can silently not have.

Three invariants live here because prose does not enforce anything:

* :func:`assert_read_only` — these scripts run reporting commands only. The
  economic inputs are assumptions and are *never* posted to the ledger; that
  separation is the feature, so a typo must not be able to breach it.
* Money is :class:`~decimal.Decimal`, never ``float``.
* :func:`parse_rate` refuses an ambiguous percentage. `beans` reads a bare
  ``0.03`` as **0.03%**, not 3% — silently, and it roughly doubles future
  consumption. Every rate this skill emits or reads goes through here.
"""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal, ROUND_HALF_UP

# Read-only `beans` command prefixes these scripts may run. `economic
# create-template` is deliberately absent: this skill writes its own config
# from the user's answers and must never overwrite an existing plan.
READ_ONLY_PREFIXES = frozenset({
    ("economic", "bs"), ("economic", "npv"),
    ("ebs", "bs"), ("ebs", "npv"),
    ("report", "income"), ("report", "trend"), ("analyze",),
    ("networth",), ("status",), ("account", "list"), ("config", "list"),
    ("recur", "list"), ("goal", "list"), ("tx", "list"), ("budget", "list"),
})

MAX_PREFIX = max(len(prefix) for prefix in READ_ONLY_PREFIXES)

# A rate below this, written without a '%', is almost certainly a decimal the
# author meant as a percentage (0.03 for 3%). beans would read it as 0.03%.
AMBIGUOUS_RATE_BELOW = Decimal("0.5")


class NotReadOnly(Exception):
    """The command is not on the read-only whitelist."""


class AmbiguousRate(Exception):
    """A rate that beans and its author would read differently."""


class BeansCommandError(Exception):
    """A `beans` invocation failed. Carries the command and its stderr."""

    def __init__(self, argv: list[str], returncode: int, stderr: str):
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"`beans {' '.join(argv)}` failed "
                         f"({returncode}): {self.stderr}")


def assert_read_only(argv: list[str]) -> None:
    """Raise :class:`NotReadOnly` unless ``argv`` starts with a whitelisted
    read-only command prefix."""
    words = []
    for token in argv:
        if token.startswith("-"):
            break
        words.append(token)
        if len(words) == MAX_PREFIX:
            break
    for size in range(min(len(words), MAX_PREFIX), 0, -1):
        if tuple(words[:size]) in READ_ONLY_PREFIXES:
            return
    raise NotReadOnly(
        f"refusing to run `beans {' '.join(argv)}`: not a read-only command. "
        "The beans-economic skill never writes to the ledger.")


def build_argv(argv: list[str], *, beans: str = "beans",
               ledger: str | None = None, want_json: bool = True) -> list[str]:
    """Assemble the command line. ``--file`` is global and precedes the
    subcommand; the economic commands take their own ``--file`` for the config
    document, which is why the ledger flag must go first."""
    assert_read_only(argv)
    cmd = [beans]
    if ledger:
        cmd += ["--file", ledger]
    cmd += list(argv)
    if want_json and "--json" not in argv:
        cmd.append("--json")
    return cmd


def run_json(argv: list[str], *, beans: str = "beans",
             ledger: str | None = None):
    cmd = build_argv(argv, beans=beans, ledger=ledger, want_json=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BeansCommandError(argv, proc.returncode, proc.stderr)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BeansCommandError(argv, 0, f"non-JSON output: {exc}")


def run_text(argv: list[str], *, beans: str = "beans",
             ledger: str | None = None) -> str:
    cmd = build_argv(argv, beans=beans, ledger=ledger, want_json=False)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BeansCommandError(argv, proc.returncode, proc.stderr)
    return proc.stdout


# -- rates -------------------------------------------------------------------

def parse_rate(text, *, field: str = "rate",
               allow_negative: bool = False) -> Decimal:
    """Parse a percentage the way beans does — as percent units — but refuse
    the form where beans and its author disagree.

    `beans` reads a bare number as a percentage: '3' and '3%' are both 0.03.
    So '0.03', the other natural way to write 3%, means 0.03% — a factor of
    100. Rather than guess which was meant, refuse and say so.
    """
    raw = str(text).strip()
    if not raw:
        raise AmbiguousRate(f"{field} is empty")
    had_sign = raw.endswith("%")
    body = raw[:-1].strip() if had_sign else raw
    try:
        value = Decimal(body.replace(",", ""))
    except Exception:
        raise AmbiguousRate(f"{field}: {raw!r} is not a number")
    if value < 0 and not allow_negative:
        raise AmbiguousRate(f"{field} may not be negative: {raw!r}")
    if not had_sign and 0 < abs(value) < AMBIGUOUS_RATE_BELOW:
        raise AmbiguousRate(
            f"{field}={raw!r} is ambiguous: beans reads a bare number as a "
            f"percentage, so this means {value}%, not {value * 100}%. "
            f"Write '{value * 100}%' if you meant that, or '{value}%' if you "
            "really meant a fraction of a percent.")
    return value / 100


def rate_str(value: Decimal, places: int = 2) -> str:
    """Render a rate back as an explicit percentage — always with the sign, so
    a config this skill writes can never be re-read as a fraction."""
    pct = (Decimal(value) * 100).quantize(Decimal(1).scaleb(-places),
                                          rounding=ROUND_HALF_UP)
    return f"{pct.normalize():f}%"


# -- money -------------------------------------------------------------------

def dec(value, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value).replace(",", "").replace("$", ""))


def money_str(value: Decimal, decimals: int = 2) -> str:
    quantum = Decimal(1).scaleb(-decimals)
    return str(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def signed_str(value: Decimal, decimals: int = 2) -> str:
    text = money_str(abs(value), decimals)
    return f"-{text}" if value < 0 else f"+{text}"


def read_config_meta(beans: str = "beans", ledger: str | None = None) -> dict:
    """currency and decimals from `beans config list` (no --json form)."""
    out = {"currency": "USD", "decimals": 2}
    try:
        text = run_text(["config", "list"], beans=beans, ledger=ledger)
    except BeansCommandError:
        return out
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key == "currency":
            out["currency"] = value
        elif key == "decimals" and value.isdigit():
            out["decimals"] = int(value)
    return out
