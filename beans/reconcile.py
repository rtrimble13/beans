"""Bank reconciliation: compare the ledger's cleared balance for an
account against a real statement balance and surface what's outstanding.

Two levels of the same question:

*Balance level* — does the cleared balance tie to the statement's ending
balance?

    beans reconcile Checking --balance 4512.33      # where do we stand?
    beans clear Checking 12 14 15                   # mark matched entries
    beans clear Checking --through 2026-05-31       # or sweep a statement
    beans reconcile Checking --balance 4512.33      # difference -> 0.00

*Line level* — which line is wrong? Hand `reconcile` the statement export
itself and it pairs the rows off against the register and sorts what is
left into discrepancy classes (see `beans.matching`):

    beans reconcile Checking --statement may.csv --balance 4512.33
    beans reconcile Checking --statement may.csv --unmatched-out new.csv

Both are read-only. The second writes one optional file — the bank-only
rows, formatted for `beans import` with the category column pre-filled
where a rule matched — and that file is a draft for you to edit, not a
change to the ledger.
"""

from __future__ import annotations

from datetime import date

from beans.ledger import Ledger
from beans.models import Account
from beans.matching import MatchResult
from beans.render import Table, bold, green, money, red


def reconcile_report(led: Ledger, account: Account, statement_balance: int,
                     as_of: date) -> dict:
    sign = account.type.natural_sign
    cleared = led.cleared_balance(account, as_of) * sign
    uncleared = [
        {
            "id": row["txn_id"],
            "date": row["date"],
            "description": row["description"] or row["payee"],
            "amount": row["amount"] * sign,
        }
        for row in led.uncleared_postings(account, as_of)
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


# -- statement (line-level) reconciliation -----------------------------------


def statement_report(led: Ledger, account: Account, result: MatchResult,
                     source: str, statement_balance: int | None,
                     as_of: date, unmatched_file: str | None = None) -> dict:
    """Build the line-level reconciliation report from a match result,
    folding in the balance tie-out when a statement balance was given.

    Amounts come out sign-adjusted for display the same way the
    balance-level report does: positive means the account's natural
    direction, so a credit-card purchase reads positive.
    """
    sign = account.type.natural_sign

    def stmt(row):
        return {"line": row.line, "date": row.date,
                "description": row.description,
                "amount": row.amount * sign}

    def ledg(row):
        return {"id": row.txn_id, "date": row.date,
                "description": row.description or "",
                "amount": row.amount * sign}

    def paired(match):
        return {"id": match.ledger.txn_id, "line": match.statement.line,
                "date": match.ledger.date,
                "statement_date": match.statement.date,
                "drift_days": match.date_drift,
                "description": match.ledger.description or "",
                "statement_description": match.statement.description,
                "amount": match.ledger.amount * sign,
                "statement_amount": match.statement.amount * sign,
                "amount_delta": match.amount_delta * sign}

    cleared = led.cleared_balance(account, as_of) * sign
    data = {
        "report": "reconcile",
        "account": account.name,
        "as_of": as_of,
        "statement": {
            "file": source,
            "rows": len(result.rows),
            "start": result.start,
            "end": result.end,
            "total": result.statement_total * sign,
            "window_days": result.window,
        },
        "statement_balance": statement_balance,
        "cleared_balance": cleared,
        "difference": (None if statement_balance is None
                       else statement_balance - cleared),
        "summary": {
            "matched": len(result.matched),
            "date_drift": len(result.drifted),
            "amount_mismatch": len(result.mismatched),
            "bank_only": len(result.bank_only),
            "outstanding": len(result.outstanding),
            "cleared_missing": len(result.cleared_missing),
        },
        "date_drift": [paired(m) for m in result.drifted],
        "amount_mismatch": [paired(m) for m in result.mismatched],
        "bank_only": [stmt(r) for r in result.bank_only],
        "outstanding": [ledg(r) for r in result.outstanding],
        "cleared_missing": [ledg(r) for r in result.cleared_missing],
        "unmatched_file": unmatched_file,
    }
    return data


def _section(lines: list[str], title: str, note: str,
             headers: list[str], align: str, rows: list[list[str]]) -> None:
    if not rows:
        return
    lines.append("")
    lines.append(bold(f"{title} ({len(rows)})"))
    if note:
        lines.append(note)
    table = Table(headers=headers, align=align)
    for row in rows:
        table.add(*row)
    lines.append(table.render())


def render_statement_reconcile(data: dict, decimals: int,
                               symbol: str) -> str:
    stmt = data["statement"]
    counts = data["summary"]
    span = (f"{stmt['start'].isoformat()} → {stmt['end'].isoformat()}"
            if stmt["start"] else "no dated rows")
    lines = [
        bold(f"RECONCILE — {data['account']}"),
        f"Statement: {stmt['file']} — {stmt['rows']} row(s), {span}",
        f"Matching window: ±{stmt['window_days']} day(s)",
        "",
    ]

    if data["statement_balance"] is not None:
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

    table = Table(align="lr")
    table.add(bold("Matched"), bold(str(counts["matched"])))
    table.add("  on an exact date",
              str(counts["matched"] - counts["date_drift"]))
    table.add("  within the date window", str(counts["date_drift"]))
    table.rule()
    for label, key in (("Amount mismatch", "amount_mismatch"),
                       ("In bank, not in ledger", "bank_only"),
                       ("In ledger, not in bank", "outstanding"),
                       ("Cleared, absent from statement", "cleared_missing")):
        value = str(counts[key])
        table.add(label, value if counts[key] == 0 else red(value))
    lines.append(table.render())

    _section(
        lines, "Matched — date drift",
        "Same amount, nearby date. These are matches, not discrepancies "
        "(a recurring entry booked to the 1st often settles a day or two "
        "either side).",
        ["ID", "Ledger date", "Stmt date", "Drift", "Description", "Amount"],
        "rllrlr",
        [[row["id"], row["date"].isoformat(),
          row["statement_date"].isoformat(), f"{row['drift_days']:+d}d",
          (row["description"] or row["statement_description"])[:40],
          money(row["amount"], decimals)]
         for row in data["date_drift"]],
    )

    _section(
        lines, "Amount mismatch",
        "Same payee and date, different amount — check the entry.",
        ["ID", "Date", "Description", "Ledger", "Statement", "Diff"],
        "rllrrr",
        [[row["id"], row["date"].isoformat(), row["description"][:32],
          money(row["amount"], decimals),
          money(row["statement_amount"], decimals),
          money(row["amount_delta"], decimals)]
         for row in data["amount_mismatch"]],
    )

    _section(
        lines, "In bank, not in ledger",
        "On the statement but never recorded — import these.",
        ["Line", "Date", "Description", "Amount"], "rllr",
        [[row["line"], row["date"].isoformat(), row["description"][:45],
          money(row["amount"], decimals)]
         for row in data["bank_only"]],
    )

    _section(
        lines, "In ledger, not in bank",
        "Outstanding checks and deposits in transit look like this — so "
        "do duplicates and typos.",
        ["ID", "Date", "Description", "Amount"], "rllr",
        [[row["id"], row["date"].isoformat(), row["description"][:45],
          money(row["amount"], decimals)]
         for row in data["outstanding"]],
    )

    _section(
        lines, "Cleared, absent from statement",
        "Already ticked off against a statement that does not contain "
        "them — worth a look.",
        ["ID", "Date", "Description", "Amount"], "rllr",
        [[row["id"], row["date"].isoformat(), row["description"][:45],
          money(row["amount"], decimals)]
         for row in data["cleared_missing"]],
    )

    notes = []
    bank_total = sum(r["amount"] for r in data["bank_only"])
    ledger_total = sum(r["amount"] for r in data["outstanding"])
    if data["bank_only"] and data["outstanding"] and bank_total == ledger_total:
        notes.append(
            "Note: the two unmatched groups total the same amount "
            f"({money(bank_total, decimals, symbol)}) — this usually means "
            "one side splits or combines what the other records as a "
            "single entry."
        )
    # Outstanding ledger entries do not count against this: a check that
    # hasn't been presented yet is expected, and the claim here is only
    # that every line *on the statement* found its posting.
    if not any(counts[k] for k in ("amount_mismatch", "bank_only",
                                   "cleared_missing")):
        notes.append(green("Every statement line ties to the register."))
    if data["unmatched_file"]:
        notes.append(
            f"Wrote {len(data['bank_only'])} unmatched row(s) to "
            f"{data['unmatched_file']} — fill in any blank category, then: "
            f"beans import {data['unmatched_file']} "
            f"--account {data['account']}"
        )
    elif data["bank_only"]:
        notes.append(
            "Re-run with --unmatched-out PATH to write the bank-only rows "
            "as an editable CSV for `beans import`."
        )
    notes.append("Nothing was written to the ledger. Mark the confirmed "
                 f"entries with `beans clear {data['account']} <ID...>`.")
    lines.append("")
    lines.append("\n".join(notes))
    return "\n".join(lines)
