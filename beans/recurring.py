"""Recurring/scheduled transactions.

A recurring rule is a balanced transaction template plus a cadence
(daily, weekly, biweekly, monthly, quarterly, yearly). Occurrence dates
are derived from the rule's start date and a count of instances already
posted, so monthly rules anchored on the 31st correctly clamp to short
months (Jan 31 -> Feb 28 -> Mar 31) without drifting.

`beans recur run` posts every occurrence due through a given date.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from beans.ledger import Ledger
from beans.models import Posting, Recurring
from beans.render import Table, bold, money
from beans.utils import BeansError

# Hard ceiling on instances posted per rule in one run, to surface
# obviously wrong dates (e.g. a daily rule started decades ago).
MAX_RUN_PER_RULE = 1000


def add_months_clamped(anchor: date, months: int) -> date:
    """anchor shifted by whole months, clamping the day to month length."""
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = total // 12, total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def nth_occurrence(start: date, frequency: str, n: int) -> date:
    """The date of the (n+1)-th instance; n=0 is the start date itself."""
    if frequency == "daily":
        return start + timedelta(days=n)
    if frequency == "weekly":
        return start + timedelta(weeks=n)
    if frequency == "biweekly":
        return start + timedelta(weeks=2 * n)
    if frequency == "monthly":
        return add_months_clamped(start, n)
    if frequency == "quarterly":
        return add_months_clamped(start, 3 * n)
    if frequency == "yearly":
        return add_months_clamped(start, 12 * n)
    raise ValueError(f"unknown frequency: {frequency}")


def next_due(rec: Recurring) -> date | None:
    """The next unposted occurrence, or None if the rule has ended."""
    due = nth_occurrence(rec.start_date, rec.frequency, rec.occurrences)
    if rec.end_date and due > rec.end_date:
        return None
    return due


def run_due(led: Ledger, as_of: date, dry_run: bool = False) -> dict:
    """Post every active rule's occurrences due through as_of."""
    posted = []
    for rec in led.recurrings():
        if not rec.active:
            continue
        count = rec.occurrences
        while True:
            if count - rec.occurrences >= MAX_RUN_PER_RULE:
                raise BeansError(
                    f"recurring rule {rec.name!r} generated more than "
                    f"{MAX_RUN_PER_RULE} instances in one run — check its "
                    "start date, or remove and recreate it"
                )
            due = nth_occurrence(rec.start_date, rec.frequency, count)
            if due > as_of or (rec.end_date and due > rec.end_date):
                break
            txn_id = None
            if not dry_run:
                txn = led.add_transaction(
                    due,
                    rec.description or rec.name,
                    [Posting(account_id=p.account_id, amount=p.amount)
                     for p in rec.postings],
                    payee=rec.payee,
                    tags=rec.tags + ["recurring"],
                )
                txn_id = txn.id
            posted.append({
                "id": txn_id,
                "rule": rec.name,
                "date": due,
                "description": rec.description or rec.name,
                "amount": sum(p.amount for p in rec.postings if p.amount > 0),
            })
            count += 1
        if count != rec.occurrences and not dry_run:
            led.set_recurring_occurrences(rec, count)
    return {
        "report": "recurring_run",
        "as_of": as_of,
        "dry_run": dry_run,
        "posted": posted,
    }


def render_run(data: dict, decimals: int, symbol: str) -> str:
    verb = "Would post" if data["dry_run"] else "Posted"
    lines = [f"{verb} {len(data['posted'])} transaction(s) due through "
             f"{data['as_of'].isoformat()}"]
    if data["posted"]:
        table = Table(headers=["Date", "Rule", "Description", "Amount"],
                      align="lllr")
        for row in data["posted"]:
            table.add(row["date"].isoformat(), row["rule"],
                      row["description"][:40], money(row["amount"], decimals))
        lines.append(table.render())
    return "\n".join(lines)


def list_rules(led: Ledger, as_of: date) -> dict:
    rows = []
    for rec in led.recurrings():
        due = next_due(rec)
        if not rec.active:
            status = "paused"
        elif due is None:
            status = "ended"
        elif due <= as_of:
            status = "due"
        else:
            status = "scheduled"
        rows.append({
            "name": rec.name,
            "frequency": rec.frequency,
            "start": rec.start_date,
            "end": rec.end_date,
            "next_due": due,
            "status": status,
            "posted_count": rec.occurrences,
            "amount": sum(p.amount for p in rec.postings if p.amount > 0),
        })
    return {"report": "recurring_list", "as_of": as_of, "rules": rows}


def render_list(data: dict, decimals: int, symbol: str) -> str:
    if not data["rules"]:
        return ("No recurring rules. Add one with: beans recur add "
                "<name> --freq monthly --post ... (see `beans recur add -h`)")
    table = Table(headers=["Rule", "Frequency", "Next Due", "Status",
                           "Posted", "Amount"], align="lllllr")
    due_count = 0
    for row in data["rules"]:
        if row["status"] == "due":
            due_count += 1
        table.add(row["name"], row["frequency"],
                  row["next_due"].isoformat() if row["next_due"] else "—",
                  row["status"], row["posted_count"],
                  money(row["amount"], decimals))
    lines = [table.render()]
    if due_count:
        lines.append("")
        lines.append(bold(f"{due_count} rule(s) due — post with "
                          "`beans recur run`"))
    return "\n".join(lines)


def render_rule(rec: Recurring, decimals: int) -> str:
    """Detailed single-rule view for `beans recur show`."""
    due = next_due(rec)
    lines = [bold(rec.name),
             f"  frequency:  {rec.frequency}",
             f"  starts:     {rec.start_date.isoformat()}"]
    if rec.end_date:
        lines.append(f"  ends:       {rec.end_date.isoformat()}")
    lines.append(f"  status:     {'active' if rec.active else 'paused'}")
    lines.append(f"  posted:     {rec.occurrences} instance(s)")
    lines.append(f"  next due:   {due.isoformat() if due else '— (ended)'}")
    if rec.description:
        lines.append(f"  desc:       {rec.description}")
    if rec.payee:
        lines.append(f"  payee:      {rec.payee}")
    if rec.tags:
        lines.append(f"  tags:       {', '.join(rec.tags)}")
    lines.append("  postings:")
    width = max(len(p.account_name) for p in rec.postings)
    for p in rec.postings:
        lines.append(f"    {p.account_name:<{width}}  "
                     f"{money(p.amount, decimals):>14}")
    return "\n".join(lines)
