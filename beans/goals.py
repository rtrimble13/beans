"""Savings goals and debt-payoff targets.

A goal ties an account to a target balance and date. Asset goals grow
toward the target ("$20,000 house fund by 2028-01"); liability goals
shrink toward it (target 0 = pay the debt off). Reports show progress
and the monthly contribution required to land on time.
"""

from __future__ import annotations

from datetime import date

from beans.ledger import Ledger
from beans.models import AccountType
from beans.render import bold, green, money, red
from beans.utils import months_in_range

BAR_WIDTH = 20


def _progress_bar(fraction: float) -> str:
    filled = max(0, min(BAR_WIDTH, round(fraction * BAR_WIDTH)))
    return "[" + "#" * filled + "-" * (BAR_WIDTH - filled) + "]"


def goals_report(led: Ledger, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    raw = led.balances(as_of=as_of)
    rows = []
    for goal in led.goals():
        account = goal["account"]
        balance = raw.get(account.id, 0) * account.type.natural_sign
        target = goal["target"]
        months_left = max(0.0, months_in_range(as_of, goal["target_date"]))
        if account.type is AccountType.LIABILITY:
            # Pay the balance down to the target (usually zero).
            remaining = max(0, balance - target)
            done = remaining == 0
            progress = None  # without a known start there is no fraction
        else:
            remaining = max(0, target - balance)
            done = remaining == 0
            progress = min(1.0, balance / target) if target else 1.0
        required = (round(remaining / months_left)
                    if months_left >= 1 and remaining else remaining)
        rows.append({
            "name": goal["name"],
            "account": account.name,
            "kind": ("payoff" if account.type is AccountType.LIABILITY
                     else "savings"),
            "target": target,
            "target_date": goal["target_date"],
            "balance": balance,
            "remaining": remaining,
            "progress_pct": (round(100 * progress, 1)
                             if progress is not None else None),
            "required_monthly": required,
            "on_track": done,
            "months_left": round(months_left, 1),
        })
    return {"report": "goals", "as_of": as_of, "rows": rows}


def render_goals(data: dict, decimals: int, symbol: str) -> str:
    if not data["rows"]:
        return ("No goals. Add one with: beans goal add <name> "
                "--account <account> --target <amount> --by <date>")
    lines = [bold("GOALS"), f"As of: {data['as_of'].isoformat()}", ""]
    for row in data["rows"]:
        title = f"{row['name']} — {row['account']} ({row['kind']})"
        lines.append(bold(title))
        if row["kind"] == "savings":
            pct = row["progress_pct"]
            lines.append(f"  {_progress_bar(pct / 100)} {pct:.0f}%  "
                         f"{money(row['balance'], decimals, symbol)} of "
                         f"{money(row['target'], decimals, symbol)} "
                         f"by {row['target_date'].isoformat()}")
        else:
            lines.append(f"  {money(row['remaining'], decimals, symbol)} "
                         f"remaining, due {row['target_date'].isoformat()}")
        if row["on_track"]:
            lines.append(green("  Reached!"))
        elif row["months_left"] < 1:
            lines.append(red(f"  Past due — "
                             f"{money(row['remaining'], decimals, symbol)} "
                             "short"))
        else:
            lines.append(f"  Needs "
                         f"{money(row['required_monthly'], decimals, symbol)}"
                         f"/month for {row['months_left']:.0f} months")
        lines.append("")
    return "\n".join(lines).rstrip()
