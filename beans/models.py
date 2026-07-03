"""Domain model: account types, accounts, transactions, postings."""

from __future__ import annotations

import datetime
import enum
from dataclasses import dataclass, field
from decimal import Decimal


class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"

    @property
    def natural_sign(self) -> int:
        """+1 for debit-normal accounts (assets, expenses), -1 otherwise.

        Posting amounts are stored debit-positive / credit-negative; a
        natural balance multiplies the raw sum by this sign so every
        account reads positive in its normal state.
        """
        return 1 if self in (AccountType.ASSET, AccountType.EXPENSE) else -1

    @property
    def default_cashflow(self) -> str:
        """Default statement-of-cash-flows activity for the account type."""
        if self in (AccountType.INCOME, AccountType.EXPENSE):
            return "operating"
        if self is AccountType.ASSET:
            return "investing"
        return "financing"

    @property
    def label(self) -> str:
        return {
            AccountType.ASSET: "Assets",
            AccountType.LIABILITY: "Liabilities",
            AccountType.EQUITY: "Equity",
            AccountType.INCOME: "Income",
            AccountType.EXPENSE: "Expenses",
        }[self]


CASHFLOW_CATEGORIES = ("operating", "investing", "financing")

# Balance-sheet liquidity classification for assets and liabilities:
# `current` = realizable/due within a year, `noncurrent` = beyond a year.
LIQUIDITY_CLASSES = ("current", "noncurrent")


@dataclass
class Account:
    id: int
    name: str
    type: AccountType
    is_cash: bool = False
    cf_category: str | None = None
    closed: bool = False
    description: str = ""
    currency: str | None = None  # denomination; None = the base currency
    liquidity: str = "current"  # current | noncurrent (assets & liabilities)

    @property
    def cashflow(self) -> str:
        return self.cf_category or self.type.default_cashflow

    @property
    def is_current(self) -> bool:
        return self.liquidity == "current"

    @property
    def leaf(self) -> str:
        return self.name.rsplit(":", 1)[-1]


@dataclass
class Posting:
    account_id: int
    amount: int  # minor units of the base currency, debit-positive
    id: int | None = None
    account_name: str = ""
    cleared: bool = False  # confirmed against a bank statement
    # Minor units of the account's own currency, for postings on
    # foreign-denominated accounts (None on base-currency accounts).
    foreign_amount: int | None = None


@dataclass
class Transaction:
    id: int
    date: datetime.date
    description: str
    payee: str = ""
    tags: list[str] = field(default_factory=list)
    void: bool = False
    postings: list[Posting] = field(default_factory=list)


@dataclass
class Loan:
    """An amortizing loan attached to a liability account. The terms drive a
    standard amortization schedule; the schedule is used only to split the
    account's ledger balance into a current portion (principal due within a
    year) and a non-current remainder — the balance itself always comes from
    the ledger."""

    id: int
    account_id: int
    principal: int  # original principal, minor units
    annual_rate: Decimal  # nominal annual rate, e.g. Decimal('0.0625')
    term_months: int  # number of scheduled payments
    payment: int  # scheduled payment, minor units
    start_date: datetime.date
    frequency: str = "monthly"
    account_name: str = ""


RECURRENCE_FREQUENCIES = (
    "daily", "weekly", "biweekly", "monthly", "quarterly", "yearly",
)


@dataclass
class Recurring:
    """A scheduled transaction template posted on a fixed cadence."""

    id: int
    name: str
    frequency: str
    start_date: datetime.date
    end_date: datetime.date | None = None
    occurrences: int = 0  # how many instances have been posted
    active: bool = True
    description: str = ""
    payee: str = ""
    tags: list[str] = field(default_factory=list)
    postings: list[Posting] = field(default_factory=list)
