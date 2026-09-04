#!/usr/bin/env python3
"""Shared plumbing for the beans-report scripts: run read-only `beans`
commands, walk period keys, and do money arithmetic in `Decimal`.

Two invariants live here rather than in prose, because prose is not enforced:

* :func:`assert_read_only` — every command these scripts run must match a
  whitelisted read-only prefix. A reporting skill has no business writing to
  a ledger, and a typo should fail loudly rather than post a transaction.
* Money is :class:`~decimal.Decimal`, never ``float``. `beans` emits
  major-unit decimal strings; we parse, compare and re-emit them at the
  ledger's own precision so a figure never gains a rounding artifact on the
  way through.
"""

from __future__ import annotations

import calendar
import json
import subprocess
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# Read-only `beans` command prefixes these scripts may run. Anything else —
# import, tx add, recur run, period close, budget set — is refused.
READ_ONLY_PREFIXES = frozenset({
    ("report", "income"), ("report", "is"),
    ("report", "balance"), ("report", "bs"),
    ("report", "cashflow"), ("report", "cf"),
    ("report", "trial"), ("report", "tb"), ("report", "trend"),
    ("analyze",), ("networth",), ("status",), ("forecast",),
    ("budget", "report"), ("budget", "list"),
    ("account", "list"), ("recur", "list"), ("goal", "list"),
    ("loan", "list"), ("invest", "list"), ("price", "list"),
    ("config", "list"), ("period", "status"),
    ("register",), ("tx", "list"), ("tx", "show"), ("search",),
})

MAX_PREFIX = max(len(p) for p in READ_ONLY_PREFIXES)


class NotReadOnly(Exception):
    """Raised when a command is not on the read-only whitelist."""


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
    read-only command prefix. Options are ignored; only the leading
    subcommand words are matched."""
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
        "The beans-report skill never writes to the ledger.")


def build_argv(argv: list[str], *, beans: str = "beans",
               ledger: str | None = None, want_json: bool = True) -> list[str]:
    """Assemble the full command line. ``--file`` is a global option and must
    precede the subcommand."""
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
    """Run a read-only `beans` command and return its parsed JSON."""
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
    """Run a read-only `beans` command that has no --json form."""
    cmd = build_argv(argv, beans=beans, ledger=ledger, want_json=False)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BeansCommandError(argv, proc.returncode, proc.stderr)
    return proc.stdout


# -- periods -----------------------------------------------------------------

def month_key(when: date) -> str:
    return f"{when.year:04d}-{when.month:02d}"


def quarter_key(when: date) -> str:
    return f"{when.year:04d}-Q{(when.month - 1) // 3 + 1}"


def shift_month(key: str, delta: int) -> str:
    """Move a YYYY-MM key by ``delta`` months."""
    year, month = (int(part) for part in key.split("-"))
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def shift_quarter(key: str, delta: int) -> str:
    """Move a YYYY-QN key by ``delta`` quarters."""
    year, quarter = key.split("-Q")
    index = int(year) * 4 + (int(quarter) - 1) + delta
    return f"{index // 4:04d}-Q{index % 4 + 1}"


def shift(key: str, delta: int, grain: str) -> str:
    return shift_quarter(key, delta) if grain == "quarter" \
        else shift_month(key, delta)


def last_complete(today: date, grain: str) -> str:
    """The most recent period that has fully elapsed as of ``today``.

    The current period is *always* incomplete until its final day is behind
    us — a four-day-old month reports four days of spending against a whole
    month of history, which reads as a collapse that never happened. This is
    the single most important rule in the skill, so it is computed here once
    rather than judged per call site.
    """
    if grain == "quarter":
        current = quarter_key(today)
        end_month = ((today.month - 1) // 3 + 1) * 3
        last_day = _month_end(today.year, end_month)
        return current if today >= last_day else shift_quarter(current, -1)
    current = month_key(today)
    last_day = _month_end(today.year, today.month)
    return current if today >= last_day else shift_month(current, -1)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def period_keys(end_key: str, count: int, grain: str) -> list[str]:
    """``count`` period keys ending at ``end_key``, oldest first."""
    if count < 1:
        return []
    return [shift(end_key, offset, grain)
            for offset in range(-(count - 1), 1)]


# -- money -------------------------------------------------------------------

def dec(value, default: str = "0") -> Decimal:
    """Parse a `beans` money string into a Decimal. None/'' become ``default``
    — an account absent from a period's report earned or spent nothing, which
    is a real zero, not missing data."""
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def money_str(value: Decimal, decimals: int = 2) -> str:
    """Render a Decimal at the ledger's precision, the way beans does."""
    quantum = Decimal(1).scaleb(-decimals)
    return str(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def signed_str(value: Decimal, decimals: int = 2) -> str:
    """Like :func:`money_str` but always carries an explicit sign, so a
    change of +12.00 never reads as a level of 12.00."""
    text = money_str(abs(value), decimals)
    return f"-{text}" if value < 0 else f"+{text}"
