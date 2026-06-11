"""Plain-text rendering: aligned tables and hierarchical account trees."""

from __future__ import annotations

import sys

from beans.utils import format_amount

RULE = "rule"  # sentinel row: horizontal separator


def _use_color() -> bool:
    return sys.stdout.isatty()


def colorize(text: str, code: str) -> str:
    if not _use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return colorize(text, "1")


def red(text: str) -> str:
    return colorize(text, "31")


def green(text: str) -> str:
    return colorize(text, "32")


def money(minor: int, decimals: int = 2, symbol: str = "",
          color_negative: bool = True) -> str:
    text = format_amount(minor, decimals, symbol)
    if minor < 0 and color_negative:
        return red(text)
    return text


def _visible_len(text: str) -> int:
    """Length ignoring ANSI escape sequences."""
    length, i = 0, 0
    while i < len(text):
        if text[i] == "\033":
            i = text.index("m", i) + 1
        else:
            length += 1
            i += 1
    return length


def _pad(text: str, width: int, align: str) -> str:
    gap = width - _visible_len(text)
    if gap <= 0:
        return text
    return " " * gap + text if align == "r" else text + " " * gap


class Table:
    """Minimal column-aligned table. align is a string like 'lrr'."""

    def __init__(self, headers: list[str] | None = None, align: str = ""):
        self.headers = headers
        self.align = align
        self.rows: list[object] = []

    def add(self, *cells: str) -> None:
        self.rows.append([str(c) for c in cells])

    def rule(self) -> None:
        self.rows.append(RULE)

    def render(self, indent: str = "") -> str:
        data_rows = [r for r in self.rows if r is not RULE]
        all_rows = ([self.headers] if self.headers else []) + data_rows
        if not all_rows:
            return ""
        ncols = max(len(r) for r in all_rows)
        widths = [0] * ncols
        for row in all_rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], _visible_len(str(cell)))

        def fmt_row(row: list[str]) -> str:
            cells = []
            for i in range(ncols):
                cell = str(row[i]) if i < len(row) else ""
                a = self.align[i] if i < len(self.align) else "l"
                cells.append(_pad(cell, widths[i], a))
            return (indent + "  ".join(cells)).rstrip()

        lines = []
        if self.headers:
            lines.append(fmt_row([bold(h) for h in self.headers]))
            lines.append(indent + "-" * (sum(widths) + 2 * (ncols - 1)))
        for row in self.rows:
            if row is RULE:
                lines.append(indent + "-" * (sum(widths) + 2 * (ncols - 1)))
            else:
                lines.append(fmt_row(row))
        return "\n".join(lines)


def rollup(amounts: dict[str, int]) -> list[tuple[str, int, int, bool]]:
    """Aggregate colon-separated account names into a display tree.

    Returns (name, depth, amount, is_leaf) rows in tree order, where
    non-leaf rows carry the subtotal of their descendants (plus any
    balance posted directly to the parent account itself).
    """
    totals: dict[tuple[str, ...], int] = {}
    leaves = set()
    for name, amount in amounts.items():
        parts = tuple(name.split(":"))
        leaves.add(parts)
        for depth in range(1, len(parts) + 1):
            key = parts[:depth]
            totals[key] = totals.get(key, 0) + amount

    rows = []
    for key in sorted(totals, key=lambda k: tuple(p.lower() for p in k)):
        is_leaf = key in leaves and not any(
            other != key and other[: len(key)] == key for other in totals
        )
        rows.append((key[-1], len(key) - 1, totals[key], is_leaf))
    return rows


def strip_shared_root(
    tree: list[tuple[str, int, int, bool]],
    amounts: dict[str, int],
) -> list[tuple[str, int, int, bool]]:
    """Drop a single shared top-level segment (e.g. 'Assets') so statement
    sections don't repeat their own title, re-basing depths to zero.

    Kept as-is when the root segment is itself an account with postings,
    since dropping it would hide its directly-posted balance.
    """
    roots = [r for r in tree if r[1] == 0]
    if len(roots) != 1 or len(tree) == 1 or roots[0][0] in amounts:
        return tree
    return [(name, depth - 1, amount, leaf)
            for name, depth, amount, leaf in tree[1:]]
