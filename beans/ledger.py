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
from decimal import Decimal

from beans.utils import (
    BeansError,
    currency_decimals,
    foreign_from_base,
    format_amount,
)

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
    description TEXT NOT NULL DEFAULT '',
    currency    TEXT
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
    id             INTEGER PRIMARY KEY,
    txn_id         INTEGER NOT NULL REFERENCES transactions(id)
                   ON DELETE CASCADE,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    amount         INTEGER NOT NULL,
    cleared        INTEGER NOT NULL DEFAULT 0,
    foreign_amount INTEGER
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
CREATE TABLE IF NOT EXISTS import_rules (
    id         INTEGER PRIMARY KEY,
    pattern    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    account_id INTEGER NOT NULL REFERENCES accounts(id)
);
CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    target      INTEGER NOT NULL,
    target_date TEXT NOT NULL,
    created     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lots (
    id         INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    symbol     TEXT NOT NULL COLLATE NOCASE,
    quantity   TEXT NOT NULL,
    cost       INTEGER NOT NULL,
    acquired   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prices (
    id     INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL COLLATE NOCASE,
    date   TEXT NOT NULL,
    price  INTEGER NOT NULL,
    UNIQUE (symbol, date)
);
CREATE TABLE IF NOT EXISTS fx_rates (
    id       INTEGER PRIMARY KEY,
    currency TEXT NOT NULL COLLATE NOCASE,
    date     TEXT NOT NULL,
    rate     TEXT NOT NULL,
    UNIQUE (currency, date)
);
CREATE INDEX IF NOT EXISTS idx_postings_txn ON postings(txn_id);
CREATE INDEX IF NOT EXISTS idx_postings_account ON postings(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_lots_symbol ON lots(symbol);
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
        self._migrate()

    def _migrate(self) -> None:
        """Bring ledgers created by older versions up to date. New tables
        come from the IF NOT EXISTS bootstrap; new columns are added here."""
        posting_cols = {r["name"]
                        for r in self.db.execute("PRAGMA table_info(postings)")}
        account_cols = {r["name"]
                        for r in self.db.execute("PRAGMA table_info(accounts)")}
        with self.db:
            if "cleared" not in posting_cols:
                self.db.execute(
                    "ALTER TABLE postings ADD COLUMN "
                    "cleared INTEGER NOT NULL DEFAULT 0"
                )
            if "foreign_amount" not in posting_cols:
                self.db.execute(
                    "ALTER TABLE postings ADD COLUMN foreign_amount INTEGER"
                )
            if "currency" not in account_cols:
                self.db.execute(
                    "ALTER TABLE accounts ADD COLUMN currency TEXT"
                )

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
            currency=row["currency"],
        )

    def add_account(
        self,
        name: str,
        type_: AccountType,
        is_cash: bool = False,
        cf_category: str | None = None,
        description: str = "",
        currency: str | None = None,
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
        if currency:
            currency = currency.upper().strip()
            if not currency.isalpha() or len(currency) != 3:
                raise BeansError(
                    f"invalid currency code {currency!r} (use an ISO code "
                    "like EUR)"
                )
            if currency == self.currency:
                currency = None  # the base currency needs no denomination
            elif type_ not in (AccountType.ASSET, AccountType.LIABILITY):
                raise BeansError(
                    "only asset and liability accounts can be denominated "
                    "in a foreign currency (income and expenses are always "
                    "recorded in the base currency)"
                )
        try:
            with self.db:
                cur = self.db.execute(
                    "INSERT INTO accounts "
                    "(name, type, is_cash, cf_category, description, "
                    "currency) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, type_.value, int(is_cash), cf_category,
                     description, currency),
                )
        except sqlite3.IntegrityError:
            raise BeansError(f"account {name!r} already exists")
        return Account(cur.lastrowid, name, type_, is_cash, cf_category,
                       False, description, currency)

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

    # -- period close ------------------------------------------------------

    @property
    def closed_through(self) -> date | None:
        value = self.get_meta("closed_through")
        return date.fromisoformat(value) if value else None

    def close_books(self, through: date) -> None:
        current = self.closed_through
        if current and through < current:
            raise BeansError(
                f"books are already closed through {current.isoformat()}; "
                "reopen first with `beans period reopen`"
            )
        self.set_meta("closed_through", through.isoformat())

    def reopen_books(self) -> None:
        if self.closed_through is None:
            raise BeansError("the books are not closed")
        with self.db:
            self.db.execute(
                "DELETE FROM meta WHERE key = 'closed_through'"
            )

    def _check_not_closed(self, when: date, action: str) -> None:
        closed = self.closed_through
        if closed and when <= closed:
            raise BeansError(
                f"cannot {action} dated {when.isoformat()}: the books are "
                f"closed through {closed.isoformat()} "
                "(see `beans period reopen`)"
            )

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

    def _derive_foreign_amounts(self, postings: list[Posting],
                                when: date) -> None:
        """Fill in foreign_amount for postings on foreign-denominated
        accounts, converting the base amount at the latest exchange rate
        on or before the transaction date (explicit amounts win)."""
        currencies = {
            r["id"]: r["currency"]
            for r in self.db.execute(
                f"SELECT id, currency FROM accounts WHERE id IN "
                f"({','.join('?' * len(postings))})",
                [p.account_id for p in postings],
            )
        }
        for p in postings:
            code = currencies.get(p.account_id)
            if not code:
                p.foreign_amount = None
                continue
            if p.foreign_amount is not None:
                continue
            latest = self.latest_fx_rate(code, as_of=when)
            if latest is None:
                raise BeansError(
                    f"no exchange rate for {code} — set one with "
                    f"`beans currency set {code} RATE` (or pass the "
                    "foreign amount explicitly)"
                )
            p.foreign_amount = foreign_from_base(
                p.amount, latest[1], self.decimals, currency_decimals(code))

    def _insert_transaction(
        self,
        when: date,
        description: str,
        postings: list[Posting],
        payee: str,
        tags: list[str],
    ) -> int:
        """INSERT a transaction and its postings; the caller owns the
        surrounding database transaction."""
        self._derive_foreign_amounts(postings, when)
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
            "INSERT INTO postings (txn_id, account_id, amount, "
            "foreign_amount) VALUES (?, ?, ?, ?)",
            [(txn_id, p.account_id, p.amount, p.foreign_amount)
             for p in postings],
        )
        return txn_id

    def add_transaction(
        self,
        when: date,
        description: str,
        postings: list[Posting],
        payee: str = "",
        tags: list[str] | None = None,
    ) -> Transaction:
        self._check_postings(postings)
        self._check_not_closed(when, "record a transaction")
        tags = tags or []
        with self.db:
            txn_id = self._insert_transaction(when, description, postings,
                                              payee, tags)
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
                cleared=bool(p["cleared"]),
                foreign_amount=p["foreign_amount"],
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

    def _build_transactions(self, rows: list[sqlite3.Row]) -> list[Transaction]:
        """Build Transactions for many rows with one postings query per
        chunk instead of one per transaction."""
        postings_by_txn: dict[int, list[Posting]] = {r["id"]: [] for r in rows}
        ids = list(postings_by_txn)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for p in self.db.execute(
                f"SELECT p.*, a.name FROM postings p "
                f"JOIN accounts a ON a.id = p.account_id "
                f"WHERE p.txn_id IN ({marks}) ORDER BY p.id",
                chunk,
            ):
                postings_by_txn[p["txn_id"]].append(Posting(
                    id=p["id"],
                    account_id=p["account_id"],
                    amount=p["amount"],
                    account_name=p["name"],
                    cleared=bool(p["cleared"]),
                    foreign_amount=p["foreign_amount"],
                ))
        return [
            Transaction(
                id=row["id"],
                date=date.fromisoformat(row["date"]),
                description=row["description"],
                payee=row["payee"],
                tags=[t for t in row["tags"].split(",") if t],
                void=bool(row["void"]),
                postings=postings_by_txn[row["id"]],
            )
            for row in rows
        ]

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
        if limit:
            # Newest N, fetched in SQL, then restored to chronological order.
            sql += " ORDER BY t.date DESC, t.id DESC LIMIT ?"
            params.append(limit)
            rows = list(reversed(self.db.execute(sql, params).fetchall()))
        else:
            sql += " ORDER BY t.date, t.id"
            rows = self.db.execute(sql, params).fetchall()
        return self._build_transactions(rows)

    def void_transaction(self, txn_id: int) -> Transaction:
        txn = self.get_transaction(txn_id)
        if txn.void:
            raise BeansError(f"transaction {txn_id} is already void")
        self._check_not_closed(txn.date, "void a transaction")
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

    def type_totals(self, amounts: dict[int, int]) -> dict[AccountType, int]:
        """Natural-sign totals per account type for a raw balances/flows
        map — the one place the sign convention is applied in aggregate."""
        accounts = {a.id: a for a in self.accounts(include_closed=True)}
        totals = {t: 0 for t in AccountType}
        for acct_id, amount in amounts.items():
            account = accounts.get(acct_id)
            if account:
                totals[account.type] += amount * account.type.natural_sign
        return totals

    def position(self, as_of: date | None = None,
                 raw: dict[int, int] | None = None) -> dict[str, int]:
        """Snapshot of assets, liabilities, cash, and net worth (natural
        signs). Pass `raw` to reuse an existing balances() result."""
        if raw is None:
            raw = self.balances(as_of=as_of)
        totals = self.type_totals(raw)
        accounts = {a.id: a for a in self.accounts(include_closed=True)}
        cash = sum(v for k, v in raw.items()
                   if k in accounts and accounts[k].is_cash)
        assets = totals[AccountType.ASSET]
        liabilities = totals[AccountType.LIABILITY]
        return {
            "assets": assets,
            "liabilities": liabilities,
            "cash": cash,
            "net_worth": assets - liabilities,
        }

    def monthly_type_totals(self, end: date) -> dict[str, dict[str, int]]:
        """Raw posting sums grouped by 'YYYY-MM' and account type through
        end — one scan that supports running month-end balances."""
        out: dict[str, dict[str, int]] = {}
        for row in self.db.execute(
            "SELECT substr(t.date, 1, 7) AS ym, a.type, "
            "SUM(p.amount) AS total FROM postings p "
            "JOIN transactions t ON t.id = p.txn_id "
            "JOIN accounts a ON a.id = p.account_id "
            "WHERE t.void = 0 AND t.date <= ? GROUP BY ym, a.type",
            (end.isoformat(),),
        ):
            out.setdefault(row["ym"], {})[row["type"]] = row["total"]
        return out

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

    def post_recurring_instance(self, rec: Recurring, due: date) -> Transaction:
        """Post one instance of a rule and advance its occurrence counter
        in a single database transaction, so an interrupted run can never
        repost an instance that already committed."""
        postings = [Posting(account_id=p.account_id, amount=p.amount)
                    for p in rec.postings]
        self._check_postings(postings)
        self._check_not_closed(due, "post a recurring instance")
        tags = rec.tags + ["recurring"]
        description = rec.description or rec.name
        with self.db:
            txn_id = self._insert_transaction(due, description, postings,
                                              rec.payee, tags)
            self.db.execute(
                "UPDATE recurring SET occurrences = occurrences + 1 "
                "WHERE id = ?",
                (rec.id,),
            )
        rec.occurrences += 1
        return Transaction(txn_id, due, description, rec.payee, tags,
                           False, postings)

    def remove_recurring(self, rec: Recurring) -> None:
        with self.db:
            self.db.execute("DELETE FROM recurring WHERE id = ?", (rec.id,))

    # -- search and undo -----------------------------------------------------

    def search_transactions(self, query: str,
                            limit: int | None = None) -> list[Transaction]:
        pattern = f"%{query}%"
        sql = (
            "SELECT * FROM transactions WHERE void = 0 AND "
            "(description LIKE ? OR payee LIKE ? OR tags LIKE ?)"
        )
        params: list = [pattern, pattern, pattern]
        if limit:
            sql += " ORDER BY date DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = list(reversed(self.db.execute(sql, params).fetchall()))
        else:
            sql += " ORDER BY date, id"
            rows = self.db.execute(sql, params).fetchall()
        return self._build_transactions(rows)

    def last_transaction(self) -> Transaction:
        row = self.db.execute(
            "SELECT * FROM transactions WHERE void = 0 "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise BeansError("no transactions to undo")
        return self._build_transaction(row)

    # -- reconciliation ------------------------------------------------------

    def set_cleared(
        self,
        account: Account,
        txn_ids: list[int] | None = None,
        through: date | None = None,
        cleared: bool = True,
    ) -> int:
        """Mark this account's postings cleared (or not). Selects either
        explicit transaction ids or everything dated through a date."""
        if not txn_ids and not through:
            raise BeansError(
                "specify transaction ids or --through DATE to clear"
            )
        sql = (
            "UPDATE postings SET cleared = ? WHERE account_id = ? "
            "AND txn_id IN (SELECT id FROM transactions WHERE void = 0"
        )
        params: list = [int(cleared), account.id]
        if through:
            sql += " AND date <= ?"
            params.append(through.isoformat())
        if txn_ids:
            sql += f" AND id IN ({','.join('?' * len(txn_ids))})"
            params.extend(txn_ids)
        sql += ")"
        with self.db:
            cur = self.db.execute(sql, params)
        if txn_ids and cur.rowcount == 0:
            raise BeansError(
                f"no postings on {account.name} match those transaction ids"
            )
        return cur.rowcount

    def cleared_balance(self, account: Account,
                        as_of: date | None = None) -> int:
        sql = (
            "SELECT COALESCE(SUM(p.amount), 0) AS total FROM postings p "
            "JOIN transactions t ON t.id = p.txn_id "
            "WHERE t.void = 0 AND p.cleared = 1 AND p.account_id = ?"
        )
        params: list = [account.id]
        if as_of:
            sql += " AND t.date <= ?"
            params.append(as_of.isoformat())
        return self.db.execute(sql, params).fetchone()["total"]

    def uncleared_postings(
        self, account: Account, as_of: date | None = None
    ) -> list[dict]:
        """Uncleared postings on the account, oldest first, as plain rows
        (one query — reconciliation only needs these fields)."""
        sql = (
            "SELECT t.id AS txn_id, t.date, t.description, t.payee, "
            "p.amount FROM postings p "
            "JOIN transactions t ON t.id = p.txn_id "
            "WHERE t.void = 0 AND p.cleared = 0 AND p.account_id = ?"
        )
        params: list = [account.id]
        if as_of:
            sql += " AND t.date <= ?"
            params.append(as_of.isoformat())
        sql += " ORDER BY t.date, t.id, p.id"
        return [
            {
                "txn_id": r["txn_id"],
                "date": date.fromisoformat(r["date"]),
                "description": r["description"],
                "payee": r["payee"],
                "amount": r["amount"],
            }
            for r in self.db.execute(sql, params)
        ]

    # -- import rules --------------------------------------------------------

    def add_import_rule(self, pattern: str, account: Account) -> None:
        pattern = pattern.strip()
        if not pattern:
            raise BeansError("an import rule needs a pattern")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO import_rules (pattern, account_id) "
                    "VALUES (?, ?)",
                    (pattern, account.id),
                )
        except sqlite3.IntegrityError:
            raise BeansError(f"an import rule for {pattern!r} already exists")

    def import_rules(self) -> list[tuple[int, str, Account]]:
        rows = self.db.execute(
            "SELECT r.id AS rule_id, r.pattern, a.* FROM import_rules r "
            "JOIN accounts a ON a.id = r.account_id ORDER BY r.id"
        ).fetchall()
        return [(r["rule_id"], r["pattern"], self._row_to_account(r))
                for r in rows]

    def remove_import_rule(self, pattern: str) -> None:
        with self.db:
            cur = self.db.execute(
                "DELETE FROM import_rules WHERE pattern = ? COLLATE NOCASE",
                (pattern.strip(),),
            )
        if cur.rowcount == 0:
            raise BeansError(f"no import rule matches {pattern!r}")

    def match_import_rule(self, description: str,
                          rules: list | None = None) -> Account | None:
        """First rule whose pattern appears in the description, if any.
        Pass prefetched `rules` (from import_rules()) when matching many
        descriptions to avoid re-querying per call."""
        haystack = description.lower()
        if rules is None:
            rules = self.import_rules()
        for _id, pattern, account in rules:
            if pattern.lower() in haystack:
                return account
        return None

    # -- goals ---------------------------------------------------------------

    def add_goal(self, name: str, account: Account, target: int,
                 target_date: date) -> None:
        name = name.strip()
        if not name:
            raise BeansError("a goal needs a name")
        if account.type not in (AccountType.ASSET, AccountType.LIABILITY):
            raise BeansError(
                "goals track asset or liability accounts "
                "(savings targets or debt payoff)"
            )
        if target < 0:
            raise BeansError("goal target cannot be negative")
        if target_date <= date.today():
            raise BeansError("goal target date must be in the future")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO goals "
                    "(name, account_id, target, target_date, created) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, account.id, target, target_date.isoformat(),
                     datetime.now().isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            raise BeansError(f"goal {name!r} already exists")

    def goals(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT g.id AS goal_id, g.name AS goal_name, g.target, "
            "g.target_date, a.* FROM goals g "
            "JOIN accounts a ON a.id = g.account_id "
            "ORDER BY g.target_date, g.name COLLATE NOCASE"
        ).fetchall()
        return [
            {
                "id": r["goal_id"],
                "name": r["goal_name"],
                "target": r["target"],
                "target_date": date.fromisoformat(r["target_date"]),
                "account": self._row_to_account(r),
            }
            for r in rows
        ]

    def remove_goal(self, name: str) -> None:
        with self.db:
            cur = self.db.execute(
                "DELETE FROM goals WHERE name = ? COLLATE NOCASE",
                (name.strip(),),
            )
        if cur.rowcount == 0:
            raise BeansError(f"no goal named {name!r}")

    # -- investment lots and prices --------------------------------------------

    def add_lot(self, account: Account, symbol: str, quantity: str,
                cost: int, acquired: date) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO lots (account_id, symbol, quantity, cost, "
                "acquired) VALUES (?, ?, ?, ?, ?)",
                (account.id, symbol.upper(), quantity, cost,
                 acquired.isoformat()),
            )

    def lots(self, account: Account | None = None,
             symbol: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM lots"
        clauses, params = [], []
        if account:
            clauses.append("account_id = ?")
            params.append(account.id)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY acquired, id"
        return self.db.execute(sql, params).fetchall()

    def update_lot(self, lot_id: int, quantity: str, cost: int) -> None:
        with self.db:
            self.db.execute(
                "UPDATE lots SET quantity = ?, cost = ? WHERE id = ?",
                (quantity, cost, lot_id),
            )

    def delete_lot(self, lot_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM lots WHERE id = ?", (lot_id,))

    def set_price(self, symbol: str, when: date, price: int) -> None:
        if price <= 0:
            raise BeansError("price must be positive")
        with self.db:
            self.db.execute(
                "INSERT INTO prices (symbol, date, price) VALUES (?, ?, ?) "
                "ON CONFLICT(symbol, date) DO UPDATE SET "
                "price = excluded.price",
                (symbol.upper(), when.isoformat(), price),
            )

    def latest_price(self, symbol: str,
                     as_of: date | None = None) -> tuple[date, int] | None:
        sql = "SELECT date, price FROM prices WHERE symbol = ?"
        params: list = [symbol.upper()]
        if as_of:
            sql += " AND date <= ?"
            params.append(as_of.isoformat())
        sql += " ORDER BY date DESC LIMIT 1"
        row = self.db.execute(sql, params).fetchone()
        if not row:
            return None
        return date.fromisoformat(row["date"]), row["price"]

    def prices(self, symbol: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM prices"
        params: list = []
        if symbol:
            sql += " WHERE symbol = ?"
            params.append(symbol.upper())
        sql += " ORDER BY symbol, date"
        return self.db.execute(sql, params).fetchall()

    # -- exchange rates --------------------------------------------------------

    def set_fx_rate(self, code: str, when: date, rate: Decimal) -> None:
        code = code.upper().strip()
        if code == self.currency:
            raise BeansError(
                f"{code} is the ledger's base currency — rates are quoted "
                "as base units per foreign unit"
            )
        with self.db:
            self.db.execute(
                "INSERT INTO fx_rates (currency, date, rate) "
                "VALUES (?, ?, ?) ON CONFLICT(currency, date) DO UPDATE "
                "SET rate = excluded.rate",
                (code, when.isoformat(), str(rate)),
            )

    def latest_fx_rate(self, code: str,
                       as_of: date | None = None) -> tuple[date, Decimal] | None:
        sql = "SELECT date, rate FROM fx_rates WHERE currency = ?"
        params: list = [code.upper()]
        if as_of:
            sql += " AND date <= ?"
            params.append(as_of.isoformat())
        sql += " ORDER BY date DESC LIMIT 1"
        row = self.db.execute(sql, params).fetchone()
        if not row:
            return None
        return date.fromisoformat(row["date"]), Decimal(row["rate"])

    def fx_rates(self, code: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM fx_rates"
        params: list = []
        if code:
            sql += " WHERE currency = ?"
            params.append(code.upper())
        sql += " ORDER BY currency, date"
        return self.db.execute(sql, params).fetchall()

    def foreign_balances(self, as_of: date | None = None) -> dict[int, int]:
        """Foreign-currency balance (minor units of the account's own
        currency) per foreign-denominated account id."""
        sql = (
            "SELECT p.account_id, SUM(p.foreign_amount) AS total "
            "FROM postings p JOIN transactions t ON t.id = p.txn_id "
            "WHERE t.void = 0 AND p.foreign_amount IS NOT NULL"
        )
        params: list = []
        if as_of:
            sql += " AND t.date <= ?"
            params.append(as_of.isoformat())
        sql += " GROUP BY p.account_id"
        return {
            r["account_id"]: r["total"] for r in self.db.execute(sql, params)
        }
