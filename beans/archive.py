"""Archival: roll the ledger forward into a smaller file without losing
the answers.

A household register grows without bound — twenty-five years of daily
activity is tens of thousands of transactions — and at some point you
want a fresh file to work in. The obvious way to get one is to keep the
closing balances and drop the transactions. That ties the balance sheet
to the cent and quietly destroys everything else: with no flows behind
it, `status` reports the cutover as a windfall, `forecast` projects a
household that neither earns nor spends, and `analyze` cannot compute a
savings rate or a runway at all.

So the default here **compacts** rather than deletes. Every transaction
on or before the cutover is replaced by one summary transaction per
month, whose postings are that month's per-account totals. The result is
a register a hundredth the size in which every period-aligned figure —
balance sheet, income statement, cash flows, trend, net worth, forecast,
every ratio — is *identical*, because `balances`, `flows`,
`monthly_flows` and `monthly_type_totals` are all sums, and a sum of
monthly sums is the monthly sum.

Two things follow from that, and both are load-bearing:

**The grain is the month, and is not a knob.** A summary lands wholly on
one date, so a window that starts or ends mid-month no longer ties. Every
default in beans is period-aligned, so this does not bite in ordinary
use — but a finer grain would not help: weekly buckets straddle month
ends and would break `trend`, `networth` and `forecast`, which is worse
than the edge it fixes. The roll-up grain has to divide the coarsest
period any report groups by.

**What is lost is detail, not arithmetic.** Payees, descriptions,
individual amounts, cleared flags and void history are gone for archived
months, and with them `search`, `tx show`, `register` and `reconcile` for
those months — and the classifier's evidence, which is why `plan()`
reports the merchants that are about to become unlearnable so they can be
written down as import rules first.

Nothing is destroyed in place: the source ledger is never modified, and
the compacted ledger is a new file. The original *is* the full-fidelity
archive, so keeping it is the whole backup story.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from beans.classify import merchant_key
from beans.ledger import Ledger
from beans.models import AccountType
from beans.render import Table, bold
from beans.utils import BeansError, month_bounds

# Tag stamped on every summary transaction, so archived months are
# identifiable in the register and filterable in search.
ARCHIVE_TAG = "archived"

# Description prefixes `beans` generates itself (`spend`, `earn`,
# `transfer` when given no --desc). They restate the account rather than
# name a merchant, so they are not categorization evidence worth warning
# about losing.
SELF_DESCRIBED = ("Spending: ", "Income: ", "Transfer: ")


def _month_end(key: str) -> date:
    """Last day of a 'YYYY-MM' key — where that month's summary lands."""
    return month_bounds(int(key[:4]), int(key[5:]))[1]


def _monthly_legs(db: sqlite3.Connection,
                  through: date) -> dict[str, list[tuple[int, int]]]:
    """Per-account posting totals for each month up to `through`, keyed
    'YYYY-MM'. Void transactions are excluded: they contribute nothing to
    any balance, so a summary must not carry them."""
    legs: dict[str, list[tuple[int, int]]] = {}
    for row in db.execute(
        "SELECT substr(t.date, 1, 7) AS ym, p.account_id AS acct, "
        "SUM(p.amount) AS total FROM postings p "
        "JOIN transactions t ON t.id = p.txn_id "
        "WHERE t.void = 0 AND t.date <= ? "
        "GROUP BY ym, acct ORDER BY ym, acct",
        (through.isoformat(),),
    ):
        if row["total"]:
            legs.setdefault(row["ym"], []).append((row["acct"], row["total"]))
    return legs


def _opening_legs(db: sqlite3.Connection,
                  through: date) -> list[tuple[int, int]]:
    """Balance-sheet balances as of `through`, as opening-entry postings.

    Income and expense accounts are left out — they are period flows, and
    dropping them is what closes cumulative net income into equity. The
    caller supplies the balancing equity leg.
    """
    return [
        (row["acct"], row["total"])
        for row in db.execute(
            "SELECT p.account_id AS acct, SUM(p.amount) AS total "
            "FROM postings p JOIN transactions t ON t.id = p.txn_id "
            "JOIN accounts a ON a.id = p.account_id "
            "WHERE t.void = 0 AND t.date <= ? AND a.type IN "
            "('asset','liability','equity') "
            "GROUP BY acct ORDER BY acct",
            (through.isoformat(),),
        )
        if row["total"]
    ]


def plan(led: Ledger, through: date, drop_detail: bool = False) -> dict:
    """What archiving through `through` would do, without doing it."""
    if through >= date.today():
        raise BeansError(
            f"cannot archive through {through.isoformat()}: pick a date in "
            "the past, so the archived months are complete"
        )
    counts = led.db.execute(
        "SELECT COUNT(*) AS txns, "
        "(SELECT COUNT(*) FROM postings p JOIN transactions t2 "
        " ON t2.id = p.txn_id WHERE t2.date <= ?) AS postings, "
        "MIN(date) AS first, MAX(date) AS last "
        "FROM transactions WHERE date <= ?",
        (through.isoformat(), through.isoformat()),
    ).fetchone()
    if not counts["txns"]:
        raise BeansError(
            f"nothing to archive on or before {through.isoformat()}"
        )
    legs = _monthly_legs(led.db, through)
    summaries = len(legs) if not drop_detail else 1
    remaining = led.db.execute(
        "SELECT COUNT(*) AS n FROM transactions WHERE date > ?",
        (through.isoformat(),),
    ).fetchone()["n"]
    return {
        "report": "archive_plan",
        "through": through,
        "mode": "drop-detail" if drop_detail else "compact",
        "source": str(led.path),
        "first_archived": date.fromisoformat(counts["first"]),
        "last_archived": date.fromisoformat(counts["last"]),
        "archived_transactions": counts["txns"],
        "archived_postings": counts["postings"],
        "summary_transactions": summaries,
        "retained_transactions": remaining,
        "months": sorted(legs),
        "unlearnable_merchants": _unlearnable(led, through),
        "source_bytes": led.path.stat().st_size if led.path.exists() else 0,
    }


def _unlearnable(led: Ledger, through: date, limit: int = 10) -> list[dict]:
    """Merchants whose only categorization evidence is about to be
    archived, worst first — no surviving history and no import rule.

    `beans categorize` learns from two-legged transactions, and a summary
    has many legs, so this evidence does not survive either mode. The
    merchants that hurt are the annual ones: an archive run every January
    is exactly out of phase with a bill paid every January.

    Descriptions are read the way the classifier reads them — same
    two-leg filter, same `merchant_key` normalization — so the warning
    names what would actually be lost rather than an approximation of it.
    Descriptions `beans` writes for itself are skipped: "Spending: Rent"
    is the account restated, not a merchant, and no bank export will ever
    contain it.
    """
    covered = {merchant_key(pattern)
               for _id, pattern, _acct in led.import_rules()}
    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for row in led.db.execute(
        "SELECT t.date, t.description, t.payee FROM transactions t "
        "WHERE t.void = 0 AND "
        "(SELECT COUNT(*) FROM postings x WHERE x.txn_id = t.id) = 2",
    ):
        name = (row["description"] or row["payee"] or "").strip()
        if not name or name.startswith(SELF_DESCRIBED):
            continue
        key = merchant_key(name)
        if not key:
            continue
        labels.setdefault(key, name)
        bucket = before if row["date"] <= through.isoformat() else after
        bucket[key] += 1
    lost = [
        {"merchant": labels[key], "archived_sightings": n}
        for key, n in before.items()
        if not after.get(key) and key not in covered
    ]
    lost.sort(key=lambda item: (-item["archived_sightings"], item["merchant"]))
    return lost[:limit]


def archive(led: Ledger, through: date, out: str | Path,
            drop_detail: bool = False, force: bool = False) -> dict:
    """Write a compacted copy of `led` to `out` and return what changed.

    The source ledger is opened read-only in effect — it is never written
    — and the destination is built from SQLite's online backup, so the
    copy is consistent even if something else is mid-write.
    """
    summary = plan(led, through, drop_detail=drop_detail)
    path = Path(out).expanduser()
    if path.resolve() == led.path.resolve():
        raise BeansError(
            "archive destination is the ledger itself — archiving writes a "
            "new file and leaves the original as the full-detail record"
        )
    if path.exists() and not force:
        raise BeansError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)

    # Balances and monthly flows before the rewrite: the invariants the
    # result is checked against, read from the source rather than
    # recomputed from the copy so a bad copy cannot agree with itself.
    expected_balances = led.balances(as_of=through)
    expected_flows = _monthly_legs(led.db, through)

    if path.exists():
        path.unlink()
    target = sqlite3.connect(path)
    try:
        with target:
            led.db.backup(target)
    finally:
        target.close()

    new = Ledger(path)
    try:
        _rewrite(new, through, summary, drop_detail)
        _verify(new, through, expected_balances, expected_flows, drop_detail)
        new.db.execute("VACUUM")
    except Exception:
        new.close()
        path.unlink(missing_ok=True)
        raise
    new.close()

    summary["report"] = "archive"
    summary["out"] = str(path)
    summary["out_bytes"] = path.stat().st_size
    return summary


def _rewrite(new: Ledger, through: date, summary: dict,
             drop_detail: bool) -> None:
    """Replace the pre-cutover register in `new` with its summaries."""
    legs = _monthly_legs(new.db, through)
    opening = _opening_legs(new.db, through) if drop_detail else []
    with new.db:
        new.db.execute(
            "DELETE FROM postings WHERE txn_id IN "
            "(SELECT id FROM transactions WHERE date <= ?)",
            (through.isoformat(),),
        )
        new.db.execute("DELETE FROM transactions WHERE date <= ?",
                       (through.isoformat(),))
        if drop_detail:
            _insert_summary(new, through,
                            "Opening balances (detail archived)",
                            _balanced(new, opening))
        else:
            for key in sorted(legs):
                _insert_summary(new, min(_month_end(key), through),
                                f"Monthly summary {key} (detail archived)",
                                legs[key])
    # The books are closed through the cutover: the detail that would
    # justify editing them no longer exists in this file. A close already
    # standing past the cutover is left where it is — archiving must not
    # quietly reopen months the user had locked.
    already = new.closed_through
    new.set_meta("closed_through",
                 max(through, already).isoformat() if already
                 else through.isoformat())
    # Where flow history actually starts. Under compaction the monthly
    # series survives intact, so it stays the original first month;
    # dropping detail really does move it to the cutover.
    new.set_meta(
        "history_begins",
        (through if drop_detail else summary["first_archived"]).isoformat(),
    )
    # Where line-item detail starts — the day after the cutover in both
    # modes, since the cutover day itself is inside a summary.
    new.set_meta("detail_begins",
                 (through + timedelta(days=1)).isoformat())


def _equity_account(led: Ledger):
    """Where an opening entry's balancing leg goes.

    'Equity:Opening Balances' is in the default chart and is what
    `beans init` and the manual use, but a hand-built chart need not have
    it — so fall back to the only equity account if there is exactly one.
    """
    equity = led.accounts(type_=AccountType.EQUITY, include_closed=True)
    for name in ("equity:opening balances", "opening balances"):
        for account in equity:
            if account.name.lower() == name:
                return account
    if len(equity) == 1:
        return equity[0]
    raise BeansError(
        "--drop-detail needs one equity account to carry the opening "
        "balance, and this chart has "
        + (f"{len(equity)}" if equity else "none")
        + " — add 'Equity:Opening Balances' first, or archive without "
          "--drop-detail"
    )


def _balanced(led: Ledger,
              legs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Add the equity leg that makes an opening entry sum to zero.

    The residual is cumulative net income — the retained earnings the
    books never formally closed — which is exactly what folds into
    contributed capital when the flows behind it are dropped.
    """
    total = sum(amount for _acct, amount in legs)
    if not total:
        return legs
    merged = dict(legs)
    equity = _equity_account(led)
    merged[equity.id] = merged.get(equity.id, 0) - total
    return [(acct, amount) for acct, amount in sorted(merged.items())
            if amount]


def _insert_summary(led: Ledger, when: date, description: str,
                    legs: list[tuple[int, int]]) -> None:
    if not legs:
        return
    if sum(amount for _acct, amount in legs) != 0:
        raise BeansError(
            f"refusing to write an unbalanced summary for {when.isoformat()} "
            "— this is a bug in beans, and the archive was not written"
        )
    cur = led.db.execute(
        "INSERT INTO transactions (date, description, payee, tags, void, "
        "created) VALUES (?, ?, '', ?, 0, ?)",
        (when.isoformat(), description, ARCHIVE_TAG,
         date.today().isoformat()),
    )
    led.db.executemany(
        "INSERT INTO postings (txn_id, account_id, amount, cleared, "
        "foreign_amount) VALUES (?, ?, ?, 0, NULL)",
        [(cur.lastrowid, acct, amount) for acct, amount in legs],
    )


def _verify(new: Ledger, through: date, balances: dict[int, int],
            flows: dict[str, list[tuple[int, int]]],
            drop_detail: bool) -> None:
    """Prove the rewrite preserved what it claims to preserve, and refuse
    to hand back a ledger that does not tie.

    Under compaction the claim is total: every account balance as of the
    cutover and every archived month's per-account flow are unchanged.

    Under --drop-detail the claim is necessarily weaker, and saying so
    precisely is the point. Assets and liabilities — and therefore net
    worth — are unchanged. Income and expense balances go to zero and
    equity absorbs them, because closing cumulative net income into
    contributed capital is exactly what dropping the flows means; what
    must still hold is that *total* equity is unchanged, which is the
    statement that no value was invented or lost.
    """
    types = {a.id: a.type for a in new.accounts(include_closed=True)}
    got = new.balances(as_of=through)
    kept = ({AccountType.ASSET, AccountType.LIABILITY} if drop_detail
            else set(AccountType))
    # An account whose balance nets to zero may be dropped from the
    # rewrite entirely, so compare on value rather than on key presence.
    for acct_id in set(got) | set(balances):
        if types.get(acct_id) not in kept:
            continue
        if got.get(acct_id, 0) != balances.get(acct_id, 0):
            raise BeansError(
                "archive verification failed: balance for account id "
                f"{acct_id} changed from {balances.get(acct_id, 0)} to "
                f"{got.get(acct_id, 0)} — the archive was not written"
            )
    if drop_detail:
        def equity_and_earnings(amounts: dict[int, int]) -> int:
            return sum(
                amount for acct_id, amount in amounts.items()
                if types.get(acct_id) in (AccountType.EQUITY,
                                          AccountType.INCOME,
                                          AccountType.EXPENSE)
            )
        if equity_and_earnings(got) != equity_and_earnings(balances):
            raise BeansError(
                "archive verification failed: total equity changed — the "
                "archive was not written"
            )
        return
    rebuilt = _monthly_legs(new.db, through)
    if ({key: sorted(legs) for key, legs in rebuilt.items()}
            != {key: sorted(legs) for key, legs in flows.items()}):
        raise BeansError(
            "archive verification failed: monthly flows changed — the "
            "archive was not written"
        )


def render_plan(data: dict, decimals: int, symbol: str) -> str:
    mode = ("compacting to monthly summaries" if data["mode"] == "compact"
            else "dropping detail, keeping balances only")
    dry = data["report"] == "archive_plan"
    lines = [
        bold("ARCHIVE" + (" (dry run)" if dry else "")),
        f"Through: {data['through'].isoformat()} — {mode}",
        f"Source:  {data['source']}",
    ]
    if "out" in data:
        lines.append(f"Written: {data['out']}")
    lines.append("")
    table = Table(align="lr")
    table.add("Archived transactions", f"{data['archived_transactions']:,}")
    table.add("Archived postings", f"{data['archived_postings']:,}")
    table.add("Replaced by", f"{data['summary_transactions']:,} summar"
              + ("y" if data["summary_transactions"] == 1 else "ies"))
    table.add("Retained after cutover", f"{data['retained_transactions']:,}")
    table.add("Covering",
              f"{data['first_archived'].isoformat()} to "
              f"{data['last_archived'].isoformat()}")
    table.add("Ledger size", f"{_mb(data['source_bytes'])} -> "
              + (_mb(data["out_bytes"]) if "out_bytes" in data
                 else "(dry run)"))
    lines.append(table.render(indent="  "))

    lost = data["unlearnable_merchants"]
    if lost:
        lines += ["", bold("Categorization history that will not survive"),
                  "These merchants have no activity after the cutover and no",
                  "import rule, so `beans categorize` will stop suggesting",
                  "an account for them. `beans rule add` writes the decision",
                  "down before it is lost:", ""]
        for item in lost:
            lines.append(f"  {item['merchant']:<40} "
                         f"{item['archived_sightings']:>4} archived")
    if dry:
        lines += ["", "Nothing was written. Re-run without --dry-run to "
                  "archive."]
    else:
        lines += ["",
                  "The source ledger is unchanged and still holds every "
                  "line item —",
                  "it is the archive of record, so keep it. Work in the new "
                  "file with:",
                  "",
                  f"  beans -f {data['out']} status"]
    return "\n".join(lines) + "\n"


def _mb(size: int) -> str:
    return f"{size / 1_000_000:.2f} MB"
