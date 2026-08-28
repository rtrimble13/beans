"""Suggest a counter-account for each row of a bank export, and say how
sure it is.

A bank export carries a date, a description and an amount — never a
beans account name. Something has to supply that name. `beans` has three
sources, and this module puts them in order of how much they know:

1. **the row's own category column** — a decision already made, so it
   wins outright and is never second-guessed;
2. **a saved import rule** — standing intent ("from now on, WHOLE FOODS
   is Groceries"), which beats inference because it is explicit;
3. **the ledger's own history** — how you categorized this same merchant
   the last forty times, read straight out of the register.

(3) is what makes rules optional rather than mandatory: a rule is a
hand-maintained cache of a decision your books already record. But it
only works once there *is* history, so rules still carry a new ledger,
and still express intent that history cannot know yet — a brand-new
merchant, or a deliberate re-categorization going forward.

Every suggestion carries a **confidence** and, more usefully, the
**basis** it rests on. The number alone hides an important distinction:

    AMAZON MKTPLACE    Expenses:Shopping  0.63  17 prior: 14 Shopping / 3 Cloud
    UNITED AIRLINES    Expenses:Travel    0.60  3 prior

Those score the same for opposite reasons — the first has plenty of
evidence that disagrees (it genuinely depends on the transaction, and
more history will not settle it), the second has barely any evidence yet
(it will firm up on its own). Printing the basis next to the score is
what lets you tell them apart, so both are always emitted together.

Confidence is a **ranking heuristic, not a calibrated probability**. Its
job is to sort your attention — review the bottom of the list — and it
is deliberately not wired to any auto-accept threshold: the point of
producing a file is that a person reads it before it reaches the ledger.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path

from beans.ledger import Ledger
from beans.models import Account
from beans.render import Table, bold, money, red
from beans.utils import BeansError

# Damps confidence when the evidence is thin: with a unanimous history a
# single prior scores 0.33, three score 0.60, ten score 0.83. Without it
# one lucky observation would look as certain as forty.
EVIDENCE_DAMPING = 2

# A fuzzy history hit has to be at least this alike before it is offered
# at all, and its confidence is scaled by how alike it actually was.
FUZZY_THRESHOLD = 0.75

# Containment ("shell" inside "shell oil") only counts as a merchant match
# when the shorter key is at least this long, so a two-letter fragment
# doesn't sweep up every merchant that happens to contain it.
MIN_CONTAINMENT = 5

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_DIGITS = re.compile(r"\d+")


def merchant_key(text: str) -> str:
    """Reduce a description to the merchant behind it.

    Deliberately stricter than `matching.normalize`, which keeps single
    digits because for reconciliation a number can be the identity of the
    transaction — `CHECK 1041` and `CHECK 1042` are different cheques and
    must not be conflated. Here the question is the opposite one: *which
    merchant is this?*, and every digit is noise — a store number, a
    till, a reference. Keeping them fragments one merchant across dozens
    of keys and starves the evidence: `AMAZON MKTPLACE 3` and `AMAZON
    MKTPLACE 12` are the same shop and belong in the same bucket.
    """
    lowered = _PUNCT.sub(" ", (text or "").lower())
    return " ".join(_DIGITS.sub(" ", lowered).split())


def key_similarity(left: str, right: str) -> float:
    """Likeness of two merchant keys, both already normalized."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if (left in right or right in left) and \
            min(len(left), len(right)) >= MIN_CONTAINMENT:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()

# Sources, most authoritative first.
COLUMN, RULE, HISTORY, NONE = "column", "rule", "history", "none"


@dataclass
class Suggestion:
    account: str | None
    confidence: float
    source: str
    basis: str


class Classifier:
    """Answers "which account is this?" for one target account.

    Built once per run: the history index is a single query, and every
    row is matched against the in-memory index.
    """

    def __init__(self, led: Ledger, account: Account,
                 since: date | None = None):
        self.led = led
        self.account = account
        self.rules = led.import_rules()
        self.index: dict[str, Counter] = defaultdict(Counter)
        for description, counter in led.counter_account_history(account,
                                                                since):
            key = merchant_key(description)
            if key:
                self.index[key][counter] += 1
        # Sorted once: `get_close_matches` returns ties in input order, so
        # a stable input is what makes the same ledger give the same answer.
        self._keys = sorted(self.index)

    @property
    def history_size(self) -> int:
        return sum(sum(c.values()) for c in self.index.values())

    def _nearest(self, key: str) -> tuple[str | None, float]:
        """The closest merchant already seen, or (None, 0.0).

        Containment is checked first with plain string operations, then
        `get_close_matches` does the scoring — it prefilters on length and
        character overlap before running the full ratio, which a manual
        scan does not. On a ledger with a few thousand distinct merchants
        that is the difference between a fraction of a second and half a
        minute for a statement full of unfamiliar names.
        """
        if len(key) >= MIN_CONTAINMENT:
            contained = [c for c in self._keys
                         if len(c) >= MIN_CONTAINMENT
                         and (c in key or key in c)]
            if contained:
                # Longest wins: the most specific merchant containing it.
                return max(contained, key=lambda c: (len(c), c)), 1.0
        close = get_close_matches(key, self._keys, n=1,
                                  cutoff=FUZZY_THRESHOLD)
        if not close:
            return None, 0.0
        return close[0], key_similarity(key, close[0])

    def _from_history(self, description: str) -> Suggestion | None:
        key = merchant_key(description)
        if not key:
            return None
        hits, scale, note = self.index.get(key), 1.0, ""
        if hits is None:
            # No exact merchant match — fall back to the nearest one seen.
            best_key, scale = self._nearest(key)
            if best_key is None:
                return None
            hits = self.index[best_key]
            note = f"~{best_key[:24]} "
        account, top = hits.most_common(1)[0]
        total = sum(hits.values())
        confidence = ((top / total)
                      * (total / (total + EVIDENCE_DAMPING))
                      * scale)
        if len(hits) == 1:
            basis = f"{note}{total} prior"
        else:
            split = " / ".join(
                f"{n} {name.rsplit(':', 1)[-1]}"
                for name, n in hits.most_common(3)
            )
            basis = f"{note}{total} prior: {split}"
        return Suggestion(account, round(confidence, 2), HISTORY, basis)

    def suggest(self, description: str,
                category: str | None = None) -> Suggestion:
        """Resolve one row. `category` is whatever the row already carried
        — an existing decision, which is never overridden."""
        if category:
            # Resolve it so a typo surfaces here rather than at import.
            account = self.led.find_account(category)
            return Suggestion(account.name, 1.0, COLUMN, "already set")
        if description:
            for _id, pattern, account in self.rules:
                if pattern.lower() in description.lower():
                    return Suggestion(account.name, 1.0, RULE,
                                      f'rule "{pattern}"')
            found = self._from_history(description)
            if found:
                return found
        return Suggestion(None, 0.0, NONE, "no match")


# -- the prepared file -------------------------------------------------------

PREPARED_COLUMNS = ["date", "description", "amount", "category",
                    "confidence", "basis"]


def _plain_amount(minor: int, decimals: int) -> str:
    """Minor units as a bare decimal — no separators, no symbol — so the
    file stays diff-friendly and reads back through `beans import`."""
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 10**decimals)
    if not decimals:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{frac:0{decimals}d}"


def prepare(classifier: Classifier,
            rows: list) -> list[tuple[object, Suggestion]]:
    """Pair every statement row with its suggestion, in file order."""
    out = []
    for row in rows:
        try:
            found = classifier.suggest(row.description, row.category)
        except BeansError as exc:
            # A category the file already carried but that doesn't resolve
            # — say which row, the way the importer does.
            raise BeansError(f"line {row.line}: {exc}")
        out.append((row, found))
    return out


def write_prepared_csv(led: Ledger, classifier: Classifier, rows: list,
                       path: str, force: bool = False) -> int:
    """Write rows plus their suggestions as a CSV `beans import` reads.

    `import` ignores columns it doesn't know, so `confidence` and `basis`
    ride along for you to read and are simply skipped on import — the
    file needs no stripping before use. Amounts are written in import
    convention (positive = money into the account), already un-inverted
    if the source was read with `--invert`.
    """
    out = Path(path).expanduser()
    # This file is meant to be edited between being written and being
    # imported, so overwriting one silently would throw away that work.
    if out.exists() and not force:
        raise BeansError(f"{out} already exists — pass --force to overwrite")
    prepared = prepare(classifier, rows)
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PREPARED_COLUMNS)
        for row, found in prepared:
            writer.writerow([
                row.date.isoformat(),
                row.description,
                _plain_amount(row.amount, led.decimals),
                found.account or "",
                f"{found.confidence:.2f}",
                found.basis,
            ])
    return len(prepared)


# -- the report --------------------------------------------------------------


def categorize_report(led: Ledger, account: Account,
                      classifier: Classifier, rows: list,
                      source: str, out_path: str | None = None) -> dict:
    sign = account.type.natural_sign
    prepared = prepare(classifier, rows)
    counts: Counter = Counter(found.source for _row, found in prepared)
    return {
        "report": "categorize",
        "account": account.name,
        "source": source,
        "output": out_path,
        "history_size": classifier.history_size,
        "summary": {
            "rows": len(prepared),
            "column": counts[COLUMN],
            "rule": counts[RULE],
            "history": counts[HISTORY],
            "unresolved": counts[NONE],
        },
        "rows": [
            {
                "line": row.line,
                "date": row.date,
                "description": row.description,
                "amount": row.amount * sign,
                "category": found.account,
                "confidence": found.confidence,
                "source": found.source,
                "basis": found.basis,
            }
            for row, found in prepared
        ],
    }


def render_categorize(data: dict, decimals: int, symbol: str) -> str:
    counts = data["summary"]
    lines = [
        bold(f"CATEGORIZE — {data['account']}"),
        f"Source: {data['source']} — {counts['rows']} row(s)",
        f"Learned from {data['history_size']} prior transaction(s) "
        "on this account",
        "",
    ]
    table = Table(align="lr")
    table.add("Already set in the file", str(counts["column"]))
    table.add("From an import rule", str(counts["rule"]))
    table.add("Inferred from history", str(counts["history"]))
    unresolved = str(counts["unresolved"])
    table.add(bold("Needs a decision"),
              unresolved if not counts["unresolved"] else red(unresolved))
    lines.append(table.render())
    lines.append("")

    # Least certain first: this list is meant to be read from the top and
    # abandoned once the rows stop being interesting.
    ordered = sorted(data["rows"],
                     key=lambda r: (r["confidence"], r["date"]))
    table = Table(headers=["Date", "Description", "Amount", "Account",
                           "Conf", "Basis"], align="llrlrl")
    for row in ordered:
        conf = f"{row['confidence']:.2f}"
        table.add(row["date"].isoformat(), row["description"][:28],
                  money(row["amount"], decimals),
                  (row["category"] or "—")[:26],
                  conf if row["confidence"] >= 0.75 else red(conf),
                  row["basis"][:34])
    lines.append(table.render())
    lines.append("")

    notes = ["Sorted least-certain first — read from the top and stop when "
             "the rows stop being interesting."]
    if counts["unresolved"]:
        notes.append(
            f"{counts['unresolved']} row(s) have no account yet. Fill them "
            "in, or teach them once with `beans rule add PATTERN ACCOUNT`."
        )
    if data["output"]:
        notes.append(
            f"Wrote {counts['rows']} row(s) to {data['output']} — review "
            f"the low-confidence rows, then: beans import {data['output']} "
            f"--account {data['account']}"
        )
    else:
        notes.append("Nothing was written. Pass -o PATH to save this as an "
                     "editable CSV for `beans import`.")
    notes.append("Confidence ranks your attention; it is not a probability, "
                 "and nothing is imported on its strength.")
    lines.append("\n".join(notes))
    return "\n".join(lines)
