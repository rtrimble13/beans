"""Export and backup: get your data out, whole and consistent.

- export json: the complete ledger — accounts, transactions, budgets,
  recurring rules, goals, import rules, lots, prices, exchange rates —
  as one structured document with amounts as decimal strings.
- export csv: one row per posting, flat, for spreadsheets.
- backup: a consistent point-in-time copy of the SQLite file made with
  the online backup API (safe even mid-write). Restore by pointing
  beans at the copy: `beans -f backup.db ...`.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from pathlib import Path

from beans import __version__
from beans.ledger import Ledger
from beans.reports import to_major
from beans.utils import BeansError, currency_decimals


def export_json(led: Ledger) -> dict:
    decimals = led.decimals

    def major(minor: int | None, code: str | None = None) -> str | None:
        if minor is None:
            return None
        return to_major(minor,
                        currency_decimals(code) if code else decimals)

    accounts = led.accounts(include_closed=True)
    currency_by_id = {a.id: a.currency for a in accounts}
    data = {
        "format": "beans-export",
        "version": __version__,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "meta": {
            "currency": led.currency,
            "decimals": decimals,
            "created": led.get_meta("created"),
            "default_account": led.get_meta("default_account"),
            "closed_through": (led.closed_through.isoformat()
                               if led.closed_through else None),
        },
        "accounts": [
            {
                "name": a.name,
                "type": a.type.value,
                "is_cash": a.is_cash,
                "cashflow": a.cashflow,
                "closed": a.closed,
                "currency": a.currency,
                "description": a.description,
            }
            for a in accounts
        ],
        "transactions": [
            {
                "id": t.id,
                "date": t.date.isoformat(),
                "description": t.description,
                "payee": t.payee,
                "tags": t.tags,
                "void": t.void,
                "postings": [
                    {
                        "account": p.account_name,
                        "amount": major(p.amount),
                        "cleared": p.cleared,
                        "foreign_amount": major(
                            p.foreign_amount,
                            currency_by_id.get(p.account_id)),
                        "currency": currency_by_id.get(p.account_id),
                    }
                    for p in t.postings
                ],
            }
            for t in led.transactions(include_void=True)
        ],
        "budgets": [
            {"account": a.name, "amount": major(amount), "period": period}
            for a, amount, period in led.budgets()
        ],
        "recurring": [
            {
                "name": r.name,
                "frequency": r.frequency,
                "start": r.start_date.isoformat(),
                "end": r.end_date.isoformat() if r.end_date else None,
                "occurrences": r.occurrences,
                "active": r.active,
                "description": r.description,
                "payee": r.payee,
                "tags": r.tags,
                "postings": [
                    {"account": p.account_name, "amount": major(p.amount)}
                    for p in r.postings
                ],
            }
            for r in led.recurrings()
        ],
        "goals": [
            {
                "name": g["name"],
                "account": g["account"].name,
                "target": major(g["target"]),
                "target_date": g["target_date"].isoformat(),
            }
            for g in led.goals()
        ],
        "import_rules": [
            {"pattern": pattern, "account": account.name}
            for _id, pattern, account in led.import_rules()
        ],
        "lots": [
            {
                "account": next(a.name for a in accounts
                                if a.id == lot["account_id"]),
                "symbol": lot["symbol"],
                "quantity": lot["quantity"],
                "cost": major(lot["cost"]),
                "acquired": lot["acquired"],
            }
            for lot in led.lots()
        ],
        "prices": [
            {"symbol": r["symbol"], "date": r["date"],
             "price": major(r["price"])}
            for r in led.prices()
        ],
        "fx_rates": [
            {"currency": r["currency"], "date": r["date"], "rate": r["rate"]}
            for r in led.fx_rates()
        ],
    }
    return data


def export_csv(led: Ledger) -> str:
    """Flat postings export: one row per posting."""
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["txn_id", "date", "description", "payee", "tags",
                     "void", "account", "amount", "cleared", "currency",
                     "foreign_amount"])
    # Include voided transactions, matching export_json: void is the
    # audit-preserving alternative to deletion, so a "whole" export must
    # carry it. The void column flags them (like the cleared column).
    for txn in led.transactions(include_void=True):
        for p in txn.postings:
            account = accounts.get(p.account_id)
            code = account.currency if account else None
            writer.writerow([
                txn.id,
                txn.date.isoformat(),
                txn.description,
                txn.payee,
                ",".join(txn.tags),
                int(txn.void),
                p.account_name,
                to_major(p.amount, led.decimals),
                int(p.cleared),
                code or "",
                (to_major(p.foreign_amount, currency_decimals(code))
                 if p.foreign_amount is not None and code else ""),
            ])
    return out.getvalue()


def backup(led: Ledger, dest: str | None = None) -> Path:
    """Consistent point-in-time copy of the ledger via SQLite's online
    backup API."""
    if dest:
        path = Path(dest).expanduser()
        if path.is_dir():
            path = path / _default_backup_name(led)
    else:
        path = led.path.with_name(_default_backup_name(led))
    if path.resolve() == led.path.resolve():
        raise BeansError("backup destination is the ledger itself")
    if path.exists():
        raise BeansError(f"{path} already exists — not overwriting a backup")
    path.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(path)
    try:
        with target:
            led.db.backup(target)
    finally:
        target.close()
    return path


def _default_backup_name(led: Ledger) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{led.path.stem}-backup-{stamp}{led.path.suffix or '.db'}"
