"""The tool whitelist: a curated set of callable tools that map 1:1 onto safe
`beans` subcommands.

Rather than exposing a raw shell, each tool declares a JSON-schema for its
arguments and knows how to turn those arguments into an ``argv`` list for
``cli.main``. The runner executes that argv in-process and feeds the captured
``--json`` back to the model. Period strings (``ytd``, ``this-month``,
``2026-Q1``) pass straight through to the existing period parser — nothing is
reimplemented here.

Read-only tools are always available. Mutating tools are included only when
the caller passes ``--allow-writes``, and even then the runner confirms each
one against the exact command line before it touches the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

_PERIOD_PROP = {
    "period": {
        "type": "string",
        "description": ("period selector: ytd, all, this-month, last-month, "
                        "this-quarter, last-quarter, this-year, last-year, "
                        "YYYY, YYYY-MM, or YYYY-QN"),
    },
}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    build_argv: Callable[[dict], list[str]]
    writes: bool = False

    def definition(self) -> dict:
        """The provider-neutral tool definition sent to the model."""
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters}


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or []}


def _period_argv(args: dict) -> list[str]:
    period = args.get("period")
    return ["--period", str(period)] if period else []


# -- read-only tools ---------------------------------------------------------

READ_TOOLS: list[Tool] = [
    Tool(
        "get_income_statement",
        "Income statement (revenue, expenses, net) with common-size "
        "percentages; pass compare=true to include the prior period.",
        _schema({**_PERIOD_PROP,
                 "compare": {"type": "boolean",
                             "description": "compare against the prior "
                                            "period"}}),
        lambda a: (["report", "income", "--json"] + _period_argv(a)
                   + (["--compare"] if a.get("compare") else [])),
    ),
    Tool(
        "get_balance_sheet",
        "Classified balance sheet (assets, liabilities, equity) as of a date.",
        _schema({"date": {"type": "string",
                          "description": "as-of date YYYY-MM-DD "
                                         "(default: today)"},
                 "flat": {"type": "boolean",
                          "description": "skip the current/non-current "
                                         "split"}}),
        lambda a: (["report", "balance", "--json"]
                   + (["--date", str(a["date"])] if a.get("date") else [])
                   + (["--flat"] if a.get("flat") else [])),
    ),
    Tool(
        "get_cashflow",
        "Direct-method statement of cash flows for a period.",
        _schema(dict(_PERIOD_PROP)),
        lambda a: ["report", "cashflow", "--json"] + _period_argv(a),
    ),
    Tool(
        "get_analysis",
        "Financial ratios and analysis: savings rate, liquidity runway, "
        "current ratio, debt-to-assets, debt-to-income, and top expenses.",
        _schema(dict(_PERIOD_PROP)),
        lambda a: ["analyze", "--json"] + _period_argv(a),
    ),
    Tool(
        "list_transactions",
        "List transactions, optionally filtered by period, account, or count.",
        _schema({**_PERIOD_PROP,
                 "account": {"type": "string",
                             "description": "only transactions involving "
                                            "this account"},
                 "limit": {"type": "integer",
                           "description": "return only the last N"}}),
        lambda a: (["tx", "list", "--json"] + _period_argv(a)
                   + (["--account", str(a["account"])]
                      if a.get("account") else [])
                   + (["--limit", str(a["limit"])] if a.get("limit") else [])),
    ),
    Tool(
        "search",
        "Full-text search over transaction descriptions, payees, and tags.",
        _schema({"query": {"type": "string", "description": "search text"},
                 "limit": {"type": "integer",
                           "description": "return only the last N matches"}},
                required=["query"]),
        lambda a: (["search", "--json", str(a["query"])]
                   + (["--limit", str(a["limit"])] if a.get("limit") else [])),
    ),
    Tool(
        "get_register",
        "Running-balance register for one account over a period.",
        _schema({"account": {"type": "string",
                             "description": "account name"},
                 **_PERIOD_PROP},
                required=["account"]),
        lambda a: (["register", str(a["account"]), "--json"]
                   + _period_argv(a)),
    ),
    Tool(
        "get_budget_report",
        "Budget-vs-actual variance for a period (defaults to this month).",
        _schema(dict(_PERIOD_PROP)),
        lambda a: ["budget", "report", "--json"] + _period_argv(a),
    ),
    Tool(
        "get_forecast",
        "Project finances forward from history, budgets, and recurring rules.",
        _schema({"months": {"type": "integer",
                            "description": "months to project (default 6)"},
                 "method": {"type": "string", "enum": ["average", "trend"],
                            "description": "projection method"}}),
        lambda a: (["forecast", "--json"]
                   + (["--months", str(a["months"])]
                      if a.get("months") else [])
                   + (["--method", str(a["method"])]
                      if a.get("method") else [])),
    ),
    Tool(
        "get_networth",
        "Month-end net-worth trend over the last N months.",
        _schema({"months": {"type": "integer",
                            "description": "months of history (default 12)"}}),
        lambda a: (["networth", "--json"]
                   + (["--months", str(a["months"])]
                      if a.get("months") else [])),
    ),
    Tool(
        "list_accounts",
        "The chart of accounts with current balances.",
        _schema({"type": {"type": "string",
                          "enum": ["asset", "liability", "equity",
                                   "income", "expense"],
                          "description": "filter by account type"},
                 "all": {"type": "boolean",
                         "description": "include closed accounts"}}),
        lambda a: (["account", "list", "--json"]
                   + (["--type", str(a["type"])] if a.get("type") else [])
                   + (["--all"] if a.get("all") else [])),
    ),
    Tool(
        "get_economic_balance_sheet",
        "Economic balance sheet: human-capital NPV, PV of lifetime "
        "consumption, and economic (vs accounting) net worth.",
        _schema({}),
        lambda a: ["economic", "bs", "--json"],
    ),
]


# -- write tools (only when --allow-writes) ----------------------------------

WRITE_TOOLS: list[Tool] = [
    Tool(
        "record_expense",
        "Record an expense (money leaving a cash account into an expense "
        "category). Requires explicit user confirmation before it runs.",
        _schema({"amount": {"type": "string",
                            "description": "positive amount, e.g. 42.50"},
                 "category": {"type": "string",
                              "description": "expense account, e.g. "
                                             "Expenses:Dining"},
                 "source": {"type": "string",
                            "description": "paying account (default: the "
                                           "configured default account)"},
                 "description": {"type": "string"},
                 "date": {"type": "string",
                          "description": "YYYY-MM-DD (default: today)"}},
                required=["amount", "category"]),
        lambda a: (["spend", str(a["amount"]), str(a["category"])]
                   + (["--from", str(a["source"])] if a.get("source") else [])
                   + (["--desc", str(a["description"])]
                      if a.get("description") else [])
                   + (["--date", str(a["date"])] if a.get("date") else [])),
        writes=True,
    ),
    Tool(
        "record_income",
        "Record income (money arriving into a cash account from an income "
        "source). Requires explicit user confirmation before it runs.",
        _schema({"amount": {"type": "string"},
                 "source": {"type": "string",
                            "description": "income account, e.g. "
                                           "Income:Salary"},
                 "target": {"type": "string",
                            "description": "receiving account (default: the "
                                           "configured default account)"},
                 "description": {"type": "string"},
                 "date": {"type": "string"}},
                required=["amount", "source"]),
        lambda a: (["earn", str(a["amount"]), str(a["source"])]
                   + (["--to", str(a["target"])] if a.get("target") else [])
                   + (["--desc", str(a["description"])]
                      if a.get("description") else [])
                   + (["--date", str(a["date"])] if a.get("date") else [])),
        writes=True,
    ),
    Tool(
        "record_transfer",
        "Move money between two accounts. Requires explicit user "
        "confirmation before it runs.",
        _schema({"amount": {"type": "string"},
                 "source": {"type": "string", "description": "from account"},
                 "target": {"type": "string", "description": "to account"},
                 "description": {"type": "string"},
                 "date": {"type": "string"}},
                required=["amount", "source", "target"]),
        lambda a: (["transfer", str(a["amount"]), str(a["source"]),
                    str(a["target"])]
                   + (["--desc", str(a["description"])]
                      if a.get("description") else [])
                   + (["--date", str(a["date"])] if a.get("date") else [])),
        writes=True,
    ),
]


def registry(allow_writes: bool = False) -> dict[str, Tool]:
    """The name→Tool map available to the agent for this invocation."""
    tools = list(READ_TOOLS)
    if allow_writes:
        tools += WRITE_TOOLS
    return {t.name: t for t in tools}


def definitions(allow_writes: bool = False) -> list[dict]:
    """Tool definitions to send to the model."""
    return [t.definition() for t in registry(allow_writes).values()]
