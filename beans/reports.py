"""Financial statements: income statement, balance sheet, statement of
cash flows, trial balance, account register, and balance listings.

Each report builds a plain dict of data (amounts in integer minor units)
and has a renderer that turns it into aligned text. `jsonify` converts a
report dict to JSON-ready form with major-unit decimal strings.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from beans import loans
from beans.ledger import Ledger
from beans.models import AccountType
from beans.render import Table, bold, money, rollup, strip_shared_root
from beans.utils import (BeansError, add_months, last_complete_period,
                         month_bounds, parse_period, period_key,
                         period_months, prior_period, shift_period)


def to_major(minor: int, decimals: int) -> str:
    return str(Decimal(minor).scaleb(-decimals).quantize(
        Decimal(1).scaleb(-decimals) if decimals else Decimal(1)))


class Money:
    """A money amount in minor units carrying its own precision, for fields
    denominated in a currency other than the ledger base (e.g. a foreign
    balance in JPY). `jsonify` renders it at the embedded precision instead
    of the base decimals, so per-currency money handling lives here in the
    serializer rather than being re-implemented inline at each call site."""

    __slots__ = ("minor", "decimals")

    def __init__(self, minor: int | None, decimals: int):
        self.minor = minor
        self.decimals = decimals


# Report-dict keys whose integer values are counts, not money.
NON_MONEY_KEYS = {"id", "months", "horizon_months", "lookback_months",
                  "posted_count", "number", "term_months",
                  "payments_remaining", "work_months", "live_months",
                  # reconcile --statement: row counts, CSV line numbers and
                  # day counts, none of which are money.
                  "line", "rows", "drift_days", "window_days", "matched",
                  "date_drift", "amount_mismatch", "bank_only",
                  "outstanding", "cleared_missing",
                  # categorize: counts by source, and how many prior
                  # transactions the classifier learned from.
                  "history_size", "column", "rule", "history",
                  "unresolved",
                  # import: row counts in the summary. The top-level
                  # "imported"/"skipped" keys hold lists, which fall
                  # through to the recursive branch either way.
                  "imported", "skipped",
                  # trend: how many periods the series spans, and how
                  # many of them had fully elapsed.
                  "period_count", "complete_periods"}


def jsonify(value, decimals: int):
    """Convert a report dict for JSON output: every int is money in minor
    units and becomes a major-unit decimal string (except known counts).
    A `Money` value carries its own precision (for foreign currencies)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, Money):
        return (None if value.minor is None
                else to_major(value.minor, value.decimals))
    if isinstance(value, int):
        return to_major(value, decimals)
    if isinstance(value, dict):
        return {
            k: v if k in NON_MONEY_KEYS and isinstance(v, (bool, int))
            else jsonify(v, decimals)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [jsonify(v, decimals) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _natural_by_name(led: Ledger, raw: dict[int, int],
                     type_: AccountType) -> dict[str, int]:
    """Map account name -> natural-sign amount for one account type."""
    out = {}
    for account in led.accounts(type_=type_, include_closed=True):
        amount = raw.get(account.id, 0)
        if amount:
            out[account.name] = amount * type_.natural_sign
    return out


def _tree_rows(table: Table, amounts: dict[str, int], decimals: int,
               indent: str = "  ", extra=None) -> None:
    tree = strip_shared_root(rollup(amounts), amounts)
    for name, depth, amount, is_leaf in tree:
        label = indent + "  " * depth + name
        if is_leaf:
            cols = [label, money(amount, decimals)]
            if extra:
                cols.append(extra(name, amount))
            table.add(*cols)
        else:
            table.add(label, "")


# -- income statement -------------------------------------------------------


def income_statement(led: Ledger, start: date | None, end: date,
                     label: str, compare: bool = False) -> dict:
    flows = led.flows(start, end)
    data = {
        "report": "income_statement",
        "period": label,
        "start": start,
        "end": end,
        "income": _natural_by_name(led, flows, AccountType.INCOME),
        "expenses": _natural_by_name(led, flows, AccountType.EXPENSE),
    }
    data["total_income"] = sum(data["income"].values())
    data["total_expenses"] = sum(data["expenses"].values())
    data["net_income"] = data["total_income"] - data["total_expenses"]
    if compare:
        if start is None:
            # An unbounded period has no prior period to compare against;
            # degrade gracefully with a note instead of erroring out.
            data["compare_note"] = (
                "comparison unavailable for an unbounded period "
                "(use a bounded period or --from/--to)")
        else:
            p_start, p_end, p_label = prior_period(start, end)
            data["compare"] = income_statement(led, p_start, p_end, p_label)
    return data


def render_income_statement(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("INCOME STATEMENT"), f"For the period: {data['period']}", ""]
    total_income = data["total_income"]

    def pct(_name: str, amount: int) -> str:
        if not total_income:
            return ""
        return f"{100 * amount / total_income:5.1f}%"

    table = Table(align="lrr")
    table.add(bold("Income"), "", "")
    _tree_rows(table, data["income"], decimals, extra=pct)
    table.rule()
    table.add(bold("Total Income"),
              money(total_income, decimals, symbol), pct("", total_income))
    table.add("", "", "")
    table.add(bold("Expenses"), "", "")
    _tree_rows(table, data["expenses"], decimals, extra=pct)
    table.rule()
    table.add(bold("Total Expenses"),
              money(data["total_expenses"], decimals, symbol),
              pct("", data["total_expenses"]))
    table.rule()
    table.add(bold("Net Income"),
              money(data["net_income"], decimals, symbol),
              pct("", data["net_income"]))
    lines.append(table.render())

    if "compare" in data:
        prior = data["compare"]
        lines += ["", bold(f"Comparison with prior period ({prior['period']})")]
        cmp_table = Table(
            headers=["", "Current", "Prior", "Change"], align="lrrr"
        )
        for key, name in (("total_income", "Total Income"),
                          ("total_expenses", "Total Expenses"),
                          ("net_income", "Net Income")):
            cur, prev = data[key], prior[key]
            cmp_table.add(name, money(cur, decimals, symbol),
                          money(prev, decimals, symbol),
                          money(cur - prev, decimals, symbol))
        lines.append(cmp_table.render())
    if "compare_note" in data:
        lines += ["", data["compare_note"]]
    return "\n".join(lines)


# -- balance sheet -----------------------------------------------------------


def balance_sheet(led: Ledger, as_of: date, classified: bool = True) -> dict:
    raw = led.balances(as_of=as_of)
    assets = _natural_by_name(led, raw, AccountType.ASSET)
    liabilities = _natural_by_name(led, raw, AccountType.LIABILITY)
    equity = _natural_by_name(led, raw, AccountType.EQUITY)
    # Retained earnings: cumulative net income never formally "closed" to
    # equity, computed on the fly as corporate systems do at close.
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    retained = -sum(
        amount for acct_id, amount in raw.items()
        if acct_id in accounts
        and accounts[acct_id].type in (AccountType.INCOME, AccountType.EXPENSE)
    )
    total_assets = sum(assets.values())
    total_liabilities = sum(liabilities.values())
    total_equity = sum(equity.values()) + retained

    # Current vs non-current split. Assets follow their liquidity tag;
    # liabilities are split by any attached loan's amortization schedule,
    # falling back to the tag. Buckets always re-sum to the type totals.
    assets_current, assets_noncurrent = {}, {}
    for account in led.accounts(type_=AccountType.ASSET, include_closed=True):
        amount = raw.get(account.id, 0) * AccountType.ASSET.natural_sign
        if amount:
            bucket = assets_current if account.is_current else assets_noncurrent
            bucket[account.name] = amount
    liab_split = loans.classified_liability_split(led, as_of, raw)
    liabilities_current, liabilities_noncurrent = {}, {}
    for account in led.accounts(type_=AccountType.LIABILITY,
                                include_closed=True):
        current, noncurrent = liab_split.get(account.id, (0, 0))
        if current:
            liabilities_current[account.name] = current
        if noncurrent:
            liabilities_noncurrent[account.name] = noncurrent

    return {
        "report": "balance_sheet",
        "as_of": as_of,
        "classified": classified,
        "assets": assets,
        "assets_current": assets_current,
        "assets_noncurrent": assets_noncurrent,
        "liabilities": liabilities,
        "liabilities_current": liabilities_current,
        "liabilities_noncurrent": liabilities_noncurrent,
        "equity": equity,
        "retained_earnings": retained,
        "total_assets": total_assets,
        "total_assets_current": sum(assets_current.values()),
        "total_assets_noncurrent": sum(assets_noncurrent.values()),
        "total_liabilities": total_liabilities,
        "total_liabilities_current": sum(liabilities_current.values()),
        "total_liabilities_noncurrent": sum(liabilities_noncurrent.values()),
        "total_equity": total_equity,
        "net_worth": total_assets - total_liabilities,
        "balanced": total_assets == total_liabilities + total_equity,
    }


def render_balance_sheet(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("BALANCE SHEET"), f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(align="lr")

    def block(title: str, amounts: dict[str, int], total: int) -> None:
        table.add(bold(title), "")
        _tree_rows(table, amounts, decimals)
        table.rule()
        table.add(bold(f"Total {title}"), money(total, decimals, symbol))
        table.add("", "")

    def subtotal(label: str, amounts: dict[str, int], total: int) -> None:
        if not amounts:
            return
        table.add("  " + bold(label), "")
        _tree_rows(table, amounts, decimals, indent="    ")
        table.add("  " + label + " subtotal", money(total, decimals, symbol))

    def classified_block(title: str, cur: dict[str, int], cur_total: int,
                         non: dict[str, int], non_total: int,
                         total: int) -> None:
        table.add(bold(title), "")
        subtotal(f"Current {title}", cur, cur_total)
        subtotal(f"Non-current {title}", non, non_total)
        table.rule()
        table.add(bold(f"Total {title}"), money(total, decimals, symbol))
        table.add("", "")

    if data.get("classified", True):
        classified_block(
            "Assets", data["assets_current"], data["total_assets_current"],
            data["assets_noncurrent"], data["total_assets_noncurrent"],
            data["total_assets"])
        classified_block(
            "Liabilities", data["liabilities_current"],
            data["total_liabilities_current"], data["liabilities_noncurrent"],
            data["total_liabilities_noncurrent"], data["total_liabilities"])
    else:
        block("Assets", data["assets"], data["total_assets"])
        block("Liabilities", data["liabilities"], data["total_liabilities"])
    table.add(bold("Equity"), "")
    _tree_rows(table, data["equity"], decimals)
    table.add("  Retained Earnings",
              money(data["retained_earnings"], decimals))
    table.rule()
    table.add(bold("Total Equity"),
              money(data["total_equity"], decimals, symbol))
    table.rule()
    table.add(bold("Liabilities + Equity"),
              money(data["total_liabilities"] + data["total_equity"],
                    decimals, symbol))
    table.add(bold("Net Worth"),
              money(data["net_worth"], decimals, symbol))
    lines.append(table.render())
    if not data["balanced"]:
        lines.append("WARNING: balance sheet does not balance — "
                     "the ledger may be corrupted")
    return "\n".join(lines)


# -- statement of cash flows -------------------------------------------------


def cash_flow_statement(led: Ledger, start: date | None, end: date,
                        label: str) -> dict:
    accounts = {a.id: a for a in led.accounts(include_closed=True)}
    cash_ids = {a.id for a in accounts.values() if a.is_cash}
    sections: dict[str, dict[str, int]] = {
        "operating": {}, "investing": {}, "financing": {}
    }
    for txn in led.transactions(start=start, end=end):
        cash_delta = sum(
            p.amount for p in txn.postings if p.account_id in cash_ids
        )
        if cash_delta == 0:
            continue
        # The cash legs sum to the negation of the non-cash legs, so each
        # non-cash posting (negated) is that account's exact cash effect.
        for p in txn.postings:
            if p.account_id in cash_ids:
                continue
            account = accounts[p.account_id]
            bucket = sections[account.cashflow]
            bucket[account.name] = bucket.get(account.name, 0) - p.amount

    begin = (start - timedelta(days=1)) if start else None
    raw_begin = led.balances(as_of=begin) if begin else {}
    raw_end = led.balances(as_of=end)
    cash_begin = sum(raw_begin.get(i, 0) for i in cash_ids) if begin else 0
    cash_end = sum(raw_end.get(i, 0) for i in cash_ids)
    data = {
        "report": "cash_flow_statement",
        "period": label,
        "start": start,
        "end": end,
        "operating": sections["operating"],
        "investing": sections["investing"],
        "financing": sections["financing"],
        "net_operating": sum(sections["operating"].values()),
        "net_investing": sum(sections["investing"].values()),
        "net_financing": sum(sections["financing"].values()),
        "cash_beginning": cash_begin,
        "cash_ending": cash_end,
    }
    data["net_change"] = (data["net_operating"] + data["net_investing"]
                          + data["net_financing"])
    return data


def render_cash_flow_statement(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("STATEMENT OF CASH FLOWS"),
             f"For the period: {data['period']}", ""]
    table = Table(align="lr")
    for key, title in (("operating", "Operating Activities"),
                       ("investing", "Investing Activities"),
                       ("financing", "Financing Activities")):
        table.add(bold(f"Cash Flows from {title}"), "")
        amounts = data[key]
        for name in sorted(amounts, key=str.lower):
            table.add("  " + name, money(amounts[name], decimals))
        table.rule()
        table.add(bold(f"Net Cash from {title}"),
                  money(data[f"net_{key}"], decimals, symbol))
        table.add("", "")
    table.rule()
    table.add(bold("Net Change in Cash"),
              money(data["net_change"], decimals, symbol))
    table.add("Cash at Beginning of Period",
              money(data["cash_beginning"], decimals, symbol))
    table.add(bold("Cash at End of Period"),
              money(data["cash_ending"], decimals, symbol))
    lines.append(table.render())
    return "\n".join(lines)


# -- trial balance and balances ----------------------------------------------


def trial_balance(led: Ledger, as_of: date) -> dict:
    raw = led.balances(as_of=as_of)
    rows = []
    for account in led.accounts(include_closed=True):
        amount = raw.get(account.id, 0)
        if amount == 0:
            continue
        rows.append({
            "account": account.name,
            "debit": amount if amount > 0 else 0,
            "credit": -amount if amount < 0 else 0,
        })
    return {
        "report": "trial_balance",
        "as_of": as_of,
        "rows": rows,
        "total_debits": sum(r["debit"] for r in rows),
        "total_credits": sum(r["credit"] for r in rows),
    }


def render_trial_balance(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("TRIAL BALANCE"), f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(headers=["Account", "Debit", "Credit"], align="lrr")
    for row in data["rows"]:
        table.add(row["account"],
                  money(row["debit"], decimals) if row["debit"] else "",
                  money(row["credit"], decimals) if row["credit"] else "")
    table.rule()
    table.add(bold("Totals"),
              money(data["total_debits"], decimals, symbol),
              money(data["total_credits"], decimals, symbol))
    lines.append(table.render())
    if data["total_debits"] != data["total_credits"]:
        lines.append("WARNING: debits do not equal credits")
    return "\n".join(lines)


def balances_report(led: Ledger, as_of: date) -> dict:
    raw = led.balances(as_of=as_of)
    sections = {}
    for type_ in AccountType:
        amounts = _natural_by_name(led, raw, type_)
        if amounts:
            sections[type_.value] = amounts
    return {"report": "balances", "as_of": as_of, "sections": sections}


def render_balances(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("ACCOUNT BALANCES"),
             f"As of: {data['as_of'].isoformat()}", ""]
    table = Table(align="lr")
    for type_ in AccountType:
        amounts = data["sections"].get(type_.value)
        if not amounts:
            continue
        table.add(bold(type_.label), "")
        _tree_rows(table, amounts, decimals)
        table.rule()
        table.add(bold(f"Total {type_.label}"),
                  money(sum(amounts.values()), decimals, symbol))
        table.add("", "")
    lines.append(table.render())
    return "\n".join(lines)


# -- net worth trend ---------------------------------------------------------


def net_worth_trend(led: Ledger, months: int, end: date | None = None) -> dict:
    """Month-end assets, liabilities, and net worth for the last `months`
    months — the household equivalent of a book-value trend.

    Computed from one grouped scan of the ledger (monthly deltas by
    account type) accumulated into running balances, instead of a full
    balances() aggregation per month."""
    end = end or date.today()
    deltas = led.monthly_type_totals(end)
    this_month_start = month_bounds(end.year, end.month)[0]
    first_shown = add_months(this_month_start, -(months - 1))

    assets = liabilities = 0
    # Seed running totals with everything before the displayed window.
    for ym in sorted(deltas):
        if ym >= f"{first_shown:%Y-%m}":
            break
        assets += deltas[ym].get("asset", 0)
        liabilities -= deltas[ym].get("liability", 0)

    rows = []
    prev_net = None
    for i in range(months):
        m_start = add_months(first_shown, i)
        ym = f"{m_start:%Y-%m}"
        assets += deltas.get(ym, {}).get("asset", 0)
        liabilities -= deltas.get(ym, {}).get("liability", 0)
        net = assets - liabilities
        rows.append({
            "month": ym,
            "as_of": min(month_bounds(m_start.year, m_start.month)[1], end),
            "assets": assets,
            "liabilities": liabilities,
            "net_worth": net,
            "change": (net - prev_net) if prev_net is not None else 0,
        })
        prev_net = net
    return {"report": "net_worth_trend", "months": months, "rows": rows}


def render_net_worth_trend(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold("NET WORTH TREND"),
             f"Last {data['months']} months (month-end balances)", ""]
    table = Table(headers=["Month", "Assets", "Liabilities", "Net Worth",
                           "Change"], align="lrrrr")
    for row in data["rows"]:
        table.add(row["month"],
                  money(row["assets"], decimals),
                  money(row["liabilities"], decimals),
                  money(row["net_worth"], decimals),
                  money(row["change"], decimals))
    lines.append(table.render())
    if data["rows"]:
        first, last = data["rows"][0], data["rows"][-1]
        total_change = last["net_worth"] - first["net_worth"]
        lines.append("")
        lines.append(f"Change over period: "
                     f"{money(total_change, decimals, symbol)}")
    return "\n".join(lines)


# -- trend -------------------------------------------------------------------


def trend(led: Ledger, count: int = 12, grain: str = "month",
          end_key: str | None = None, today: date | None = None,
          include_partial: bool = False) -> dict:
    """Income, expenses, net and per-account flows across N periods.

    Every other statement here is a snapshot, and `income_statement`'s
    `compare` reaches exactly one period back, so a question about drift
    ("are groceries creeping up?") has had no report to answer it. This is
    that report: one grouped scan of monthly flows folded into month or
    quarter buckets, rather than N separate statement runs.

    The window ends at the last *complete* period unless `include_partial`
    is set — see `last_complete_period` for why that default is not merely
    a convenience.
    """
    if count < 1:
        raise BeansError("a trend needs at least one period")
    if grain not in ("month", "quarter"):
        raise BeansError(f"invalid grain: {grain!r} (use month or quarter)")

    today = today or date.today()
    current = period_key(today, grain)
    complete = last_complete_period(today, grain)
    if end_key is None:
        end_key = current if include_partial else complete
    else:
        # Validate, and normalize ('2026-q2' -> '2026-Q2', '2026-6' ->
        # '2026-06'), so the keys echoed back are the ones bounds were taken
        # from.
        end_key = period_key(parse_period(end_key)[0], grain)

    keys = [shift_period(end_key, offset, grain)
            for offset in range(-(count - 1), 1)]
    bounds = {key: parse_period(key)[:2] for key in keys}
    window_start = bounds[keys[0]][0]
    window_end = min(bounds[keys[-1]][1], today)

    accounts = [account for account in led.accounts(include_closed=True)
                if account.type in (AccountType.INCOME, AccountType.EXPENSE)]
    flows = led.monthly_flows([a.id for a in accounts],
                              window_start, window_end)
    months = {key: period_months(key) for key in keys}

    series: list[dict] = []
    for account in accounts:
        amounts = [
            sum(flows.get((account.id, ym), 0) for ym in months[key])
            * account.type.natural_sign
            for key in keys
        ]
        # An account with no flow anywhere in the window is not a row of
        # zeros worth printing; it simply did not participate.
        if not any(amounts):
            continue
        total = sum(amounts)
        series.append({
            "account": account.name,
            "type": account.type.value,
            "amounts": amounts,
            "total": total,
            "average": round(total / len(keys)),
            "first": amounts[0],
            "last": amounts[-1],
            "change": amounts[-1] - amounts[0],
        })

    rows = []
    for index, key in enumerate(keys):
        income = sum(row["amounts"][index] for row in series
                     if row["type"] == AccountType.INCOME.value)
        expenses = sum(row["amounts"][index] for row in series
                       if row["type"] == AccountType.EXPENSE.value)
        net = income - expenses
        start, end = bounds[key]
        rows.append({
            "period": key,
            "start": start,
            "end": min(end, today),
            "partial": key > complete,
            "income": income,
            "expenses": expenses,
            "net_income": net,
            "savings_rate_pct": (round(100 * net / income, 1)
                                 if income else None),
        })

    # Biggest mover first: what changed is the reason to run this report.
    series.sort(key=lambda row: (-abs(row["change"]), row["account"]))

    # Averages are taken over COMPLETE periods only. A part-elapsed period
    # holds part of a month's spending against a whole month of history, so
    # averaging it in drags every summary figure toward a number that
    # describes nothing — the same trap the default window avoids.
    complete_rows = [row for row in rows if not row["partial"]]
    # Averaging nothing is not an option, so a window that is entirely in
    # progress averages what it has — and says so by reporting zero complete
    # periods, rather than quietly implying the figure is comparable.
    whole = complete_rows or rows
    total_income = sum(row["income"] for row in whole)
    total_expenses = sum(row["expenses"] for row in whole)
    return {
        "report": "trend",
        "grain": grain,
        "period_count": len(keys),
        "periods": keys,
        "complete_through": complete,
        # Name the period left out, so a reader knows why the series stops
        # where it does rather than assuming the ledger is behind. Only when
        # one actually was: run on the last day of a month, nothing is in
        # progress and claiming otherwise would be its own small lie.
        "excluded_partial": (current if current != complete
                             and end_key == complete else None),
        "rows": rows,
        "accounts": series,
        "totals": {
            "income": total_income,
            "expenses": total_expenses,
            "net_income": total_income - total_expenses,
            "complete_periods": len(complete_rows),
            "average_income": round(total_income / len(whole)),
            "average_expenses": round(total_expenses / len(whole)),
            "savings_rate_pct": (
                round(100 * (total_income - total_expenses) / total_income, 1)
                if total_income else None),
        },
    }


def render_trend(data: dict, decimals: int, symbol: str) -> str:
    grain = data["grain"]
    heading = f"Last {data['period_count']} {grain}s"
    if data["periods"]:
        heading += f": {data['periods'][0]} to {data['periods'][-1]}"
    lines = [bold("TREND"), heading]
    if data.get("excluded_partial"):
        lines.append(f"{data['excluded_partial']} is still in progress and is "
                     "excluded.")
    lines.append("")

    def pct(value) -> str:
        return f"{value:.1f}%" if value is not None else "n/a"

    table = Table(headers=["Period", "Income", "Expenses", "Net", "Savings"],
                  align="lrrrr")
    for row in data["rows"]:
        table.add(row["period"] + (" *" if row["partial"] else ""),
                  money(row["income"], decimals),
                  money(row["expenses"], decimals),
                  money(row["net_income"], decimals),
                  pct(row["savings_rate_pct"]))
    totals = data["totals"]
    table.rule()
    table.add("Average",
              money(totals["average_income"], decimals),
              money(totals["average_expenses"], decimals),
              money(totals["average_income"] - totals["average_expenses"],
                    decimals),
              pct(totals["savings_rate_pct"]))
    lines.append(table.render())
    if any(row["partial"] for row in data["rows"]):
        lines.append("* still in progress — not comparable to the others, "
                     "and excluded from the average.")

    if data["accounts"]:
        lines += ["", bold("BY ACCOUNT") + " (largest change first)"]
        by_account = Table(
            headers=["Account", "First", "Last", "Change", "Average"],
            align="lrrrr")
        for row in data["accounts"]:
            by_account.add(row["account"],
                           money(row["first"], decimals),
                           money(row["last"], decimals),
                           money(row["change"], decimals),
                           money(row["average"], decimals))
        lines.append(by_account.render())
        lines += ["", "Per-period figures for every account are in --json."]
    return "\n".join(lines)



# -- register ----------------------------------------------------------------


def register(led: Ledger, account, start: date | None, end: date) -> dict:
    opening = 0
    if start:
        prior = led.flows(None, start - timedelta(days=1))
        opening = prior.get(account.id, 0)
    rows = []
    running = opening
    for txn in led.transactions(start=start, end=end, account=account):
        delta = sum(
            p.amount for p in txn.postings if p.account_id == account.id
        )
        running += delta
        others = [p.account_name for p in txn.postings
                  if p.account_id != account.id]
        mine = [p for p in txn.postings if p.account_id == account.id]
        rows.append({
            "id": txn.id,
            "date": txn.date,
            "description": txn.description or txn.payee,
            "counter": ", ".join(others),
            "amount": delta * account.type.natural_sign,
            "balance": running * account.type.natural_sign,
            "cleared": all(p.cleared for p in mine),
        })
    return {
        "report": "register",
        "account": account.name,
        "opening_balance": opening * account.type.natural_sign,
        "rows": rows,
    }


def render_register(data: dict, decimals: int, symbol: str) -> str:
    lines = [bold(f"REGISTER — {data['account']}"), ""]
    table = Table(headers=["ID", "Date", "C", "Description",
                           "Counter-account", "Amount", "Balance"],
                  align="rllllrr")
    for row in data["rows"]:
        table.add(row["id"], row["date"].isoformat(),
                  "*" if row["cleared"] else "",
                  row["description"][:40], row["counter"][:40],
                  money(row["amount"], decimals),
                  money(row["balance"], decimals))
    lines.append(table.render())
    if not data["rows"]:
        lines.append("(no transactions in period)")
    return "\n".join(lines)
