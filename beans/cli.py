"""The `beans` command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from beans import __version__
from beans import (
    analysis,
    budget,
    completions,
    export,
    forecast,
    fx,
    goals,
    invest,
    reconcile,
    recurring,
    reports,
    status,
)
from beans.importer import import_csv
from beans.ledger import Ledger, ledger_path
from beans.models import RECURRENCE_FREQUENCIES, AccountType, Posting
from beans.render import Table, bold, money, red
from beans.utils import (
    BeansError,
    currency_decimals,
    currency_symbol,
    format_amount,
    month_bounds,
    parse_amount,
    parse_date,
    parse_fx_rate,
    parse_period,
)

PROG = "beans"


# -- helpers -----------------------------------------------------------------


def _open(args, create: bool = False) -> Ledger:
    """Open (or reuse) the ledger for this invocation; main() closes it."""
    led = getattr(args, "_ledger", None)
    if led is None:
        led = Ledger(ledger_path(args.file), create=create)
        args._ledger = led
    return led


def _symbol(led: Ledger) -> str:
    return currency_symbol(led.currency)


def _fmt(led: Ledger, minor: int) -> str:
    return format_amount(minor, led.decimals, _symbol(led))


def _period(args, default: str = "ytd"):
    return parse_period(
        getattr(args, "period", None),
        getattr(args, "from_date", None),
        getattr(args, "to_date", None),
        default=default,
    )


def _emit(args, led: Ledger, data: dict, renderer) -> None:
    if getattr(args, "json", False):
        print(json.dumps(reports.jsonify(data, led.decimals), indent=2))
    else:
        print(renderer(data, led.decimals, _symbol(led)))


def _print_transaction(led: Ledger, txn) -> None:
    flag = " (VOID)" if txn.void else ""
    header = f"#{txn.id}  {txn.date.isoformat()}  {txn.description}{flag}"
    if txn.payee:
        header += f"  [{txn.payee}]"
    if txn.tags:
        header += "  #" + " #".join(txn.tags)
    print(bold(header))
    table = Table(align="lr")
    for p in txn.postings:
        table.add(p.account_name, money(p.amount, led.decimals))
    print(table.render(indent="    "))


def _txn_to_dict(led: Ledger, txn) -> dict:
    return {
        "id": txn.id,
        "date": txn.date.isoformat(),
        "description": txn.description,
        "payee": txn.payee,
        "tags": txn.tags,
        "void": txn.void,
        "postings": [
            {"account": p.account_name,
             "amount": reports.to_major(p.amount, led.decimals)}
            for p in txn.postings
        ],
    }


# -- commands ----------------------------------------------------------------


def cmd_init(args) -> int:
    path = ledger_path(args.file)
    led = _open(args, create=True)
    led.initialize(currency=args.currency, with_chart=not args.bare)
    print(f"Initialized ledger at {path} (currency: {led.currency})")
    if not args.bare:
        count = len(led.accounts())
        print(f"Created a starter chart of {count} accounts — "
              "see `beans account list`.")
        print("Record opening balances against Equity:Opening Balances, "
              "e.g.:")
        print("  beans tx add --desc 'Opening balance' "
              "--post Assets:Checking 2500 --post 'Equity:Opening Balances'")
    return 0


def cmd_account_add(args) -> int:
    led = _open(args)
    type_ = AccountType(args.type)
    account = led.add_account(
        args.name, type_, is_cash=args.cash,
        cf_category=args.cashflow, description=args.desc,
        currency=args.currency,
    )
    notes = []
    if account.is_cash:
        notes.append("cash")
    if account.currency:
        notes.append(f"denominated in {account.currency}")
    notes.append(f"cash-flow: {account.cashflow}")
    print(f"Added {account.type.value} account "
          f"{account.name} ({', '.join(notes)})")
    return 0


def cmd_account_list(args) -> int:
    led = _open(args)
    type_ = AccountType(args.type) if args.type else None
    accounts = led.accounts(type_=type_, include_closed=args.all)
    if args.names:
        for a in accounts:
            print(a.name)
        return 0
    raw = led.balances()
    foreign = led.foreign_balances()
    if args.json:
        print(json.dumps([
            {
                "name": a.name, "type": a.type.value, "is_cash": a.is_cash,
                "cashflow": a.cashflow, "closed": a.closed,
                "balance": reports.to_major(
                    raw.get(a.id, 0) * a.type.natural_sign, led.decimals),
                "currency": a.currency,
                "foreign_balance": (
                    reports.to_major(
                        foreign.get(a.id, 0) * a.type.natural_sign,
                        currency_decimals(a.currency))
                    if a.currency else None),
                "description": a.description,
            }
            for a in accounts
        ], indent=2))
        return 0
    has_foreign = any(a.currency for a in accounts)
    headers = ["Account", "Type", "Flags", "Balance"]
    if has_foreign:
        headers.append("Foreign")
    table = Table(headers=headers, align="lllrr")
    for a in accounts:
        flags = ",".join(
            f for f in ("cash" if a.is_cash else "",
                        "closed" if a.closed else "",
                        a.cf_category or "") if f
        )
        cells = [a.name, a.type.value, flags,
                 money(raw.get(a.id, 0) * a.type.natural_sign, led.decimals)]
        if has_foreign:
            cells.append(
                format_amount(foreign.get(a.id, 0) * a.type.natural_sign,
                              currency_decimals(a.currency),
                              currency_symbol(a.currency))
                if a.currency else "")
        table.add(*cells)
    print(table.render())
    return 0


def cmd_account_close(args) -> int:
    led = _open(args)
    account = led.find_account(args.name)
    led.close_account(account)
    print(f"Closed account {account.name}")
    return 0


def cmd_account_modify(args) -> int:
    led = _open(args)
    account = led.find_account(args.name)
    fields = {}
    if args.rename:
        fields["name"] = args.rename
    if args.cash is not None:
        if args.cash and account.type is not AccountType.ASSET:
            raise BeansError("only asset accounts can be marked as cash")
        fields["is_cash"] = args.cash
    if args.cashflow:
        fields["cf_category"] = args.cashflow
    if args.desc is not None:
        fields["description"] = args.desc
    if not fields:
        raise BeansError("nothing to modify (see `beans account modify -h`)")
    led.update_account(account, **fields)
    print(f"Updated account {fields.get('name', account.name)}")
    return 0


def _parse_postings(led: Ledger, specs: list[list[str]]) -> list[Posting]:
    """Turn --post [ACCOUNT, AMOUNT?, FOREIGN?] specs into balanced
    postings; one spec may omit its amount to become the balancing leg.
    The third element gives the foreign amount for postings on
    foreign-denominated accounts (otherwise derived from the rate)."""
    postings: list[Posting] = []
    balancing: Posting | None = None
    total = 0
    for spec in specs:
        if len(spec) > 3:
            raise BeansError(
                f"--post takes an account, an optional amount, and an "
                f"optional foreign amount, got: {' '.join(spec)} "
                "(quote account names with spaces)"
            )
        account = led.find_account(spec[0])
        if len(spec) == 1:
            if balancing is not None:
                raise BeansError(
                    "only one posting may omit its amount (the balancing leg)"
                )
            balancing = Posting(account_id=account.id, amount=0,
                                account_name=account.name)
            postings.append(balancing)
            continue
        amount = parse_amount(spec[1], led.decimals)
        foreign = None
        if len(spec) == 3:
            if not account.currency:
                raise BeansError(
                    f"{account.name} is a base-currency account — a "
                    "foreign amount does not apply"
                )
            # The foreign amount always moves with the base amount.
            foreign = abs(parse_amount(
                spec[2], currency_decimals(account.currency)))
            foreign = foreign if amount >= 0 else -foreign
        total += amount
        postings.append(Posting(account_id=account.id, amount=amount,
                                account_name=account.name,
                                foreign_amount=foreign))
    if balancing is not None:
        balancing.amount = -total
    return postings


def cmd_tx_add(args) -> int:
    led = _open(args)
    when = parse_date(args.date, default=date.today())
    if args.like is not None:
        template = led.get_transaction(args.like)
        postings = [Posting(account_id=p.account_id, amount=p.amount,
                            account_name=p.account_name)
                    for p in template.postings]
        if args.post:
            raise BeansError("--like and --post are mutually exclusive")
        desc = args.desc or template.description
        payee = args.payee or template.payee
        tags = args.tag or template.tags
    else:
        if not args.post:
            raise BeansError("either --post or --like is required")
        if not args.desc:
            raise BeansError("--desc is required (unless using --like)")
        postings = _parse_postings(led, args.post)
        desc, payee, tags = args.desc, args.payee, args.tag
    txn = led.add_transaction(when, desc, postings, payee=payee, tags=tags)
    txn = led.get_transaction(txn.id)
    print(f"Recorded transaction #{txn.id}")
    _print_transaction(led, txn)
    return 0


def _simple_transaction(args, debit_q: str, credit_q: str,
                        desc: str) -> tuple:
    """Record a two-leg transaction; returns (debit account, date) for
    callers that follow up (e.g. budget feedback)."""
    led = _open(args)
    when = parse_date(args.date, default=date.today())
    amount = parse_amount(args.amount, led.decimals)
    if amount <= 0:
        raise BeansError("amount must be positive")
    debit = led.find_account(debit_q)
    credit = led.find_account(credit_q)
    postings = [Posting(account_id=debit.id, amount=amount),
                Posting(account_id=credit.id, amount=-amount)]
    foreign_text = getattr(args, "foreign", None)
    if foreign_text:
        targets = [(p, a) for p, a in zip(postings, (debit, credit))
                   if a.currency]
        if len(targets) != 1:
            raise BeansError(
                "--foreign needs exactly one leg on a foreign-currency "
                "account" if not targets else
                "--foreign is ambiguous: both accounts are "
                "foreign-denominated (use `beans tx add` with explicit "
                "foreign amounts)"
            )
        posting, account = targets[0]
        foreign = abs(parse_amount(foreign_text,
                                   currency_decimals(account.currency)))
        posting.foreign_amount = (foreign if posting.amount >= 0
                                  else -foreign)
    txn = led.add_transaction(
        when, desc, postings,
        payee=getattr(args, "payee", "") or "",
    )
    print(f"Recorded transaction #{txn.id}: {when.isoformat()}  {desc}  "
          f"{_fmt(led, amount)}")
    print(f"    {debit.name}  <-  {credit.name}")
    return debit, when


def _default_cash_account(args) -> str:
    led = _open(args)
    return led.get_meta("default_account", "Checking")


def _budget_feedback(led: Ledger, account, when: date) -> None:
    """After recording an expense, show where the month's budget stands."""
    monthly = budget.budget_accounts(led).get(account.id)
    if not monthly:
        return
    start, _end = month_bounds(when.year, when.month)
    actual = (led.flows(start, when).get(account.id, 0)
              * account.type.natural_sign)
    pct = 100 * actual / monthly
    text = (f"{account.leaf}: {pct:.0f}% of {when:%B} budget used "
            f"({_fmt(led, actual)} of {_fmt(led, monthly)}/month)")
    print(red(text) if pct > 100 else text)


def cmd_spend(args) -> int:
    source = args.source or _default_cash_account(args)
    desc = args.desc or f"Spending: {args.category}"
    debit, when = _simple_transaction(args, args.category, source, desc)
    _budget_feedback(_open(args), debit, when)
    return 0


def cmd_earn(args) -> int:
    target = args.target or _default_cash_account(args)
    desc = args.desc or f"Income: {args.source}"
    _simple_transaction(args, target, args.source, desc)
    return 0


def cmd_transfer(args) -> int:
    desc = args.desc or f"Transfer: {args.source} -> {args.target}"
    _simple_transaction(args, args.target, args.source, desc)
    return 0


def cmd_tx_list(args) -> int:
    led = _open(args)
    start, end, _label = _period(args, default="all")
    account = led.find_account(args.account) if args.account else None
    txns = led.transactions(start=start, end=end, account=account,
                            limit=args.limit, include_void=args.all)
    if args.json:
        print(json.dumps([_txn_to_dict(led, t) for t in txns], indent=2))
        return 0
    if not txns:
        print("(no transactions)")
        return 0
    for txn in txns:
        _print_transaction(led, txn)
    return 0


def cmd_tx_show(args) -> int:
    led = _open(args)
    txn = led.get_transaction(args.id)
    if args.json:
        print(json.dumps(_txn_to_dict(led, txn), indent=2))
    else:
        _print_transaction(led, txn)
    return 0


def cmd_tx_void(args) -> int:
    led = _open(args)
    txn = led.void_transaction(args.id)
    print(f"Voided transaction #{txn.id} ({txn.date.isoformat()} "
          f"{txn.description})")
    return 0


def cmd_register(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    start, end, _label = _period(args, default="all")
    data = reports.register(led, account, start, end)
    _emit(args, led, data, reports.render_register)
    return 0


def cmd_balances(args) -> int:
    led = _open(args)
    as_of = parse_date(args.date, default=date.today())
    data = reports.balances_report(led, as_of)
    _emit(args, led, data, reports.render_balances)
    return 0


def cmd_report_income(args) -> int:
    led = _open(args)
    start, end, label = _period(args)
    data = reports.income_statement(led, start, end, label,
                                    compare=args.compare)
    _emit(args, led, data, reports.render_income_statement)
    return 0


def cmd_report_balance(args) -> int:
    led = _open(args)
    as_of = parse_date(args.date, default=date.today())
    data = reports.balance_sheet(led, as_of)
    _emit(args, led, data, reports.render_balance_sheet)
    return 0


def cmd_report_cashflow(args) -> int:
    led = _open(args)
    start, end, label = _period(args)
    data = reports.cash_flow_statement(led, start, end, label)
    _emit(args, led, data, reports.render_cash_flow_statement)
    return 0


def cmd_report_trial(args) -> int:
    led = _open(args)
    as_of = parse_date(args.date, default=date.today())
    data = reports.trial_balance(led, as_of)
    _emit(args, led, data, reports.render_trial_balance)
    return 0


def cmd_recur_add(args) -> int:
    led = _open(args)
    start = parse_date(args.start, default=date.today())
    end = parse_date(args.end) if args.end else None
    postings = _parse_postings(led, args.post)
    rec = led.add_recurring(
        args.name, args.freq, start, postings, end=end,
        description=args.desc or "", payee=args.payee, tags=args.tag,
    )
    due = recurring.next_due(rec)
    print(f"Added recurring rule {rec.name!r} ({rec.frequency}, "
          f"first due {due.isoformat()})")
    print("Post due instances with `beans recur run`.")
    return 0


def cmd_recur_list(args) -> int:
    led = _open(args)
    data = recurring.list_rules(led, date.today())
    _emit(args, led, data, recurring.render_list)
    return 0


def cmd_recur_show(args) -> int:
    led = _open(args)
    rec = led.find_recurring(args.name)
    print(recurring.render_rule(rec, led.decimals))
    return 0


def cmd_recur_run(args) -> int:
    led = _open(args)
    as_of = parse_date(args.to_date, default=date.today())
    data = recurring.run_due(led, as_of, dry_run=args.dry_run)
    _emit(args, led, data, recurring.render_run)
    return 0


def cmd_recur_pause(args) -> int:
    led = _open(args)
    rec = led.find_recurring(args.name)
    led.set_recurring_active(rec, False)
    print(f"Paused recurring rule {rec.name!r}")
    return 0


def cmd_recur_resume(args) -> int:
    led = _open(args)
    rec = led.find_recurring(args.name)
    led.set_recurring_active(rec, True)
    print(f"Resumed recurring rule {rec.name!r}")
    return 0


def cmd_recur_remove(args) -> int:
    led = _open(args)
    rec = led.find_recurring(args.name)
    led.remove_recurring(rec)
    print(f"Removed recurring rule {rec.name!r} "
          f"(already-posted transactions are kept)")
    return 0


def cmd_networth(args) -> int:
    led = _open(args)
    if args.months < 1:
        raise BeansError("--months must be at least 1")
    data = reports.net_worth_trend(led, args.months)
    _emit(args, led, data, reports.render_net_worth_trend)
    return 0


def cmd_budget_set(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    amount = parse_amount(args.amount, led.decimals)
    led.set_budget(account, amount, args.period)
    print(f"Budget set: {account.name} = {_fmt(led, amount)} {args.period}")
    return 0


def cmd_budget_list(args) -> int:
    led = _open(args)
    budgets = led.budgets()
    if args.json:
        print(json.dumps([
            {"account": a.name, "amount": reports.to_major(amt, led.decimals),
             "period": period}
            for a, amt, period in budgets
        ], indent=2))
        return 0
    if not budgets:
        print("No budgets set. Add one with: "
              "beans budget set <account> <amount> --period monthly")
        return 0
    table = Table(headers=["Account", "Amount", "Period"], align="lrl")
    for account, amount, period in budgets:
        table.add(account.name, money(amount, led.decimals), period)
    print(table.render())
    return 0


def cmd_budget_remove(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    led.remove_budget(account)
    print(f"Removed budget for {account.name}")
    return 0


def cmd_budget_report(args) -> int:
    led = _open(args)
    start, end, label = _period(args, default="this-month")
    if start is None:
        raise BeansError("budget reports need a bounded period (not 'all')")
    data = budget.budget_report(led, start, end, label)
    _emit(args, led, data, budget.render_budget_report)
    return 0


def cmd_forecast(args) -> int:
    led = _open(args)
    if args.months < 1:
        raise BeansError("--months must be at least 1")
    if args.lookback < 1:
        raise BeansError("--lookback must be at least 1")
    data = forecast.forecast(led, months=args.months, method=args.method,
                             lookback=args.lookback,
                             use_budget=args.use_budget,
                             use_recurring=args.use_recurring)
    _emit(args, led, data, forecast.render_forecast)
    return 0


def cmd_analyze(args) -> int:
    led = _open(args)
    start, end, label = _period(args)
    data = analysis.analyze(led, start, end, label)
    _emit(args, led, data, analysis.render_analysis)
    return 0


def cmd_import(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    default_category = (led.find_account(args.category)
                        if args.category else None)
    result = import_csv(
        led, args.csvfile, account,
        default_category=default_category,
        date_col=args.date_col, desc_col=args.desc_col,
        amount_col=args.amount_col, category_col=args.category_col,
        dry_run=args.dry_run, dedupe=not args.no_dedupe,
    )
    rows, skipped = result["imported"], result["skipped"]
    verb = "Would import" if args.dry_run else "Imported"
    summary = f"{verb} {len(rows)} transaction(s) into {account.name}"
    if skipped:
        summary += (f" ({len(skipped)} duplicate(s) skipped; "
                    f"pass --no-dedupe to keep them)")
    print(summary)
    if args.dry_run:
        table = Table(headers=["Date", "Description", "Counter-account",
                               "Amount"], align="lllr")
        for row in rows:
            table.add(row["date"], row["description"][:40], row["counter"],
                      money(row["amount"], led.decimals))
        print(table.render())
    return 0


def cmd_config(args) -> int:
    led = _open(args)
    if args.action == "list":
        for key in ("currency", "decimals", "default_account", "created"):
            value = led.get_meta(key)
            if value is not None:
                print(f"{key} = {value}")
        return 0
    if args.action == "get":
        if not args.key:
            raise BeansError("usage: beans config get <key>")
        value = led.get_meta(args.key)
        if value is None:
            raise BeansError(f"no config key {args.key!r}")
        print(value)
        return 0
    # set
    if not args.key or args.value is None:
        raise BeansError("usage: beans config set <key> <value>")
    if args.key in ("currency", "decimals", "created"):
        raise BeansError(f"{args.key} is fixed at `beans init` time")
    led.set_meta(args.key, args.value)
    print(f"{args.key} = {args.value}")
    return 0


def cmd_status(args) -> int:
    led = _open(args)
    data = status.status_report(led)
    _emit(args, led, data, status.render_status)
    return 0


def cmd_undo(args) -> int:
    led = _open(args)
    txn = led.last_transaction()
    led.void_transaction(txn.id)
    print(f"Voided transaction #{txn.id}:")
    txn.void = True
    _print_transaction(led, txn)
    return 0


def cmd_search(args) -> int:
    led = _open(args)
    txns = led.search_transactions(args.query, limit=args.limit)
    if args.json:
        print(json.dumps([_txn_to_dict(led, t) for t in txns], indent=2))
        return 0
    if not txns:
        print(f"(no transactions match {args.query!r})")
        return 0
    for txn in txns:
        _print_transaction(led, txn)
    return 0


def cmd_clear(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    through = parse_date(args.through) if args.through else None
    count = led.set_cleared(account, txn_ids=args.ids or None,
                            through=through, cleared=not args.undo)
    verb = "Uncleared" if args.undo else "Cleared"
    print(f"{verb} {count} posting(s) on {account.name}")
    return 0


def cmd_reconcile(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    balance = parse_amount(args.balance, led.decimals)
    as_of = parse_date(args.date, default=date.today())
    data = reconcile.reconcile_report(led, account, balance, as_of)
    _emit(args, led, data, reconcile.render_reconcile)
    return 0


def cmd_period_close(args) -> int:
    led = _open(args)
    through = parse_date(args.date)
    led.close_books(through)
    print(f"Books closed through {through.isoformat()} — transactions on "
          "or before this date can no longer be added or voided.")
    return 0


def cmd_period_status(args) -> int:
    led = _open(args)
    closed = led.closed_through
    if closed:
        print(f"Books closed through {closed.isoformat()}")
    else:
        print("The books are open (no period close set).")
    return 0


def cmd_period_reopen(args) -> int:
    led = _open(args)
    led.reopen_books()
    print("Books reopened — all periods are editable again.")
    return 0


def cmd_rule_add(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    led.add_import_rule(args.pattern, account)
    print(f"Import rule added: descriptions containing {args.pattern!r} "
          f"-> {account.name}")
    return 0


def cmd_rule_list(args) -> int:
    led = _open(args)
    rules = led.import_rules()
    if args.json:
        print(json.dumps([
            {"id": rid, "pattern": pattern, "account": account.name}
            for rid, pattern, account in rules
        ], indent=2))
        return 0
    if not rules:
        print("No import rules. Add one with: "
              "beans rule add PATTERN ACCOUNT")
        return 0
    table = Table(headers=["Pattern", "Account"], align="ll")
    for _rid, pattern, account in rules:
        table.add(pattern, account.name)
    print(table.render())
    return 0


def cmd_rule_remove(args) -> int:
    led = _open(args)
    led.remove_import_rule(args.pattern)
    print(f"Removed import rule {args.pattern!r}")
    return 0


def cmd_goal_add(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    target = parse_amount(args.target, led.decimals) if args.target else 0
    if target == 0 and account.type is not AccountType.LIABILITY:
        raise BeansError(
            "savings goals need --target AMOUNT (omit it only for "
            "liability payoff goals)"
        )
    by = parse_date(args.by)
    led.add_goal(args.name, account, target, by)
    kind = "payoff" if account.type is AccountType.LIABILITY else "savings"
    print(f"Goal {args.name!r} added ({kind}, {account.name} "
          f"by {by.isoformat()})")
    return 0


def cmd_goal_list(args) -> int:
    led = _open(args)
    data = goals.goals_report(led)
    _emit(args, led, data, goals.render_goals)
    return 0


def cmd_goal_remove(args) -> int:
    led = _open(args)
    led.remove_goal(args.name)
    print(f"Removed goal {args.name!r}")
    return 0


def cmd_invest_buy(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    cash = led.find_account(args.source or _default_cash_account(args))
    when = parse_date(args.date, default=date.today())
    qty = invest.parse_quantity(args.quantity)
    price = parse_amount(args.price, led.decimals)
    result = invest.buy(led, args.symbol, qty, price, account, cash, when)
    print(f"Recorded transaction #{result['txn_id']}: bought "
          f"{args.quantity} {args.symbol.upper()} for "
          f"{_fmt(led, result['cost'])} ({account.name} <- {cash.name})")
    return 0


def cmd_invest_sell(args) -> int:
    led = _open(args)
    account = led.find_account(args.account)
    cash = led.find_account(args.target or _default_cash_account(args))
    when = parse_date(args.date, default=date.today())
    qty = invest.parse_quantity(args.quantity)
    price = parse_amount(args.price, led.decimals)
    result = invest.sell(led, args.symbol, qty, price, account, cash, when)
    gain = result["gain"]
    gain_text = (f"realized gain {_fmt(led, gain)}" if gain >= 0
                 else f"realized loss {_fmt(led, -gain)}")
    print(f"Recorded transaction #{result['txn_id']}: sold "
          f"{args.quantity} {args.symbol.upper()} for "
          f"{_fmt(led, result['proceeds'])} ({gain_text})")
    return 0


def cmd_invest_list(args) -> int:
    led = _open(args)
    data = invest.portfolio(led)
    _emit(args, led, data, invest.render_portfolio)
    return 0


def cmd_invest_mark(args) -> int:
    led = _open(args)
    when = parse_date(args.date, default=date.today())
    data = invest.mark_to_market(led, when, dry_run=args.dry_run)
    _emit(args, led, data, invest.render_mark)
    return 0


def cmd_price_set(args) -> int:
    led = _open(args)
    when = parse_date(args.date, default=date.today())
    price = parse_amount(args.price, led.decimals)
    led.set_price(args.symbol, when, price)
    print(f"{args.symbol.upper()} = {_fmt(led, price)} "
          f"as of {when.isoformat()}")
    return 0


def cmd_price_list(args) -> int:
    led = _open(args)
    rows = led.prices(symbol=args.symbol)
    if args.json:
        print(json.dumps([
            {"symbol": r["symbol"], "date": r["date"],
             "price": reports.to_major(r["price"], led.decimals)}
            for r in rows
        ], indent=2))
        return 0
    if not rows:
        print("No prices recorded. Add one with: "
              "beans price set SYMBOL PRICE")
        return 0
    table = Table(headers=["Symbol", "Date", "Price"], align="llr")
    for r in rows:
        table.add(r["symbol"], r["date"], money(r["price"], led.decimals))
    print(table.render())
    return 0


def cmd_currency_set(args) -> int:
    led = _open(args)
    rate = parse_fx_rate(args.rate)
    when = parse_date(args.date, default=date.today())
    led.set_fx_rate(args.code, when, rate)
    print(f"1 {args.code.upper()} = {rate} {led.currency} "
          f"as of {when.isoformat()}")
    return 0


def cmd_currency_list(args) -> int:
    led = _open(args)
    data = fx.currencies_report(led)
    if args.json:
        # Serialized by hand: foreign_balance is in the *foreign*
        # currency's minor units, so the generic base-decimals
        # conversion would mangle 0-decimal currencies like JPY.
        def major(minor, decimals):
            return (reports.to_major(minor, decimals)
                    if minor is not None else None)

        print(json.dumps({
            "report": data["report"],
            "as_of": data["as_of"].isoformat(),
            "base_currency": data["base_currency"],
            "rows": [
                {
                    "account": row["account"],
                    "currency": row["currency"],
                    "foreign_balance": major(
                        row["foreign_balance"],
                        currency_decimals(row["currency"])),
                    "book": major(row["book"], led.decimals),
                    "rate": row["rate"],
                    "rate_date": (row["rate_date"].isoformat()
                                  if row["rate_date"] else None),
                    "market": major(row["market"], led.decimals),
                    "unrealized": major(row["unrealized"], led.decimals),
                }
                for row in data["rows"]
            ],
        }, indent=2))
        return 0
    print(fx.render_currencies(data, led.decimals, _symbol(led)))
    return 0


def cmd_currency_rates(args) -> int:
    led = _open(args)
    rows = led.fx_rates(code=args.code)
    if args.json:
        print(json.dumps([
            {"currency": r["currency"], "date": r["date"], "rate": r["rate"]}
            for r in rows
        ], indent=2))
        return 0
    if not rows:
        print("No exchange rates recorded. Add one with: "
              "beans currency set EUR 1.0832")
        return 0
    table = Table(headers=["Currency", "Date",
                           f"Rate ({led.currency} per unit)"], align="llr")
    for r in rows:
        table.add(r["currency"], r["date"], r["rate"])
    print(table.render())
    return 0


def cmd_currency_revalue(args) -> int:
    led = _open(args)
    when = parse_date(args.date, default=date.today())
    data = fx.revalue(led, when, dry_run=args.dry_run)
    _emit(args, led, data, fx.render_revalue)
    return 0


def cmd_export(args) -> int:
    led = _open(args)
    if args.format == "json":
        content = json.dumps(export.export_json(led), indent=2) + "\n"
    else:
        content = export.export_csv(led)
    if args.output:
        path = Path(args.output).expanduser()
        path.write_text(content)
        print(f"Exported {args.format.upper()} to {path}")
    else:
        print(content, end="")
    return 0


def cmd_backup(args) -> int:
    led = _open(args)
    path = export.backup(led, args.dest)
    print(f"Backed up ledger to {path}")
    print(f"Restore by pointing beans at it: beans -f {path} status")
    return 0


def cmd_completions(args) -> int:
    parser = build_parser()
    command_map = {}
    for action in parser._subparsers._group_actions:
        for name, sub in action.choices.items():
            subs = []
            if sub._subparsers:
                for sub_action in sub._subparsers._group_actions:
                    subs = sorted(sub_action.choices.keys())
            command_map[name] = subs
    print(completions.generate(args.shell, command_map))
    return 0


# -- argument parsing --------------------------------------------------------


def _add_period_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--period", "-p", metavar="SPEC",
        help="ytd (default varies), all, this-month, last-month, "
             "this-quarter, last-quarter, this-year, last-year, "
             "YYYY, YYYY-MM, or YYYY-QN",
    )
    parser.add_argument("--from", dest="from_date", metavar="DATE",
                        help="period start (YYYY-MM-DD); overrides --period")
    parser.add_argument("--to", dest="to_date", metavar="DATE",
                        help="period end (YYYY-MM-DD); defaults to today")


def _add_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true",
                        help="output machine-readable JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="beans — double-entry accounting for personal finance",
        epilog="Run `beans <command> -h` for details on each command.",
    )
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--file", "-f", metavar="PATH",
        help="ledger file (default: $BEANS_LEDGER or ~/.beans/ledger.db)",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("init", help="create a new ledger")
    p.add_argument("--currency", default="USD",
                   help="ISO currency code (default: USD)")
    p.add_argument("--bare", action="store_true",
                   help="skip the starter chart of accounts")
    p.set_defaults(func=cmd_init)

    # account
    p_account = sub.add_parser("account", help="manage the chart of accounts")
    account_sub = p_account.add_subparsers(dest="subcommand",
                                           metavar="subcommand")
    p = account_sub.add_parser("add", help="add an account")
    p.add_argument("name", help="hierarchical name, e.g. Expenses:Pets")
    p.add_argument("--type", "-t", required=True,
                   choices=[t.value for t in AccountType])
    p.add_argument("--cash", action="store_true",
                   help="treat as cash/cash-equivalent (assets only)")
    p.add_argument("--cashflow", choices=["operating", "investing",
                                          "financing"],
                   help="override the cash-flow statement activity")
    p.add_argument("--currency", metavar="CODE",
                   help="denominate in a foreign currency (assets and "
                        "liabilities only), e.g. EUR")
    p.add_argument("--desc", default="", help="description")
    p.set_defaults(func=cmd_account_add)
    p = account_sub.add_parser("list", help="list accounts with balances")
    p.add_argument("--type", "-t",
                   choices=[t.value for t in AccountType])
    p.add_argument("--all", action="store_true", help="include closed")
    p.add_argument("--names", action="store_true",
                   help="print bare account names (for shell completion)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_account_list)
    p = account_sub.add_parser("close", help="close a zero-balance account")
    p.add_argument("name")
    p.set_defaults(func=cmd_account_close)
    p = account_sub.add_parser("modify", help="rename or re-flag an account")
    p.add_argument("name")
    p.add_argument("--rename", metavar="NEW_NAME")
    cash_group = p.add_mutually_exclusive_group()
    cash_group.add_argument("--cash", dest="cash", action="store_true",
                            default=None)
    cash_group.add_argument("--no-cash", dest="cash", action="store_false")
    p.add_argument("--cashflow", choices=["operating", "investing",
                                          "financing"])
    p.add_argument("--desc", default=None)
    p.set_defaults(func=cmd_account_modify)

    # tx
    p_tx = sub.add_parser("tx", help="record and inspect transactions")
    tx_sub = p_tx.add_subparsers(dest="subcommand", metavar="subcommand")
    p = tx_sub.add_parser(
        "add", help="record a transaction (any number of postings)",
        epilog="Example: beans tx add --desc Paycheck "
               "--post Assets:Checking 4000 --post Assets:Retirement 500 "
               "--post Income:Salary",
    )
    p.add_argument("--date", "-d", help="YYYY-MM-DD (default: today)")
    p.add_argument("--desc", "-m", help="description")
    p.add_argument("--payee", default="")
    p.add_argument("--tag", action="append", default=[],
                   help="tag (repeatable)")
    p.add_argument("--post", nargs="+", action="append",
                   metavar=("ACCOUNT [AMOUNT] [FOREIGN]", ""),
                   help="posting: account and amount; positive = debit, "
                        "negative = credit; omit the amount on one posting "
                        "to auto-balance; a third value gives the foreign "
                        "amount for foreign-currency accounts (repeatable)")
    p.add_argument("--like", type=int, metavar="ID",
                   help="clone postings/description from transaction ID "
                        "(override with --date/--desc/--payee)")
    p.set_defaults(func=cmd_tx_add)
    p = tx_sub.add_parser("list", help="list transactions")
    _add_period_args(p)
    p.add_argument("--account", "-a", help="only involving this account")
    p.add_argument("--limit", "-n", type=int, help="last N transactions")
    p.add_argument("--all", action="store_true", help="include voided")
    _add_json_arg(p)
    p.set_defaults(func=cmd_tx_list)
    p = tx_sub.add_parser("show", help="show one transaction")
    p.add_argument("id", type=int)
    _add_json_arg(p)
    p.set_defaults(func=cmd_tx_show)
    p = tx_sub.add_parser("void", help="void a transaction (keeps history)")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_tx_void)

    # shortcuts
    p = sub.add_parser("spend", help="record an expense")
    p.add_argument("amount")
    p.add_argument("category", help="expense account (fuzzy match)")
    p.add_argument("--from", dest="source", metavar="ACCOUNT",
                   help="paying account (default: config default_account "
                        "or Checking)")
    p.add_argument("--desc", "-m", help="description")
    p.add_argument("--payee")
    p.add_argument("--date", "-d")
    p.add_argument("--foreign", metavar="AMOUNT",
                   help="exact foreign amount when one leg is on a "
                        "foreign-currency account")
    p.set_defaults(func=cmd_spend)
    p = sub.add_parser("earn", help="record income")
    p.add_argument("amount")
    p.add_argument("source", help="income account (fuzzy match)")
    p.add_argument("--to", dest="target", metavar="ACCOUNT",
                   help="receiving account (default: config default_account "
                        "or Checking)")
    p.add_argument("--desc", "-m")
    p.add_argument("--date", "-d")
    p.add_argument("--foreign", metavar="AMOUNT",
                   help="exact foreign amount when one leg is on a "
                        "foreign-currency account")
    p.set_defaults(func=cmd_earn)
    p = sub.add_parser("transfer", help="move money between accounts")
    p.add_argument("amount")
    p.add_argument("source", metavar="from")
    p.add_argument("target", metavar="to")
    p.add_argument("--desc", "-m")
    p.add_argument("--date", "-d")
    p.add_argument("--foreign", metavar="AMOUNT",
                   help="exact foreign amount when one leg is on a "
                        "foreign-currency account (e.g. EUR received)")
    p.set_defaults(func=cmd_transfer)

    p = sub.add_parser("register",
                       help="account history with running balance")
    p.add_argument("account")
    _add_period_args(p)
    _add_json_arg(p)
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("balances", help="all account balances by type")
    p.add_argument("--date", "-d", help="as-of date (default: today)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_balances)

    # report
    p_report = sub.add_parser("report", help="financial statements")
    report_sub = p_report.add_subparsers(dest="subcommand",
                                         metavar="subcommand")
    p = report_sub.add_parser("income", aliases=["is"],
                              help="income statement")
    _add_period_args(p)
    p.add_argument("--compare", action="store_true",
                   help="compare against the prior period")
    _add_json_arg(p)
    p.set_defaults(func=cmd_report_income)
    p = report_sub.add_parser("balance", aliases=["bs"],
                              help="balance sheet")
    p.add_argument("--date", "-d", help="as-of date (default: today)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_report_balance)
    p = report_sub.add_parser("cashflow", aliases=["cf"],
                              help="statement of cash flows")
    _add_period_args(p)
    _add_json_arg(p)
    p.set_defaults(func=cmd_report_cashflow)
    p = report_sub.add_parser("trial", aliases=["tb"], help="trial balance")
    p.add_argument("--date", "-d", help="as-of date (default: today)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_report_trial)

    # recur
    p_recur = sub.add_parser("recur",
                             help="recurring/scheduled transactions")
    recur_sub = p_recur.add_subparsers(dest="subcommand",
                                       metavar="subcommand")
    p = recur_sub.add_parser(
        "add", help="define a recurring rule",
        epilog="Example: beans recur add rent --freq monthly "
               "--start 2026-07-01 --post Expenses:Housing:Rent 1800 "
               "--post Assets:Checking",
    )
    p.add_argument("name", help="unique rule name, e.g. rent")
    p.add_argument("--freq", "-F", required=True,
                   choices=list(RECURRENCE_FREQUENCIES),
                   help="how often the transaction repeats")
    p.add_argument("--start", help="first occurrence (default: today)")
    p.add_argument("--end", help="last possible occurrence (optional)")
    p.add_argument("--desc", "-m", help="description (default: rule name)")
    p.add_argument("--payee", default="")
    p.add_argument("--tag", action="append", default=[],
                   help="tag (repeatable; instances also get 'recurring')")
    p.add_argument("--post", nargs="+", action="append", required=True,
                   metavar=("ACCOUNT [AMOUNT]", ""),
                   help="posting template, same syntax as `beans tx add`")
    p.set_defaults(func=cmd_recur_add)
    p = recur_sub.add_parser("list", help="list rules with due status")
    _add_json_arg(p)
    p.set_defaults(func=cmd_recur_list)
    p = recur_sub.add_parser("show", help="show one rule in detail")
    p.add_argument("name")
    p.set_defaults(func=cmd_recur_show)
    p = recur_sub.add_parser("run",
                             help="post all occurrences due through a date")
    p.add_argument("--to", dest="to_date", metavar="DATE",
                   help="post everything due through DATE (default: today)")
    p.add_argument("--dry-run", action="store_true",
                   help="preview without writing")
    _add_json_arg(p)
    p.set_defaults(func=cmd_recur_run)
    p = recur_sub.add_parser("pause", help="suspend a rule")
    p.add_argument("name")
    p.set_defaults(func=cmd_recur_pause)
    p = recur_sub.add_parser("resume", help="reactivate a paused rule")
    p.add_argument("name")
    p.set_defaults(func=cmd_recur_resume)
    p = recur_sub.add_parser("remove", help="delete a rule (keeps history)")
    p.add_argument("name")
    p.set_defaults(func=cmd_recur_remove)

    p = sub.add_parser("networth", help="month-end net worth trend")
    p.add_argument("--months", "-n", type=int, default=12,
                   help="months of history (default: 12)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_networth)

    # budget
    p_budget = sub.add_parser("budget", help="budgets and variance reports")
    budget_sub = p_budget.add_subparsers(dest="subcommand",
                                         metavar="subcommand")
    p = budget_sub.add_parser("set", help="set or update a budget")
    p.add_argument("account")
    p.add_argument("amount")
    p.add_argument("--period", default="monthly",
                   choices=["weekly", "monthly", "quarterly", "yearly"])
    p.set_defaults(func=cmd_budget_set)
    p = budget_sub.add_parser("list", help="list budgets")
    _add_json_arg(p)
    p.set_defaults(func=cmd_budget_list)
    p = budget_sub.add_parser("remove", help="remove a budget")
    p.add_argument("account")
    p.set_defaults(func=cmd_budget_remove)
    p = budget_sub.add_parser("report",
                              help="budget vs actual (default: this month)")
    _add_period_args(p)
    _add_json_arg(p)
    p.set_defaults(func=cmd_budget_report)

    p = sub.add_parser("forecast", help="project finances forward")
    p.add_argument("--months", "-n", type=int, default=6,
                   help="months to project (default: 6)")
    p.add_argument("--method", choices=["average", "trend"],
                   default="average")
    p.add_argument("--lookback", type=int, default=6,
                   help="months of history to learn from (default: 6)")
    p.add_argument("--use-budget", action="store_true",
                   help="use budgeted amounts where budgets exist")
    p.add_argument("--use-recurring", action="store_true",
                   help="project scheduled transactions at their exact "
                        "amounts and dates (takes priority over budgets "
                        "and history for those accounts)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_forecast)

    p = sub.add_parser("analyze",
                       help="financial ratios and expense breakdown")
    _add_period_args(p)
    _add_json_arg(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("import", help="import transactions from CSV")
    p.add_argument("csvfile")
    p.add_argument("--account", "-a", required=True,
                   help="target account (e.g. the bank account exported)")
    p.add_argument("--category",
                   help="fallback counter-account for uncategorized rows")
    p.add_argument("--date-col", default="date")
    p.add_argument("--desc-col", default="description")
    p.add_argument("--amount-col", default="amount",
                   help="signed amount column; positive = money in")
    p.add_argument("--category-col", default="category")
    p.add_argument("--dry-run", action="store_true",
                   help="parse and report without writing")
    p.add_argument("--no-dedupe", action="store_true",
                   help="import rows even if a matching transaction "
                        "(same date, account, amount) already exists")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("config", help="get or set ledger configuration")
    p.add_argument("action", choices=["get", "set", "list"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("status",
                       help="one-screen dashboard (default command)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("undo", help="void the most recent transaction")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("search",
                       help="full-text search of descriptions/payees/tags")
    p.add_argument("query")
    p.add_argument("--limit", "-n", type=int, help="last N matches")
    _add_json_arg(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("clear",
                       help="mark postings cleared against a statement")
    p.add_argument("account")
    p.add_argument("ids", nargs="*", type=int, metavar="ID",
                   help="transaction ids to clear")
    p.add_argument("--through", metavar="DATE",
                   help="clear everything dated on or before DATE")
    p.add_argument("--undo", action="store_true",
                   help="un-clear instead of clear")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("reconcile",
                       help="compare cleared balance to a bank statement")
    p.add_argument("account")
    p.add_argument("--balance", "-b", required=True,
                   help="the statement's ending balance")
    p.add_argument("--date", "-d", help="statement date (default: today)")
    _add_json_arg(p)
    p.set_defaults(func=cmd_reconcile)

    # period
    p_period = sub.add_parser("period",
                              help="close or reopen accounting periods")
    period_sub = p_period.add_subparsers(dest="subcommand",
                                         metavar="subcommand")
    p = period_sub.add_parser(
        "close", help="lock all transactions through a date")
    p.add_argument("date", help="close the books through this date")
    p.set_defaults(func=cmd_period_close)
    p = period_sub.add_parser("status", help="show the period-close state")
    p.set_defaults(func=cmd_period_status)
    p = period_sub.add_parser("reopen", help="remove the period lock")
    p.set_defaults(func=cmd_period_reopen)

    # rule
    p_rule = sub.add_parser("rule",
                            help="auto-categorization rules for import")
    rule_sub = p_rule.add_subparsers(dest="subcommand", metavar="subcommand")
    p = rule_sub.add_parser(
        "add", help="route imported rows to an account by description",
        epilog="Example: beans rule add 'WHOLE FOODS' Groceries",
    )
    p.add_argument("pattern",
                   help="case-insensitive text to match in descriptions")
    p.add_argument("account")
    p.set_defaults(func=cmd_rule_add)
    p = rule_sub.add_parser("list", help="list import rules")
    _add_json_arg(p)
    p.set_defaults(func=cmd_rule_list)
    p = rule_sub.add_parser("remove", help="remove an import rule")
    p.add_argument("pattern")
    p.set_defaults(func=cmd_rule_remove)

    # goal
    p_goal = sub.add_parser("goal",
                            help="savings goals and debt-payoff targets")
    goal_sub = p_goal.add_subparsers(dest="subcommand", metavar="subcommand")
    p = goal_sub.add_parser(
        "add", help="add a goal",
        epilog="Examples: beans goal add house --account Savings "
               "--target 20000 --by 2028-01-01 | beans goal add car-free "
               "--account Liabilities:Loans --by 2027-06-01",
    )
    p.add_argument("name")
    p.add_argument("--account", "-a", required=True,
                   help="asset to grow or liability to pay down")
    p.add_argument("--target",
                   help="target balance (omit for liability payoff = 0)")
    p.add_argument("--by", required=True, metavar="DATE",
                   help="target date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_goal_add)
    p = goal_sub.add_parser("list", help="show goal progress")
    _add_json_arg(p)
    p.set_defaults(func=cmd_goal_list)
    p = goal_sub.add_parser("remove", help="remove a goal")
    p.add_argument("name")
    p.set_defaults(func=cmd_goal_remove)

    # invest
    p_invest = sub.add_parser("invest",
                              help="investment lots, valuation, and "
                                   "mark-to-market")
    invest_sub = p_invest.add_subparsers(dest="subcommand",
                                         metavar="subcommand")
    p = invest_sub.add_parser("buy", help="buy a security into an account")
    p.add_argument("symbol")
    p.add_argument("quantity")
    p.add_argument("--price", "-p", required=True,
                   help="price paid per share/unit")
    p.add_argument("--account", "-a", required=True,
                   help="investment (asset) account holding the lot")
    p.add_argument("--from", dest="source", metavar="ACCOUNT",
                   help="paying cash account (default: config "
                        "default_account or Checking)")
    p.add_argument("--date", "-d")
    p.set_defaults(func=cmd_invest_buy)
    p = invest_sub.add_parser("sell",
                              help="sell FIFO, booking realized gain/loss")
    p.add_argument("symbol")
    p.add_argument("quantity")
    p.add_argument("--price", "-p", required=True)
    p.add_argument("--account", "-a", required=True)
    p.add_argument("--to", dest="target", metavar="ACCOUNT",
                   help="receiving cash account (default: config "
                        "default_account or Checking)")
    p.add_argument("--date", "-d")
    p.set_defaults(func=cmd_invest_sell)
    p = invest_sub.add_parser("list", help="holdings with market values")
    _add_json_arg(p)
    p.set_defaults(func=cmd_invest_list)
    p = invest_sub.add_parser(
        "mark", help="post adjustments so book value equals market value")
    p.add_argument("--date", "-d")
    p.add_argument("--dry-run", action="store_true")
    _add_json_arg(p)
    p.set_defaults(func=cmd_invest_mark)

    # price
    p_price = sub.add_parser("price", help="security price history")
    price_sub = p_price.add_subparsers(dest="subcommand",
                                       metavar="subcommand")
    p = price_sub.add_parser("set", help="record a price")
    p.add_argument("symbol")
    p.add_argument("price")
    p.add_argument("--date", "-d", help="default: today")
    p.set_defaults(func=cmd_price_set)
    p = price_sub.add_parser("list", help="list recorded prices")
    p.add_argument("symbol", nargs="?")
    _add_json_arg(p)
    p.set_defaults(func=cmd_price_list)

    # currency
    p_currency = sub.add_parser(
        "currency", help="exchange rates and FX revaluation")
    currency_sub = p_currency.add_subparsers(dest="subcommand",
                                             metavar="subcommand")
    p = currency_sub.add_parser(
        "set", help="record an exchange rate",
        epilog="Example: beans currency set EUR 1.0832 "
               "(base units per 1 EUR)",
    )
    p.add_argument("code", help="ISO currency code, e.g. EUR")
    p.add_argument("rate", help="base-currency units per one foreign unit")
    p.add_argument("--date", "-d", help="default: today")
    p.set_defaults(func=cmd_currency_set)
    p = currency_sub.add_parser(
        "list", help="foreign accounts with balances and unrealized FX")
    _add_json_arg(p)
    p.set_defaults(func=cmd_currency_list)
    p = currency_sub.add_parser("rates", help="recorded exchange rates")
    p.add_argument("code", nargs="?")
    _add_json_arg(p)
    p.set_defaults(func=cmd_currency_rates)
    p = currency_sub.add_parser(
        "revalue",
        help="post FX adjustments so book value matches the current rate")
    p.add_argument("--date", "-d")
    p.add_argument("--dry-run", action="store_true")
    _add_json_arg(p)
    p.set_defaults(func=cmd_currency_revalue)

    p = sub.add_parser("export", help="export the full ledger")
    p.add_argument("format", choices=["json", "csv"],
                   help="json: everything; csv: one row per posting")
    p.add_argument("--output", "-o", metavar="FILE",
                   help="write to a file instead of stdout")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("backup",
                       help="consistent point-in-time copy of the ledger")
    p.add_argument("dest", nargs="?",
                   help="file or directory (default: alongside the ledger, "
                        "timestamped)")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("completions",
                       help="print a shell completion script")
    p.add_argument("shell", choices=["bash", "zsh"])
    p.set_defaults(func=cmd_completions)

    return parser


# Commands after which a "recurring rules due" reminder would be noise.
NO_REMINDER_COMMANDS = {"init", "recur", "status", "completions", None}


def _due_reminder(args) -> None:
    """One-line nudge when recurring rules are due, after any command.

    Written to stderr so piped output stays clean; never allowed to
    break the command that just succeeded.
    """
    if getattr(args, "json", False):
        return
    if getattr(args, "command", None) in NO_REMINDER_COMMANDS:
        return
    led = getattr(args, "_ledger", None)
    if led is None:
        return
    try:
        due = recurring.due_names(led, date.today())
        if due:
            print(f"({len(due)} recurring rule(s) due — "
                  "run `beans recur run`)", file=sys.stderr)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        name = getattr(args, "command", None)
        if name is None:
            # Bare `beans`: show the dashboard when a ledger exists,
            # otherwise the help text.
            if ledger_path(args.file).exists():
                args.json = False
                args.func = cmd_status
                args.command = "status"
            else:
                parser.print_help()
                return 0
        else:
            # A group command (e.g. `beans tx`) without a subcommand.
            for action in parser._subparsers._group_actions:
                if name in action.choices:
                    action.choices[name].print_help()
                    return 2
            parser.print_help()
            return 2
    try:
        code = args.func(args)
        if code == 0:
            _due_reminder(args)
        return code
    except BeansError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
    finally:
        led = getattr(args, "_ledger", None)
        if led is not None:
            led.close()


if __name__ == "__main__":
    sys.exit(main())
