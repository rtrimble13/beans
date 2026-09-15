"""Pro-forma projection: the books as they would stand if the run-rate held.

`beans forecast` projects one number per income and expense account and
accumulates the net. That is enough for a two-column summary and nowhere
near enough for a balance sheet, which needs a figure for *every* asset
and liability account, a retained-earnings roll-forward, and
`assets == liabilities + equity`.

So this module projects **balanced transactions**, not totals, and hands
them to the statement builders in `reports.py` unchanged. Three sources
feed the projection, in the same priority order `forecast` has always
used — recurring schedule > budget > history:

**Where the money comes from.** Every historical transaction with an
income or expense leg also says how it was funded. Attributing each
balance-sheet leg to the income/expense legs in proportion to their share
of the transaction gives, per account, the accounts that funded it: that
groceries go on the card, that salary and withheld tax move through
checking, that a mortgage payment is 135% of its interest charge in cash
of which 35% retires principal. Nothing to configure; it is read off the
books.

**The invisible half.** Transactions with *no* income or expense leg — a
savings sweep, a brokerage contribution, a card payoff — never reach an
income statement, so the old engine could not see them at all, even
though they are most of what decides what the balance sheet looks like
next month. They are projected separately, as a per-account monthly
run-rate that sums to zero by construction.

**One transaction per driver, not one per month.** `cash_flow_statement`
skips transactions with no cash leg — that is how a credit-card purchase
correctly stays out of operating cash until the card is paid. Bundling a
month into one transaction touches cash and would reclassify every card
charge as an operating outflow, so each driver gets its own balanced
entry. The projection's grain has to be the grain the classifier reads.

Nothing here writes. `ProForma` is a read-only overlay that adds the
projected transactions to `balances`, `flows` and `transactions`; the
ledger file is never opened for writing and never needs to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from beans import loans
from beans.budget import budget_accounts
from beans.ledger import Ledger
from beans.models import Account, AccountType, Posting, Transaction
from beans.recurring import pending_occurrences
from beans.utils import add_months, month_bounds

FLOW_TYPES = (AccountType.INCOME, AccountType.EXPENSE)

# Tag `beans recur run` stamps on every posted instance, and the tag the
# projection stamps on its own entries so they can never be mistaken for
# history downstream.
RECURRING_TAG = "recurring"
PROJECTED_TAG = "projected"


def month_keys(start: date, count: int) -> list[str]:
    return [f"{add_months(start, i):%Y-%m}" for i in range(count)]


def project_series(history: list[int], method: str, steps: int) -> list[int]:
    """Extrapolate a monthly series forward `steps` months."""
    if not history:
        return [0] * steps
    if method == "average" or len(history) < 2:
        avg = round(sum(history) / len(history))
        return [avg] * steps
    # Least-squares fit of flow against month index, extrapolated. The
    # fitted line is y = mean_y + slope * (x - mean_x); future month x is
    # (n - 1 + step), so the offset from the mean must subtract mean_x.
    n = len(history)
    xs = range(n)
    mean_x = (n - 1) / 2
    mean_y = sum(history) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y)
                for x, y in zip(xs, history)) / denom
    return [round(mean_y + slope * (n - 1 + step - mean_x))
            for step in range(1, steps + 1)]


@dataclass
class Driver:
    """One income or expense account's projection, and where it came from."""

    account: Account
    monthly: list[int]  # natural sign, one entry per full projected month
    source: str  # 'average' | 'trend' | 'budget' | 'recurring'
    stub: int = 0  # natural sign, for the part-elapsed current month

    @property
    def total(self) -> int:
        return sum(self.monthly) + self.stub


def _flow_split(postings: list[Posting], accounts: dict[int, Account]):
    """Split a transaction's postings into its income/expense legs and its
    balance-sheet legs."""
    flow, sheet = [], []
    for p in postings:
        account = accounts.get(p.account_id)
        if account is None:
            continue
        (flow if account.type in FLOW_TYPES else sheet).append(p)
    return flow, sheet


def funding_mix(led: Ledger, start: date, end: date,
                skip_recurring: bool = False) -> tuple[dict, dict, int, int]:
    """How each income/expense account was funded, and the run-rate of
    transfers that never touch an income statement at all.

    Returns `(ratios, transfers, mixed_count, transfer_count)`, where
    `ratios[flow_account_id][sheet_account_id]` is a multiple of the flow
    account's own raw amount, and `transfers[account_id]` is a raw total
    over the window (callers divide by its length).

    A run-rate is a claim that something *repeats*, so two kinds of
    balance-sheet movement are deliberately kept out of it: anything that
    touches equity — opening balances, a period close, an archive plug —
    and any transfer seen in only one month of a multi-month window. A
    house deposit is not $5,000 a month forever.
    """
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    mix: dict[int, dict[int, float]] = {}
    flow_total: dict[int, int] = {}
    shapes: dict[tuple, dict] = {}
    mixed = pure = 0
    for txn in led.transactions(start=start, end=end):
        if skip_recurring and RECURRING_TAG in txn.tags:
            continue
        flow, sheet = _flow_split(txn.postings, accounts)
        if not flow:
            if any(accounts[p.account_id].type is AccountType.EQUITY
                   for p in sheet):
                continue
            pure += 1
            # Direction is part of what repeats: a monthly sweep into the
            # brokerage and a one-off sale out of it touch the same two
            # accounts but are not the same behaviour.
            shape = shapes.setdefault(
                tuple(sorted((p.account_id,
                              (p.amount > 0) - (p.amount < 0))
                             for p in sheet)),
                {"months": set(), "legs": {}})
            shape["months"].add(f"{txn.date:%Y-%m}")
            for p in sheet:
                shape["legs"][p.account_id] = \
                    shape["legs"].get(p.account_id, 0) + p.amount
            continue
        mixed += 1
        total = sum(p.amount for p in flow)
        if total == 0:
            # Income and expense legs that cancel (a reclassification, say)
            # give no basis for attributing the funding side.
            continue
        for fp in flow:
            share = fp.amount / total
            flow_total[fp.account_id] = flow_total.get(fp.account_id, 0) \
                + fp.amount
            bucket = mix.setdefault(fp.account_id, {})
            for sp in sheet:
                bucket[sp.account_id] = bucket.get(sp.account_id, 0.0) \
                    + sp.amount * share
    ratios = {
        acct: {b: v / flow_total[acct] for b, v in bucket.items()}
        for acct, bucket in mix.items() if flow_total.get(acct)
    }
    span = max((end.year - start.year) * 12 + end.month - start.month + 1, 1)
    transfers: dict[int, int] = {}
    for shape in shapes.values():
        if span > 1 and len(shape["months"]) < 2:
            continue  # a one-off, not a run-rate
        for account_id, amount in shape["legs"].items():
            transfers[account_id] = transfers.get(account_id, 0) + amount
    return ratios, transfers, mixed, pure


class ProForma:
    """A read-only overlay of projected transactions on a ledger.

    Implements the five methods the statement builders call — `accounts`,
    `balances`, `flows`, `transactions`, `loans` — plus `position`.
    Everything else delegates to the underlying ledger and therefore sees
    history only; nothing in `reports.py` needs more than this.
    """

    def __init__(self, led: Ledger, txns: list[Transaction], **meta):
        self._led = led
        self.txns = txns
        self.__dict__.update(meta)

    def __getattr__(self, name):
        return getattr(self._led, name)

    # -- the surface the statement builders use ---------------------------

    def accounts(self, *args, **kwargs) -> list[Account]:
        return self._led.accounts(*args, **kwargs)

    def loans(self):
        return self._led.loans()

    def balances(self, as_of: date | None = None) -> dict[int, int]:
        raw = dict(self._led.balances(as_of=as_of))
        for txn in self.txns:
            if as_of is None or txn.date <= as_of:
                for p in txn.postings:
                    raw[p.account_id] = raw.get(p.account_id, 0) + p.amount
        return raw

    def flows(self, start: date | None, end: date) -> dict[int, int]:
        raw = dict(self._led.flows(start, end))
        for txn in self.txns:
            if (start is None or txn.date >= start) and txn.date <= end:
                for p in txn.postings:
                    raw[p.account_id] = raw.get(p.account_id, 0) + p.amount
        return raw

    def transactions(self, start: date | None = None,
                     end: date | None = None, **kwargs) -> list[Transaction]:
        out = list(self._led.transactions(start=start, end=end, **kwargs))
        out += [t for t in self.txns
                if (start is None or t.date >= start)
                and (end is None or t.date <= end)]
        out.sort(key=lambda t: (t.date, t.id))
        return out

    def position(self, as_of: date | None = None,
                 raw: dict[int, int] | None = None) -> dict[str, int]:
        if raw is None:
            raw = self.balances(as_of=as_of)
        return self._led.position(as_of=as_of, raw=raw)


@dataclass
class _Plan:
    """Everything decided before a single transaction is generated."""

    base_date: date
    window_start: date
    window_end: date
    stub_end: date | None
    future_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _lookback_window(led: Ledger, base_date: date, lookback: int):
    """The history window, never reaching back past the ledger's own
    history — months that predate it are not months of zero income and
    zero spending, and averaging them in projects a household that
    neither earns nor spends."""
    this_month = month_bounds(base_date.year, base_date.month)[0]
    start = add_months(this_month, -lookback)
    begins = led.history_begins
    if begins:
        earliest = month_bounds(begins.year, begins.month)[0]
        if earliest > start:
            start = earliest
    months = max((this_month.year - start.year) * 12
                 + this_month.month - start.month, 0)
    return start, this_month - timedelta(days=1), months


def project(led: Ledger, months: int = 6, method: str = "average",
            lookback: int = 6, use_budget: bool = False,
            use_recurring: bool = False,
            base_date: date | None = None) -> ProForma:
    """Build the pro-forma ledger: history plus projected transactions
    covering `(base_date, end of the month `months` out]`."""
    if method not in ("average", "trend"):
        raise ValueError(f"unknown forecast method: {method}")
    base_date = base_date or date.today()
    requested_lookback = lookback
    this_month, month_end = month_bounds(base_date.year, base_date.month)
    hist_start, hist_end, lookback = _lookback_window(led, base_date,
                                                      lookback)
    hist_keys = month_keys(hist_start, lookback)

    plan = _Plan(
        base_date=base_date,
        window_start=base_date + timedelta(days=1),
        window_end=add_months(this_month, months + 1) - timedelta(days=1),
        stub_end=month_end if base_date < month_end else None,
        future_keys=month_keys(this_month, months + 1)[1:],
    )
    begins = led.history_begins
    if lookback < requested_lookback:
        detail = (f"; this ledger's history begins {begins.isoformat()}"
                  if begins else "")
        if not lookback:
            plan.warnings.append(
                "No complete month of history to project from"
                f"{detail} — the figures below carry no historical basis.")
        else:
            plan.warnings.append(
                f"Only {lookback} of the {requested_lookback} requested "
                f"months of history are available{detail}.")

    builder = _Builder(led, plan, method, hist_start, hist_end,
                       hist_keys, use_budget, use_recurring)
    txns = builder.build()
    return ProForma(
        led, txns,
        drivers=builder.drivers,
        transfers=builder.transfers,
        funding=builder.funding,
        base_date=base_date,
        window_start=plan.window_start,
        window_end=plan.window_end,
        stub_end=plan.stub_end,
        future_keys=plan.future_keys,
        horizon_months=months,
        method=method,
        lookback_months=lookback,
        lookback_requested=requested_lookback,
        history_begins=begins,
        use_budget=use_budget,
        use_recurring=use_recurring,
        warnings=plan.warnings,
    )


class _Builder:
    """Turns the projection basis into balanced transactions."""

    def __init__(self, led, plan, method, hist_start, hist_end,
                 hist_keys, use_budget, use_recurring):
        self.led = led
        self.plan = plan
        self.method = method
        self.hist_start, self.hist_end = hist_start, hist_end
        self.hist_keys = hist_keys
        self.use_budget = use_budget
        self.use_recurring = use_recurring
        self.accounts = {a.id: a for a in led.accounts(include_closed=True)}
        self._next_id = 0
        self._opening = led.balances(as_of=plan.base_date)
        self.funding: dict[int, dict[int, float]] = {}
        self.transfers: dict[int, int] = {}
        self.drivers: list[Driver] = []

    # -- basis ------------------------------------------------------------

    def _mix_window(self) -> tuple[date, date]:
        """The window the funding mix is read from. `beans archive` replaces
        an archived month with one summary transaction carrying that month's
        totals — which bundles every account into a single cash-touching
        entry and would smear the mix across everything and erase the pure
        transfers entirely. So the mix stops where line-item detail does."""
        start = self.hist_start
        detail = self.led.detail_begins
        if detail and detail > start:
            if detail > self.hist_end:
                self.plan.warnings.append(
                    "No line-item detail in the lookback window (it is "
                    f"archived through {detail - timedelta(days=1)}) — "
                    "projected balances fall back to the primary cash "
                    "account and transfers cannot be projected.")
                return start, start - timedelta(days=1)
            self.plan.warnings.append(
                f"Line-item detail begins {detail.isoformat()}; the funding "
                "mix behind projected balances is read from there on, not "
                "from the full lookback window.")
            start = detail
        return start, self.hist_end

    def _primary_cash(self) -> int | None:
        """The account an unattributable projection is funded from: the
        fullest cash account, else the fullest asset account."""
        def pick(pool):
            ranked = sorted(pool, key=lambda a: (-self._opening.get(a.id, 0),
                                                 a.name))
            return ranked[0].id if ranked else None

        assets = [a for a in self.led.accounts(type_=AccountType.ASSET)]
        return pick([a for a in assets if a.is_cash]) or pick(assets)

    def _build_drivers(self) -> None:
        flow_accounts = [a for a in self.led.accounts()
                         if a.type in FLOW_TYPES]
        monthly = self.led.monthly_flows(
            [a.id for a in flow_accounts], self.hist_start, self.hist_end)
        budgets = budget_accounts(self.led) if self.use_budget else {}
        scheduled = self._scheduled_accounts()
        mtd = self.led.flows(
            month_bounds(self.plan.base_date.year,
                         self.plan.base_date.month)[0], self.plan.base_date)
        steps = len(self.plan.future_keys)
        for account in flow_accounts:
            sign = account.type.natural_sign
            if account.id in scheduled:
                # A recurring rule supplies the whole transaction, legs and
                # all, so this account is projected from the schedule alone.
                self.drivers.append(Driver(account, [0] * steps, "recurring"))
                continue
            if account.id in budgets:
                series = [budgets[account.id]] * steps
                source = "budget"
            else:
                history = [monthly.get((account.id, key), 0) * sign
                           for key in self.hist_keys]
                series = project_series(history, self.method, steps)
                source = self.method
            driver = Driver(account, series, source)
            if self.plan.stub_end is not None and series:
                # Complete the part-elapsed month up to the run-rate rather
                # than pro-rating by days: what has already happened this
                # month is in the ledger, and a category whose whole month
                # landed on the 1st has nothing left to project.
                done = mtd.get(account.id, 0) * sign
                driver.stub = max(series[0] - done, 0)
            self.drivers.append(driver)

    def _scheduled_accounts(self) -> set[int]:
        """Income/expense accounts an active recurring rule posts to inside
        the projection window."""
        if not self.use_recurring:
            return set()
        covered = set()
        for rec in self.led.recurrings():
            if not rec.active:
                continue
            for due in pending_occurrences(rec, self.plan.window_end):
                if due < self.plan.window_start:
                    continue
                for p in rec.postings:
                    account = self.accounts.get(p.account_id)
                    if account and account.type in FLOW_TYPES:
                        covered.add(account.id)
                break
        return covered

    def _build_transfers(self, mix_months: int) -> None:
        """Per-month run-rate of transactions with no income/expense leg."""
        if mix_months <= 0:
            return
        gross = sum(abs(v) for v in self._raw_transfers.values())
        if not gross:
            return
        self.transfers = {b: round(v / mix_months)
                          for b, v in self._raw_transfers.items()}
        residual = sum(self.transfers.values())
        if residual:
            biggest = max(self.transfers,
                          key=lambda b: (abs(self.transfers[b]), -b))
            self.transfers[biggest] -= residual

    # -- generation -------------------------------------------------------

    def build(self) -> list[Transaction]:
        mix_start, mix_end = self._mix_window()
        mix_months = 0
        if mix_start <= mix_end:
            self.funding, self._raw_transfers, _, _ = funding_mix(
                self.led, mix_start, mix_end,
                skip_recurring=self.use_recurring)
            mix_months = max((mix_end.year - mix_start.year) * 12
                             + mix_end.month - mix_start.month + 1, 1)
        else:
            self._raw_transfers = {}
        self._build_drivers()
        self._build_transfers(mix_months)
        self.cash_id = self._primary_cash()
        self._loan_state = self._loan_plan()
        amortized = {s["expense"] for s in self._loan_state.values()}
        for driver in self.drivers:
            if driver.account.id in amortized:
                driver.source = "amortized"

        txns: list[Transaction] = []
        periods = []
        if self.plan.stub_end is not None:
            periods.append((self.plan.stub_end, None, self._stub_scale()))
        for index, key in enumerate(self.plan.future_keys):
            year, month = int(key[:4]), int(key[5:])
            periods.append((month_bounds(year, month)[1], index, 1.0))

        for when, index, scale in periods:
            for driver in self.drivers:
                amount = (driver.stub if index is None
                          else driver.monthly[index])
                amount *= driver.account.type.natural_sign
                if not amount:
                    continue
                legs = self._fund(driver.account.id, amount)
                self._amortize(driver.account.id, legs)
                txn = self._txn(when, f"Projected: {driver.account.name}",
                                legs, driver=driver.account.id)
                if txn is not None:
                    txns.append(txn)
            legs = {b: round(v * scale) for b, v in self.transfers.items()}
            txn = self._txn(when, "Projected: transfers", legs)
            if txn is not None:
                txns.append(txn)
        txns += self._recurring_txns()
        return txns

    def _fund(self, account_id: int, amount: int) -> dict[int, int]:
        """One driver's balanced legs: the driver itself, plus the accounts
        that historically funded it — or the primary cash account when the
        books have never funded it before (a brand-new budget, say)."""
        legs = {account_id: amount}
        mix = self.funding.get(account_id)
        if mix:
            for b, ratio in mix.items():
                legs[b] = legs.get(b, 0) + round(amount * ratio)
        elif self.cash_id is not None:
            legs[self.cash_id] = legs.get(self.cash_id, 0) - amount
        return legs

    def _loan_plan(self) -> dict[int, dict]:
        """For each amortizing loan, the expense account it is paid through
        and its outstanding balance, so the projection can amortize on the
        schedule instead of freezing the historical interest/principal
        split — which, left alone, means a loan never amortizes at all."""
        state = {}
        for loan in self.led.loans():
            balance = -self._opening.get(loan.account_id, 0)
            if balance <= 0:
                continue
            paired = [(abs(ratio), -acct, acct)
                      for acct, mix in self.funding.items()
                      for target, ratio in mix.items()
                      if target == loan.account_id and ratio]
            if not paired:
                continue
            state[loan.account_id] = {
                "expense": max(paired)[2],
                "balance": balance,
                "rate": loans.periodic_rate(loan.annual_rate),
            }
        return state

    def _amortize(self, driver_id: int, legs: dict[int, int]) -> None:
        for account_id, loan in self._loan_state.items():
            if loan["expense"] != driver_id or account_id not in legs:
                continue
            payment = legs[account_id] + legs.get(driver_id, 0)
            if payment <= 0 or loan["balance"] <= 0:
                continue
            interest = loans._round_minor(
                Decimal(loan["balance"]) * loan["rate"])
            principal = min(payment - interest, loan["balance"])
            if principal <= 0:
                continue  # the payment no longer covers interest; leave it
            # The cash leg is untouched: the household pays what it pays,
            # and only the split between interest and principal moves.
            legs[driver_id] = payment - principal
            legs[account_id] = principal
            loan["balance"] -= principal

    def _txn(self, when: date, description: str, legs: dict[int, int],
             driver: int | None = None) -> Transaction | None:
        legs = {k: v for k, v in legs.items() if v}
        if not legs:
            return None
        residual = sum(legs.values())
        if residual:
            # Rounding never gets to unbalance the books: the remainder goes
            # to the largest funding leg, never to the driver itself (whose
            # amount is the projection and must be reported as projected).
            pool = {k: v for k, v in legs.items() if k != driver}
            target = (max(pool, key=lambda k: (abs(pool[k]), -k))
                      if pool else self.cash_id)
            if target is None:
                return None
            legs[target] = legs.get(target, 0) - residual
        self._next_id -= 1
        return Transaction(
            id=self._next_id, date=when, description=description,
            tags=[PROJECTED_TAG],
            postings=[Posting(account_id=k, amount=v,
                              account_name=self.accounts[k].name)
                      for k, v in legs.items() if v])

    def _stub_scale(self) -> float:
        """How much of the month's transfer run-rate is still to come.
        Transfers are scaled as a whole rather than per account, because
        scaling a zero-sum vector keeps it balanced."""
        projected = sum(abs(v) for v in self.transfers.values())
        if not projected:
            return 0.0
        month_start = month_bounds(self.plan.base_date.year,
                                   self.plan.base_date.month)[0]
        _, done, _, _ = funding_mix(self.led, month_start,
                                    self.plan.base_date,
                                    skip_recurring=self.use_recurring)
        spent = sum(abs(v) for v in done.values())
        return max(1.0 - spent / projected, 0.0)

    def _recurring_txns(self) -> list[Transaction]:
        """Scheduled transactions at their exact amounts and dates. The
        rule carries every leg, so these need no funding mix at all."""
        if not self.use_recurring:
            return []
        out = []
        for rec in self.led.recurrings():
            if not rec.active:
                continue
            # pending_occurrences carries the MAX_RUN_PER_RULE runaway guard.
            for due in pending_occurrences(rec, self.plan.window_end):
                if due < self.plan.window_start:
                    continue  # overdue and unposted; `recur run` owns it
                self._next_id -= 1
                out.append(Transaction(
                    id=self._next_id, date=due,
                    description=f"Projected: {rec.description or rec.name}",
                    payee=rec.payee, tags=[PROJECTED_TAG, RECURRING_TAG],
                    postings=[Posting(account_id=p.account_id,
                                      amount=p.amount,
                                      account_name=self.accounts[
                                          p.account_id].name)
                              for p in rec.postings]))
        return out
