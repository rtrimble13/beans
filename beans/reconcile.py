"""Bank reconciliation: compare the ledger's cleared balance for an
account against a real statement balance and surface what's outstanding.

Workflow:
    beans reconcile Checking --balance 4512.33      # where do we stand?
    beans clear Checking 12 14 15                   # mark matched entries
    beans clear Checking --through 2026-05-31       # or sweep a statement
    beans reconcile Checking --balance 4512.33      # difference -> 0.00
"""

from __future__ import annotations

from datetime import date

from beans.ledger import Ledger
from beans.models import Account
from beans.render import Table, bold, green, money, red


def reconcile_report(led: Ledger, account: Account, statement_balance: int,
                     as_of: date) -> dict:
    sign = account.type.natural_sign
    cleared = led.cleared_balance(account, as_of) * sign
    uncleared = [
        {
            "id": txn.id,
            "date": txn.date,
            "description": txn.description or txn.payee,
            "amount": posting.amount * sign,
        }
        for txn, posting in led.uncleared_postings(account, as_of)
    ]
    return {
        "report": "reconcile",
        "account": account.name,
        "as_of": as_of,
        "statement_balance": statement_balance,
        "cleared_balance": cleared,
        "difference": statement_balance - cleared,
        "uncleared": uncleared,
        "uncleared_total": sum(u["amount"] for u in uncleared),
    }


def render_reconcile(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold(f"RECONCILE — {data['account']}"),
             f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(align="lr")
    table.add("Statement balance",
              money(data["statement_balance"], decimals, symbol))
    table.add("Cleared balance",
              money(data["cleared_balance"], decimals, symbol))
    diff = data["difference"]
    diff_text = money(diff, decimals, symbol, color_negative=False)
    table.add(bold("Difference"),
              green(diff_text) if diff == 0 else red(diff_text))
    lines.append(table.render())
    lines.append("")
    if diff == 0:
        lines.append(green("Reconciled — cleared balance matches the "
                           "statement."))
    if data["uncleared"]:
        lines.append(bold(f"{len(data['uncleared'])} uncleared posting(s) "
                          f"totaling "
                          f"{money(data['uncleared_total'], decimals, symbol)}"
                          ))
        table = Table(headers=["ID", "Date", "Description", "Amount"],
                      align="rllr")
        for row in data["uncleared"]:
            table.add(row["id"], row["date"].isoformat(),
                      row["description"][:45], money(row["amount"], decimals))
        lines.append(table.render())
        if diff != 0:
            lines.append("")
            lines.append("Mark matched entries with `beans clear "
                         f"{data['account']} <ID...>` or sweep a statement "
                         f"with `beans clear {data['account']} "
                         "--through DATE`.")
    elif diff != 0:
        lines.append("No uncleared postings — the difference suggests a "
                     "missing or duplicated transaction.")
    return "\n".join(lines)
