"""The deterministic "review bundle": the fixed set of read-only reports that
a financial-analyst narrative reads from.

Living in `_toolcore` keeps a single source of truth for *which* reports make
up a review, shared by the `beans ai review` narrative and the MCP
`beans_review_bundle` tool, so the two never drift.
"""

from __future__ import annotations


def review_bundle_spec(period: str | None = None, compare: str | None = None,
                       focus: str | None = None) -> list[tuple[str, list[str]]]:
    """The ordered (label, argv) pairs gathered for a review."""
    per = ["--period", period] if period else []
    spec = [
        ("income_statement", ["report", "income", "--json", "--compare"]
         + per),
        ("balance_sheet", ["report", "balance", "--json"]),
        ("cash_flow", ["report", "cashflow", "--json"] + per),
        ("analysis", ["analyze", "--json"] + per),
        ("budget", ["budget", "report", "--json"] + per),
        ("net_worth", ["networth", "--json"]),
    ]
    if compare:
        spec.append(("income_statement_comparison",
                     ["report", "income", "--json", "--period", compare]))
    if focus == "economic":
        spec.append(("economic_balance_sheet",
                     ["economic", "bs", "--json"]))
    return spec


def assemble_review_bundle(runner, *, period=None, compare=None,
                           focus=None) -> dict:
    """Run the fixed report set through ``runner`` and collect their JSON. A
    report that legitimately can't run (e.g. no budgets set) is recorded with
    its error rather than aborting the whole bundle."""
    statements: dict[str, object] = {}
    for label, argv in review_bundle_spec(period, compare, focus):
        result = runner.run_argv(label, argv)
        if result.ok:
            statements[label] = result.data
        else:
            statements[label] = {"unavailable": result.error}
    return {"period": _period_label(period, statements),
            "statements": statements}


def _period_label(period: str | None, statements: dict) -> str:
    if period:
        return period
    income = statements.get("income_statement")
    if isinstance(income, dict):
        for key in ("period", "label"):
            if isinstance(income.get(key), str):
                return income[key]
    return "current period"
