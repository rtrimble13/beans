"""Match a bank/credit-card statement against the ledger, line by line.

`beans reconcile --statement` compares the rows of a statement export
against the account's postings and sorts every line into one of a few
classes. It is strictly read-only: nothing here writes to the ledger.

The matcher is deliberately conservative about money and generous about
dates. **The amount must be equal for a row and a posting to pair up** —
in double-entry an amount difference is a finding, not a match, so fuzz
is never allowed to absorb one. The give is on the two axes where drift
is legitimate:

* the date, because banks post a day or several after you record an
  entry (and because a recurring entry booked to the 1st of the month
  routinely settles a few days either side of it), and
* the description, because `WHOLE FOODS MARKET #412` and `Whole Foods`
  are the same merchant.

Matching runs in ordered passes so that the same file always produces
the same report:

1. equal amount and equal date          -> matched (exact)
2. equal amount, date within the window -> matched (date drift)
3. similar description, date within the
   window, but a *different* amount     -> amount mismatch
4. whatever is left over                -> bank-only / ledger-only

Each pass claims its pairs globally before the next one starts, and
within a pass the best candidate is the nearest date, then the closest
description, then the lowest transaction id — so no result depends on
dictionary or row ordering.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from beans.ledger import Ledger
from beans.models import Account
from beans.utils import BeansError, parse_amount, parse_date

# Days either side of a ledger entry in which a statement line with the
# same amount still counts as the same transaction. Five covers both the
# usual ACH posting lag and a month-boundary recurring entry booked to
# the 1st that the bank settled on the 28th-31st before it.
DEFAULT_WINDOW = 5

# How alike two normalized descriptions must be before an *amount*
# difference is reported as a mismatch rather than as two unrelated
# lines. Only ever used to pair rows that already failed on amount.
DESC_THRESHOLD = 0.6

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_DIGIT_RUN = re.compile(r"\b\d{2,}\b")


def normalize(text: str) -> str:
    """Reduce a description to comparable words: lowercase, punctuation
    dropped, and store/reference numbers removed, so `WHOLE FOODS
    MARKET #412` and `Whole Foods Market` both become `whole foods
    market`."""
    lowered = _PUNCT.sub(" ", (text or "").lower())
    return " ".join(_DIGIT_RUN.sub(" ", lowered).split())


def similarity(left: str, right: str) -> float:
    """0.0-1.0 likeness of two raw descriptions. A containment (one is a
    prefix/substring of the other, as with a truncated bank memo) scores
    1.0; otherwise fall back to a character-level ratio."""
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class StatementRow:
    """One line of the statement export, in the ledger's posting
    convention: debit-positive, i.e. money into the account is positive
    (the same convention `beans import` reads)."""

    line: int
    date: date
    description: str
    amount: int
    # Whatever the row already carried in its category column, if any —
    # a decision already made, which nothing downstream overrides.
    category: str = ""


@dataclass
class LedgerRow:
    """One of the account's postings, as a matching candidate."""

    txn_id: int
    date: date
    description: str
    amount: int
    cleared: bool


@dataclass
class Match:
    statement: StatementRow
    ledger: LedgerRow
    tier: str  # "exact" | "drift" | "mismatch"

    @property
    def date_drift(self) -> int:
        """Statement date minus ledger date, in days."""
        return (self.statement.date - self.ledger.date).days

    @property
    def amount_delta(self) -> int:
        return self.statement.amount - self.ledger.amount


@dataclass
class MatchResult:
    account: Account
    window: int
    rows: list[StatementRow] = field(default_factory=list)
    matched: list[Match] = field(default_factory=list)
    mismatched: list[Match] = field(default_factory=list)
    bank_only: list[StatementRow] = field(default_factory=list)
    ledger_only: list[LedgerRow] = field(default_factory=list)

    @property
    def drifted(self) -> list[Match]:
        """Matches that paired on a nearby rather than an equal date."""
        return [m for m in self.matched if m.tier == "drift"]

    @property
    def outstanding(self) -> list[LedgerRow]:
        """In the ledger, not on the statement, and not yet cleared —
        an outstanding check or a deposit in transit, or an entry that
        should not be there."""
        return [r for r in self.ledger_only if not r.cleared]

    @property
    def cleared_missing(self) -> list[LedgerRow]:
        """Already marked cleared, yet absent from this statement. Always
        worth a look: a posting cannot have cleared against a statement
        that does not contain it."""
        return [r for r in self.ledger_only if r.cleared]

    @property
    def statement_total(self) -> int:
        return sum(r.amount for r in self.rows)

    @property
    def start(self) -> date | None:
        return min((r.date for r in self.rows), default=None)

    @property
    def end(self) -> date | None:
        return max((r.date for r in self.rows), default=None)


# -- reading the statement ---------------------------------------------------


def resolve_columns(fieldnames: list[str] | None, path: str,
                    required: list[str]) -> dict[str, str]:
    """Map lowercased column names to the file's actual header spelling,
    erroring if a required column is missing. Shared by the importer and
    the statement matcher so the two can never disagree about how a bank
    export's headers are resolved."""
    if fieldnames is None:
        raise BeansError(f"{path} is empty or has no header row")
    fields = {f.strip().lower(): f for f in fieldnames}
    for col in required:
        if col.lower() not in fields:
            raise BeansError(
                f"column {col!r} not found in {path} "
                f"(columns: {', '.join(fieldnames)})"
            )
    return fields


def read_statement(path: str, decimals: int, date_col: str = "date",
                   desc_col: str = "description",
                   amount_col: str = "amount",
                   category_col: str = "category",
                   invert: bool = False) -> list[StatementRow]:
    """Parse a statement export into rows in posting convention.

    `invert` flips every amount, for the many credit-card exports that
    report a purchase as a positive number.
    """
    file = Path(path).expanduser()
    if not file.exists():
        raise BeansError(f"file not found: {path}")
    sign = -1 if invert else 1
    rows: list[StatementRow] = []
    with file.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = resolve_columns(reader.fieldnames, path,
                                 required=[date_col, amount_col])
        for lineno, raw in enumerate(reader, start=2):
            raw_date = (raw.get(fields[date_col.lower()]) or "").strip()
            raw_amount = (raw.get(fields[amount_col.lower()]) or "").strip()
            if not raw_date and not raw_amount:
                continue  # blank line
            try:
                when = parse_date(raw_date)
                amount = parse_amount(raw_amount, decimals)
            except BeansError as exc:
                raise BeansError(f"{path}:{lineno}: {exc}")
            if amount == 0:
                continue
            desc = (raw.get(fields.get(desc_col.lower(), ""), "")
                    or "").strip()
            category = (raw.get(fields.get(category_col.lower(), ""), "")
                        or "").strip()
            rows.append(StatementRow(lineno, when, desc, amount * sign,
                                     category))
    if not rows:
        raise BeansError(f"{path} has no data rows")
    return rows


def ledger_candidates(led: Ledger, account: Account,
                      rows: list[StatementRow],
                      window: int) -> list[LedgerRow]:
    """The account's postings that could plausibly belong to this
    statement: everything dated within the matching window of the period
    the statement covers."""
    start = min(r.date for r in rows) - timedelta(days=window)
    end = max(r.date for r in rows) + timedelta(days=window)
    return [
        LedgerRow(r["txn_id"], r["date"], r["description"] or r["payee"],
                  r["amount"], bool(r["cleared"]))
        for r in led.postings_in_range(account, start, end)
    ]


# -- the matcher -------------------------------------------------------------


def _best(row: StatementRow, pool: list[LedgerRow], window: int,
          same_amount: bool) -> LedgerRow | None:
    """The strongest remaining candidate for one statement row, or None.

    Ranked by nearest date, then closest description, then lowest
    transaction id — a total order, so the choice never depends on the
    order the pool happens to be in.
    """
    best, best_key = None, None
    for cand in pool:
        drift = abs((row.date - cand.date).days)
        if drift > window:
            continue
        if same_amount:
            if cand.amount != row.amount:
                continue
            score = similarity(row.description, cand.description)
        else:
            if cand.amount == row.amount:
                continue  # exact-amount pairs belong to the earlier passes
            score = similarity(row.description, cand.description)
            if score < DESC_THRESHOLD:
                continue
        key = (drift, -score, cand.txn_id)
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return best


def match_statement(led: Ledger, account: Account, rows: list[StatementRow],
                    window: int = DEFAULT_WINDOW) -> MatchResult:
    """Sort every statement row and candidate posting into a class.

    Read-only: this reads the ledger and returns a report, and never
    marks anything cleared or writes a transaction.
    """
    if account.currency:
        raise BeansError(
            f"{account.name} is denominated in {account.currency}; "
            "statement matching is base-currency only for now"
        )
    if window < 0:
        raise BeansError("--window cannot be negative")
    result = MatchResult(account=account, window=window, rows=list(rows))
    pool = ledger_candidates(led, account, rows, window)
    pending = sorted(rows, key=lambda r: (r.date, r.line))

    for tier, same_amount, span in (("exact", True, 0),
                                    ("drift", True, window),
                                    ("mismatch", False, window)):
        still_pending: list[StatementRow] = []
        for row in pending:
            found = _best(row, pool, span, same_amount)
            if found is None:
                still_pending.append(row)
                continue
            pool.remove(found)
            bucket = (result.mismatched if tier == "mismatch"
                      else result.matched)
            bucket.append(Match(row, found, tier))
        pending = still_pending

    result.bank_only = pending
    result.ledger_only = sorted(pool, key=lambda r: (r.date, r.txn_id))
    result.matched.sort(key=lambda m: (m.statement.date, m.statement.line))
    result.mismatched.sort(key=lambda m: (m.statement.date, m.statement.line))
    return result


# -- the editable hand-off file ----------------------------------------------


def write_unmatched_csv(led: Ledger, result: MatchResult, path: str,
                        force: bool = False) -> int:
    """Write the bank-only rows as a CSV that `beans import` can read.

    Delegates the "which account is this?" question to
    `beans.classify`, the same classifier `beans categorize` uses, so a
    row prepared by either route gets the same answer and the same
    stated confidence.

    Returns the number of rows written.
    """
    from beans.classify import Classifier, write_prepared_csv

    classifier = Classifier(led, result.account)
    rows = sorted(result.bank_only, key=lambda r: (r.date, r.line))
    return write_prepared_csv(led, classifier, rows, path, force=force)
