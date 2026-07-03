"""Loans and amortization.

A loan attaches amortization terms (principal, annual rate, term, payment) to
a liability account. The schedule those terms generate is used for two things:

  * `beans loan show` renders the amortization table, and
  * the classified balance sheet splits the liability's *ledger* balance into a
    current portion (principal scheduled to be repaid within the next twelve
    months) and a non-current remainder.

The ledger balance is always the source of truth: the current portion is the
next-twelve-months scheduled principal **capped at the actual outstanding
balance**, so the two buckets always sum to the real balance and the balance
sheet still balances. Variable rates or extra principal payments make the split
point approximate, never the totals.

Rates are exact `Decimal`s; principal, payment, interest, and balances are
integer minor units, consistent with the rest of the ledger.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from beans.ledger import Ledger
from beans.models import Account, AccountType, Loan, Posting
from beans.render import Table, bold, money
from beans.utils import BeansError, add_months_clamped

# Backstop so a bad payment/rate combination can't loop forever building a
# schedule (e.g. a payment that barely covers interest).
MAX_SCHEDULE_MONTHS = 1200

INTEREST_ACCOUNT = "Expenses:Interest"


def _round_minor(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def periodic_rate(annual_rate: Decimal) -> Decimal:
    """Monthly rate from a nominal annual rate."""
    return Decimal(annual_rate) / Decimal(12)


def payment_for(principal: int, rate: Decimal, n: int) -> int:
    """The level payment (minor units) that amortizes `principal` over `n`
    periods at periodic rate `rate`."""
    if n <= 0:
        raise BeansError("loan term must be a positive number of months")
    p = Decimal(principal)
    if rate == 0:
        return _round_minor(p / Decimal(n))
    factor = (Decimal(1) + rate) ** n
    return _round_minor(p * rate * factor / (factor - Decimal(1)))


def term_for(principal: int, rate: Decimal, payment: int) -> int:
    """Number of payments needed to amortize `principal` at `payment` per
    period. Derived by simulating the schedule, so it honours the same
    rounding the schedule uses."""
    if payment <= 0:
        raise BeansError("loan payment must be positive")
    if rate > 0 and Decimal(payment) <= Decimal(principal) * rate:
        raise BeansError(
            "payment is too small to ever pay down the loan "
            "(it does not cover the first month's interest)"
        )
    balance = principal
    for months in range(1, MAX_SCHEDULE_MONTHS + 1):
        interest = _round_minor(Decimal(balance) * rate)
        balance -= min(payment - interest, balance)
        if balance <= 0:
            return months
    raise BeansError(
        "payment is too small to pay off the loan within a reasonable term"
    )


def schedule(loan: Loan, as_of: date | None = None) -> list[dict]:
    """The amortization schedule: one row per payment with date, payment,
    interest, principal, and remaining balance (all minor units)."""
    rate = periodic_rate(loan.annual_rate)
    balance = loan.principal
    rows: list[dict] = []
    for i in range(loan.term_months):
        if balance <= 0:
            break
        when = add_months_clamped(loan.start_date, i)
        interest = _round_minor(Decimal(balance) * rate)
        principal_paid = loan.payment - interest
        # The final payment trues up whatever rounding left behind.
        if principal_paid >= balance:
            principal_paid = balance
        pay = interest + principal_paid
        balance -= principal_paid
        rows.append({
            "number": i + 1,
            "date": when,
            "payment": pay,
            "interest": interest,
            "principal": principal_paid,
            "balance": balance,
            "future": as_of is None or when > as_of,
        })
    return rows


def current_portion(loan: Loan, as_of: date, outstanding: int) -> int:
    """Principal scheduled to be repaid in the year after `as_of`, capped at
    the actual `outstanding` balance. If the schedule has no payments left
    after `as_of` but a balance remains, the whole balance is current (it is
    due or overdue)."""
    if outstanding <= 0:
        return 0
    window_end = add_months_clamped(as_of, 12)
    rows = schedule(loan)
    upcoming = [r for r in rows if r["date"] > as_of]
    if not upcoming:
        return outstanding
    due_soon = sum(r["principal"] for r in upcoming if r["date"] <= window_end)
    return min(due_soon, outstanding)


def classified_liability_split(
    led: Ledger, as_of: date, raw: dict[int, int]
) -> dict[int, tuple[int, int]]:
    """Map each liability account id to (current, non-current) natural-sign
    amounts. Accounts with a loan are split by the amortization schedule;
    the rest fall back to their `liquidity` tag."""
    split: dict[int, tuple[int, int]] = {}
    for account in led.accounts(type_=AccountType.LIABILITY,
                                include_closed=True):
        balance = raw.get(account.id, 0) * account.type.natural_sign
        loan = led.loan_for(account)
        if loan is not None and balance > 0:
            current = current_portion(loan, as_of, balance)
            split[account.id] = (current, balance - current)
        elif account.is_current:
            split[account.id] = (balance, 0)
        else:
            split[account.id] = (0, balance)
    return split


# -- reports -----------------------------------------------------------------


def _interest_account(led: Ledger) -> Account:
    try:
        return led.find_account(INTEREST_ACCOUNT)
    except BeansError:
        return led.add_account(INTEREST_ACCOUNT, AccountType.EXPENSE,
                               description="created by beans loan pay")


def pay(led: Ledger, account: Account, cash: Account, when: date,
        amount: int | None = None) -> dict:
    """Post one loan payment as a balanced transaction: principal reduces the
    liability, interest hits Expenses:Interest, and cash goes out. Interest is
    computed on the outstanding ledger balance, so the split reflects reality
    even after extra or missed payments."""
    loan = led.loan_for(account)
    if loan is None:
        raise BeansError(f"no loan attached to {account.name}")
    raw = led.balances(as_of=when)
    outstanding = raw.get(account.id, 0) * account.type.natural_sign
    if outstanding <= 0:
        raise BeansError(f"{account.name} is already paid off")
    interest = _round_minor(Decimal(outstanding) * periodic_rate(
        loan.annual_rate))
    pay_amount = amount if amount is not None else loan.payment
    principal = pay_amount - interest
    if principal <= 0:
        raise BeansError(
            "payment does not cover this period's interest "
            f"({money(interest, led.decimals)})"
        )
    if principal >= outstanding:  # final payoff trues up to the real balance
        principal = outstanding
        pay_amount = interest + principal
    interest_acct = _interest_account(led)
    postings = [
        Posting(account_id=account.id, amount=principal),
        Posting(account_id=cash.id, amount=-pay_amount),
    ]
    if interest:
        postings.append(Posting(account_id=interest_acct.id, amount=interest))
    txn = led.add_transaction(
        when, f"Loan payment: {account.name}", postings, tags=["loan"])
    return {
        "txn_id": txn.id,
        "principal": principal,
        "interest": interest,
        "payment": pay_amount,
        "balance_after": outstanding - principal,
    }


def loans_report(led: Ledger, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    raw = led.balances(as_of=as_of)
    rows = []
    for loan in led.loans():
        account = led.find_account(loan.account_name)
        balance = raw.get(account.id, 0) * account.type.natural_sign
        current = current_portion(loan, as_of, balance)
        sched = schedule(loan)
        remaining = sum(1 for r in sched if r["date"] > as_of)
        rows.append({
            "account": loan.account_name,
            "principal": loan.principal,
            "rate_pct": float(loan.annual_rate * 100),
            "term_months": loan.term_months,
            "payment": loan.payment,
            "balance": balance,
            "current_portion": current,
            "noncurrent_portion": balance - current,
            "payments_remaining": remaining,
        })
    return {"report": "loans", "as_of": as_of, "rows": rows}


def render_loans(data: dict, decimals: int, symbol: str) -> str:
    if not data["rows"]:
        return ("No loans. Attach one with: beans loan add --account "
                "<liability> --principal P --rate R --term N")
    lines = [bold("LOANS"), f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(headers=["Account", "Rate", "Payment", "Balance",
                           "Current", "Non-current", "Left"],
                  align="lrrrrrr")
    for row in data["rows"]:
        table.add(row["account"], f"{row['rate_pct']:.3f}%",
                  money(row["payment"], decimals),
                  money(row["balance"], decimals),
                  money(row["current_portion"], decimals),
                  money(row["noncurrent_portion"], decimals),
                  str(row["payments_remaining"]))
    lines.append(table.render())
    return "\n".join(lines)


def schedule_report(loan: Loan, as_of: date | None = None) -> dict:
    rows = schedule(loan, as_of=as_of)
    return {
        "report": "loan_schedule",
        "account": loan.account_name,
        "principal": loan.principal,
        "rate_pct": float(loan.annual_rate * 100),
        "term_months": loan.term_months,
        "payment": loan.payment,
        "rows": rows,
        "total_interest": sum(r["interest"] for r in rows),
    }


def render_schedule(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold(f"AMORTIZATION SCHEDULE — {data['account']}"),
             f"Principal {money(data['principal'], decimals, symbol)} at "
             f"{data['rate_pct']:.3f}% over {data['term_months']} months, "
             f"payment {money(data['payment'], decimals, symbol)}", ""]
    table = Table(headers=["#", "Date", "Payment", "Interest", "Principal",
                           "Balance"], align="rlrrrr")
    for r in data["rows"]:
        table.add(str(r["number"]), r["date"].isoformat(),
                  money(r["payment"], decimals),
                  money(r["interest"], decimals),
                  money(r["principal"], decimals),
                  money(r["balance"], decimals))
    lines.append(table.render())
    lines += ["", f"Total interest over the life of the loan: "
              f"{money(data['total_interest'], decimals, symbol)}"]
    return "\n".join(lines)
