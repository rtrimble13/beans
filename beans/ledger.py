"""SQLite-backed double-entry ledger.

All amounts are integers in minor units (e.g. cents) with postings stored
debit-positive / credit-negative. Every transaction's postings must sum to
exactly zero — the invariant that makes this a true double-entry system.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from beans.models import (
    CASHFLOW_CATEGORIES,
    RECURRENCE_FREQUENCIES,
    Account,
    AccountType,
    Posting,
    Recurring,
    Transaction,
)
from beans.utils import BeansError, format_amount

DEFAULT_LEDGER_PATH = Path.home() / ".beans" / "ledger.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    type        TEXT NOT NULL CHECK (type IN
                ('asset','liability','equity','income','expense')),
    is_cash     INTEGER NOT NULL DEFAULT 0,
    cf_category TEXT CHECK (cf_category IN
                ('operating','investing','financing')),
    closed      INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    payee       TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    void        INTEGER NOT NULL DEFAULT 0,
    created     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS postings (
    id         INTEGER PRIMARY KEY,
    txn_id     INTEGER NOT NULL REFERENCES transactions(id)
               ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    id         INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL UNIQUE REFERENCES accounts(id),
    amount     INTEGER NOT NULL,
    period     TEXT NOT NULL DEFAULT 'monthly' CHECK (period IN
               ('weekly','monthly','quarterly','yearly'))
);
CREATE TABLE IF NOT EXISTS recurring (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    payee       TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    frequency   TEXT NOT NULL CHECK (frequency IN
                ('daily','weekly','biweekly','monthly','quarterly','yearly')),
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    occurrences INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS recurring_postings (
    id           INTEGER PRIMARY KEY,
    recurring_id INTEGER NOT NULL REFERENCES recurring(id)
                 ON DELETE CASCADE,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    amount       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_postings_txn ON postings(txn_id);
CREATE INDEX IF NOT EXISTS idx_postings_account ON postings(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
"""

# (name, type, is_cash) — a sensible starter chart for personal finance.
DEFAULT_CHART: list[tuple[str, AccountType, bool]] = [
    ("Assets:Cash", AccountType.ASSET, True),
    ("Assets:Checking", AccountType.ASSET, True),
    ("Assets:Savings", AccountType.ASSET, True),
    ("Assets:Investments:Brokerage", AccountType.ASSET, False),
    ("Assets:Investments:Retirement", AccountType.ASSET, False),
    ("Liabilities:Credit Card", AccountType.LIABILITY, False),
    ("Liabilities:Loans", AccountType.LIABILITY, False),
    ("Equity:Opening Balances", AccountType.EQUITY, False),
    ("Income:Salary", AccountType.INCOME, False),
    ("Income:Interest", AccountType.INCOME, False),
    ("Income:Dividends", AccountType.INCOME, False),
    ("Income:Other", AccountType.INCOME, False),
    ("Expenses:Housing:Rent", AccountType.EXPENSE, False),
    ("Expenses:Housing:Utilities", AccountType.EXPENSE, False),
    ("Expenses:Food:Groceries", AccountType.EXPENSE, False),
    ("Expenses:Food:Dining", AccountType.EXPENSE, False),
    ("Expenses:Transportation", AccountType.EXPENSE, False),
    ("Expenses:Health", AccountType.EXPENSE, False),
    ("Expenses:Insurance", AccountType.EXPENSE, False),
    ("Expenses:Entertainment", AccountType.EXPENSE, False),
    ("Expenses:Shopping", AccountType.EXPENSE, False),
    ("Expenses:Taxes", AccountType.EXPENSE, False),
    ("Expenses:Other", AccountType.EXPENSE, False),
]

BUDGET_PERIOD_MONTHS = {
    "weekly": 12 / 52.1775,
    "monthly": 1.0,
    "quarterly": 3.0,
    "yearly": 12.0,
}


def ledger_path(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("BEANS_LEDGER")
    if env:
        return Path(env).expanduser()
    return DEFAULT_LEDGER_PATH


class Ledger:
    def __init__(self, path: Path | str, create: bool = False):
        path = Path(path)
        if not create and not path.exists():
            raise BeansError(
                f"no ledger found at {path} — run `beans init` first "
                "(or point at one with --file or $BEANS_LEDGER)"
            )
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- metadata ----------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    @property
    def currency(self) -> str:
        return self.get_meta("currency", "USD")

    @property
    def decimals(self) -> int:
        return int(self.get_meta("decimals", "2"))

    def initialize(self, currency: str = "USD", with_chart: bool = True) -> None:
        if self.get_meta("currency"):
            raise BeansError(f"ledger at {self.path} is already initialized")
        self.set_meta("currency", currency.upper())
        self.set_meta("decimals", "0" if currency.upper() == "JPY" else "2")
        self.set_meta("created", datetime.now().isoformat(timespec="seconds"))
        if with_chart:
            for name, type_, is_cash in DEFAULT_CHART:
                self.add_account(name, type_, is_cash=is_cash)

    # -- accounts ----------------------------------------------------------

    @staticmethod
    def _row_to_account(row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            name=row["name"],
            type=AccountType(row["type"]),
            is_cash=bool(row["is_cash"]),
            cf_category=row["cf_category"],
            closed=bool(row["closed"]),
            description=row["description"],
        )

    def add_account(
        self,
        name: str,
        type_: AccountType,
        is_cash: bool = False,
        cf_category: str | None = None,
        description: str = "",
    ) -> Account:
        name = name.strip()
        if not name or name.startswith(":") or name.endswith(":"):
            raise BeansError(f"invalid account name: {name!r}")
        if cf_category and cf_category not in CASHFLOW_CATEGORIES:
            raise BeansError(
                f"invalid cash-flow category {cf_category!r} "
                f"(expected one of {', '.join(CASHFLOW_CATEGORIES)})"
            )
        if is_cash and type_ is not AccountType.ASSET:
            raise BeansError("only asset accounts can be marked as cash")
        try:
            with self.db:
                cur = self.db.execute(
                    "INSERT INTO accounts "
                    "(name, type, is_cash, cf_category, description) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, type_.value, int(is_cash), cf_category, description),
                )
        except sqlite3.IntegrityError:
            raise BeansError(f"account {name!r} already exists")
        return Account(cur.lastrowid, name, type_, is_cash, cf_category,
                       False, description)

    def accounts(
        self,
        type_: AccountType | None = None,
        include_closed: bool = False,
    ) -> list[Account]:
        sql = "SELECT * FROM accounts"
        clauses, params = [], []
        if type_:
            clauses.append("type = ?")
            params.append(type_.value)
        if not include_closed:
            clauses.append("closed = 0")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name COLLATE NOCASE"
        return [self._row_to_account(r) for r in self.db.execute(sql, params)]

    def find_account(self, query: str) -> Account:
        """Resolve a user-supplied name: exact, then unique leaf, then
        unique substring match (all case-insensitive)."""
        query = query.strip()
        row = self.db.execute(
            "SELECT * FROM accounts WHERE name = ? COLLATE NOCASE", (query,)
        ).fetchone()
        if row:
            return self._row_to_account(row)
        candidates = self.accounts(include_closed=True)
        q = query.lower()
        leaf = [a for a in candidates if a.leaf.lower() == q]
        if len(leaf) == 1:
            return leaf[0]
        sub = [a for a in candidates if q in a.name.lower()]
        if len(sub) == 1:
            return sub[0]
        matches = leaf or sub
        if matches:
            names = ", ".join(a.name for a in matches[:6])
            raise BeansError(f"account {query!r} is ambiguous: {names}")
        raise BeansError(
            f"no account matches {query!r} (see `beans account list`)"
        )

    def update_account(self, account: Account, **fields) -> None:
        allowed = {"name", "is_cash", "cf_category", "closed", "description"}
        if "name" in fields:
            name = fields["name"] = str(fields["name"]).strip()
            if not name or name.startswith(":") or name.endswith(":"):
                raise BeansError(f"invalid account name: {name!r}")
        cf = fields.get("cf_category")
        if cf is not None and cf not in CASHFLOW_CATEGORIES:
            raise BeansError(
                f"invalid cash-flow category {cf!r} "
                f"(expected one of {', '.join(CASHFLOW_CATEGORIES)})"
            )
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"cannot update field {key!r}")
            sets.append(f"{key} = ?")
            params.append(int(value) if isinstance(value, bool) else value)
        if not sets:
            return
        params.append(account.id)
        try:
            with self.db:
                self.db.execute(
                    f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
        except sqlite3.IntegrityError as exc:
            if "name" in fields:
                raise BeansError(
                    f"account {fields['name']!r} already exists"
                )
            raise BeansError(f"could not update {account.name}: {exc}")

    def close_account(self, account: Account) -> None:
        balance = self.balances(as_of=None).get(account.id, 0)
        if balance != 0:
            raise BeansError(
                f"cannot close {account.name}: balance is not zero "
                "(transfer the remaining balance first)"
            )
        self.update_account(account, closed=True)

    # -- transactions ------------------------------------------------------

    def _check_postings(self, postings: list[Posting]) -> None:
        if len(postings) < 2:
            raise BeansError("a transaction needs at least two postings")
        total = sum(p.amount for p in postings)
        if total != 0:
            raise BeansError(
                "transaction does not balance: postings sum to "
                f"{format_amount(total, self.decimals)} "
                "(debits must equal credits)"
            )
        if any(p.amount == 0 for p in postings):
            raise BeansError("postings must have a non-zero amount")

    def add_transaction(
        self,
        when: date,
        description: str,
        postings: list[Posting],
        payee: str = "",
        tags: list[str] | None = None,
    ) -> Transaction:
        self._check_postings(postings)
        tags = tags or []
        with self.db:
            cur = self.db.execute(
                "INSERT INTO transactions "
                "(date, description, payee, tags, created) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    when.isoformat(),
                    description,
                    payee,
                    ",".join(tags),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            txn_id = cur.lastrowid
            self.db.executemany(
                "INSERT INTO postings (txn_id, account_id, amount) "
                "VALUES (?, ?, ?)",
                [(txn_id, p.account_id, p.amount) for p in postings],
            )
        return Transaction(txn_id, when, description, payee, tags,
                           False, postings)

    def get_transaction(self, txn_id: int) -> Transaction:
        row = self.db.execute(
            "SELECT * FROM transactions WHERE id = ?", (txn_id,)
        ).fetchone()
        if not row:
            raise BeansError(f"no transaction with id {txn_id}")
        return self._build_transaction(row)

    def _build_transaction(self, row: sqlite3.Row) -> Transaction:
        postings = [
            Posting(
                id=p["id"],
                account_id=p["account_id"],
                amount=p["amount"],
                account_name=p["name"],
            )
            for p in self.db.execute(
                "SELECT p.*, a.name FROM postings p "
                "JOIN accounts a ON a.id = p.account_id "
                "WHERE p.txn_id = ? ORDER BY p.id",
                (row["id"],),
            )
        ]
        return Transaction(
            id=row["id"],
            date=date.fromisoformat(row["date"]),
            description=row["description"],
            payee=row["payee"],
            tags=[t for t in row["tags"].split(",") if t],
            void=bool(row["void"]),
            postings=postings,
        )

    def transactions(
        self,
        start: date | None = None,
        end: date | None = None,
        account: Account | None = None,
        limit: int | None = None,
        include_void: bool = False,
    ) -> list[Transaction]:
        sql = "SELECT DISTINCT t.* FROM transactions t"
        clauses, params = [], []
        if account:
            sql += " JOIN postings p ON p.txn_id = t.id"
            clauses.append("p.account_id = ?")
            params.append(account.id)
        if start:
            clauses.append("t.date >= ?")
            params.append(start.isoformat())
        if end:
            clauses.append("t.date <= ?")
            params.append(end.isoformat())
        if not include_void:
            clauses.append("t.void = 0")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY t.date, t.id"
        rows = self.db.execute(sql, params).fetchall()
        if limit:
            rows = rows[-limit:]
        return [self._build_transaction(r) for r in rows]

    def void_transaction(self, txn_id: int) -> Transaction:
        txn = self.get_transaction(txn_id)
        if txn.void:
            raise BeansError(f"transaction {txn_id} is already void")
        with self.db:
            self.db.execute(
                "UPDATE transactions SET void = 1 WHERE id = ?", (txn_id,)
            )
        txn.void = True
        return txn

    # -- aggregates --------------------------------------------------------

    def balances(self, as_of: date | None = None) -> dict[int, int]:
        """Raw balance (debit-positive) per account id through as_of."""
        sql = (
            "SELECT p.account_id, SUM(p.amount) AS total FROM postings p "
            "JOIN transactions t ON t.id = p.txn_id WHERE t.void = 0"
        )
        params: list[str] = []
        if as_of:
            sql += " AND t.date <= ?"
            params.append(as_of.isoformat())
        sql += " GROUP BY p.account_id"
        return {
            r["account_id"]: r["total"] for r in self.db.execute(sql, params)
        }

    def flows(self, start: date | None, end: date) -> dict[int, int]:
        """Raw posting sums per account id within [start, end]."""
        sql = (
            "SELECT p.account_id, SUM(p.amount) AS total FROM postings p "
            "JOIN transactions t ON t.id = p.txn_id "
            "WHERE t.void = 0 AND t.date <= ?"
        )
        params = [end.isoformat()]
        if start:
            sql += " AND t.date >= ?"
            params.append(start.isoformat())
        sql += " GROUP BY p.account_id"
        return {
            r["account_id"]: r["total"] for r in self.db.execute(sql, params)
        }

    def monthly_flows(
        self, account_ids: list[int], start: date, end: date
    ) -> dict[tuple[int, str], int]:
        """Raw flows keyed by (account_id, 'YYYY-MM') within [start, end]."""
        if not account_ids:
            return {}
        marks = ",".join("?" * len(account_ids))
        sql = (
            f"SELECT p.account_id, substr(t.date, 1, 7) AS ym, "
            f"SUM(p.amount) AS total FROM postings p "
            f"JOIN transactions t ON t.id = p.txn_id "
            f"WHERE t.void = 0 AND t.date >= ? AND t.date <= ? "
            f"AND p.account_id IN ({marks}) "
            f"GROUP BY p.account_id, ym"
        )
        params = [start.isoformat(), end.isoformat(), *account_ids]
        return {
            (r["account_id"], r["ym"]): r["total"]
            for r in self.db.execute(sql, params)
        }

    # -- budgets -----------------------------------------------------------

    def set_budget(self, account: Account, amount: int, period: str) -> None:
        if period not in BUDGET_PERIOD_MONTHS:
            raise BeansError(
                f"invalid budget period {period!r} (expected one of "
                f"{', '.join(BUDGET_PERIOD_MONTHS)})"
            )
        if account.type not in (AccountType.INCOME, AccountType.EXPENSE):
            raise BeansError(
                "budgets can only be set on income or expense accounts"
            )
        if amount <= 0:
            raise BeansError("budget amount must be positive")
        with self.db:
            self.db.execute(
                "INSERT INTO budgets (account_id, amount, period) "
                "VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET "
                "amount = excluded.amount, period = excluded.period",
                (account.id, amount, period),
            )

    def budgets(self) -> list[tuple[Account, int, str]]:
        rows = self.db.execute(
            "SELECT a.*, b.amount AS budget_amount, b.period AS budget_period "
            "FROM budgets b JOIN accounts a ON a.id = b.account_id "
            "ORDER BY a.name COLLATE NOCASE"
        ).fetchall()
        return [
            (self._row_to_account(r), r["budget_amount"], r["budget_period"])
            for r in rows
        ]

    def remove_budget(self, account: Account) -> None:
        with self.db:
            cur = self.db.execute(
                "DELETE FROM budgets WHERE account_id = ?", (account.id,)
            )
        if cur.rowcount == 0:
            raise BeansError(f"no budget set for {account.name}")

    # -- recurring transactions ----------------------------------------------

    def add_recurring(
        self,
        name: str,
        frequency: str,
        start: date,
        postings: list[Posting],
        end: date | None = None,
        description: str = "",
        payee: str = "",
        tags: list[str] | None = None,
    ) -> Recurring:
        name = name.strip()
        if not name:
            raise BeansError("a recurring rule needs a name")
        if frequency not in RECURRENCE_FREQUENCIES:
            raise BeansError(
                f"invalid frequency {frequency!r} (expected one of "
                f"{', '.join(RECURRENCE_FREQUENCIES)})"
            )
        if end and end < start:
            raise BeansError("end date is before start date")
        self._check_postings(postings)
        tags = tags or []
        try:
            with self.db:
                cur = self.db.execute(
                    "INSERT INTO recurring "
                    "(name, description, payee, tags, frequency, "
                    "start_date, end_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, description, payee, ",".join(tags), frequency,
                     start.isoformat(), end.isoformat() if end else None),
                )
                rec_id = cur.lastrowid
                self.db.executemany(
                    "INSERT INTO recurring_postings "
                    "(recurring_id, account_id, amount) VALUES (?, ?, ?)",
                    [(rec_id, p.account_id, p.amount) for p in postings],
                )
        except sqlite3.IntegrityError:
            raise BeansError(f"recurring rule {name!r} already exists")
        return self.get_recurring(rec_id)

    def _build_recurring(self, row: sqlite3.Row) -> Recurring:
        postings = [
            Posting(
                id=p["id"],
                account_id=p["account_id"],
                amount=p["amount"],
                account_name=p["name"],
            )
            for p in self.db.execute(
                "SELECT p.*, a.name FROM recurring_postings p "
                "JOIN accounts a ON a.id = p.account_id "
                "WHERE p.recurring_id = ? ORDER BY p.id",
                (row["id"],),
            )
        ]
        return Recurring(
            id=row["id"],
            name=row["name"],
            frequency=row["frequency"],
            start_date=date.fromisoformat(row["start_date"]),
            end_date=(date.fromisoformat(row["end_date"])
                      if row["end_date"] else None),
            occurrences=row["occurrences"],
            active=bool(row["active"]),
            description=row["description"],
            payee=row["payee"],
            tags=[t for t in row["tags"].split(",") if t],
            postings=postings,
        )

    def get_recurring(self, rec_id: int) -> Recurring:
        row = self.db.execute(
            "SELECT * FROM recurring WHERE id = ?", (rec_id,)
        ).fetchone()
        if not row:
            raise BeansError(f"no recurring rule with id {rec_id}")
        return self._build_recurring(row)

    def recurrings(self) -> list[Recurring]:
        rows = self.db.execute(
            "SELECT * FROM recurring ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [self._build_recurring(r) for r in rows]

    def find_recurring(self, query: str) -> Recurring:
        query = query.strip()
        row = self.db.execute(
            "SELECT * FROM recurring WHERE name = ? COLLATE NOCASE", (query,)
        ).fetchone()
        if row:
            return self._build_recurring(row)
        candidates = self.recurrings()
        q = query.lower()
        sub = [r for r in candidates if q in r.name.lower()]
        if len(sub) == 1:
            return sub[0]
        if sub:
            names = ", ".join(r.name for r in sub[:6])
            raise BeansError(f"recurring rule {query!r} is ambiguous: {names}")
        raise BeansError(
            f"no recurring rule matches {query!r} (see `beans recur list`)"
        )

    def set_recurring_active(self, rec: Recurring, active: bool) -> None:
        with self.db:
            self.db.execute(
                "UPDATE recurring SET active = ? WHERE id = ?",
                (int(active), rec.id),
            )
        rec.active = active

    def set_recurring_occurrences(self, rec: Recurring, count: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE recurring SET occurrences = ? WHERE id = ?",
                (count, rec.id),
            )
        rec.occurrences = count

    def remove_recurring(self, rec: Recurring) -> None:
        with self.db:
            self.db.execute("DELETE FROM recurring WHERE id = ?", (rec.id,))
