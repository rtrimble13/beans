"""The `beans` command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from beans import __version__
from beans import analysis, budget, forecast, reports
from beans.importer import import_csv
from beans.ledger import Ledger, ledger_path
from beans.models import AccountType, Posting
from beans.render import Table, bold, money
from beans.utils import (
    BeansError,
    currency_symbol,
    format_amount,
    parse_amount,
    parse_date,
    parse_period,
)

PROG = "beans"


# -- helpers -----------------------------------------------------------------


def _open(args, create: bool = False) -> Ledger:
    return Ledger(ledger_path(args.file), create=create)


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
    width = max(len(p.account_name) for p in txn.postings)
    for p in txn.postings:
        print(f"    {p.account_name:<{width}}  "
              f"{money(p.amount, led.decimals):>14}")


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
    led = Ledger(path, create=True)
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
    )
    notes = []
    if account.is_cash:
        notes.append("cash")
    notes.append(f"cash-flow: {account.cashflow}")
    print(f"Added {account.type.value} account "
          f"{account.name} ({', '.join(notes)})")
    return 0


def cmd_account_list(args) -> int:
    led = _open(args)
    type_ = AccountType(args.type) if args.type else None
    accounts = led.accounts(type_=type_, include_closed=args.all)
    raw = led.balances()
    if args.json:
        print(json.dumps([
            {
                "name": a.name, "type": a.type.value, "is_cash": a.is_cash,
                "cashflow": a.cashflow, "closed": a.closed,
                "balance": reports.to_major(
                    raw.get(a.id, 0) * a.type.natural_sign, led.decimals),
                "description": a.description,
            }
            for a in accounts
        ], indent=2))
        return 0
    table = Table(headers=["Account", "Type", "Flags", "Balance"],
                  align="lllr")
    for a in accounts:
        flags = ",".join(
            f for f in ("cash" if a.is_cash else "",
                        "closed" if a.closed else "",
                        a.cf_category or "") if f
        )
        table.add(a.name, a.type.value, flags,
                  money(raw.get(a.id, 0) * a.type.natural_sign, led.decimals))
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


def cmd_tx_add(args) -> int:
    led = _open(args)
    when = parse_date(args.date, default=date.today())
    postings: list[Posting] = []
    balancing: Posting | None = None
    total = 0
    for spec in args.post:
        if len(spec) > 2:
            raise BeansError(
                f"--post takes an account and an optional amount, got: "
                f"{' '.join(spec)} (quote account names with spaces)"
            )
        account = led.find_account(spec[0])
        if account.closed:
            raise BeansError(f"account {account.name} is closed")
        if len(spec) == 1:
            if balancing is not None:
                raise BeansError(
                    "only one posting may omit its amount (the balancing leg)"
                )
            balancing = Posting(account_id=account.id, amount=0,
                                account_name=account.name)
            postings.append(balancing)
        else:
            amount = parse_amount(spec[1], led.decimals)
            total += amount
            postings.append(Posting(account_id=account.id, amount=amount,
                                    account_name=account.name))
    if balancing is not None:
        balancing.amount = -total
    txn = led.add_transaction(when, args.desc, postings,
                              payee=args.payee, tags=args.tag)
    txn = led.get_transaction(txn.id)
    print(f"Recorded transaction #{txn.id}")
    _print_transaction(led, txn)
    return 0


def _simple_transaction(args, debit_q: str, credit_q: str,
                        desc: str) -> int:
    led = _open(args)
    when = parse_date(args.date, default=date.today())
    amount = parse_amount(args.amount, led.decimals)
    if amount <= 0:
        raise BeansError("amount must be positive")
    debit = led.find_account(debit_q)
    credit = led.find_account(credit_q)
    txn = led.add_transaction(
        when, desc,
        [Posting(account_id=debit.id, amount=amount),
         Posting(account_id=credit.id, amount=-amount)],
        payee=getattr(args, "payee", "") or "",
    )
    print(f"Recorded transaction #{txn.id}: {when.isoformat()}  {desc}  "
          f"{_fmt(led, amount)}")
    print(f"    {debit.name}  <-  {credit.name}")
    return 0


def _default_cash_account(args) -> str:
    led = _open(args)
    return led.get_meta("default_account", "Checking")


def cmd_spend(args) -> int:
    source = args.source or _default_cash_account(args)
    desc = args.desc or f"Spending: {args.category}"
    return _simple_transaction(args, args.category, source, desc)


def cmd_earn(args) -> int:
    target = args.target or _default_cash_account(args)
    desc = args.desc or f"Income: {args.source}"
    return _simple_transaction(args, target, args.source, desc)


def cmd_transfer(args) -> int:
    desc = args.desc or f"Transfer: {args.source} -> {args.target}"
    return _simple_transaction(args, args.target, args.source, desc)


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
                             use_budget=args.use_budget)
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
    rows = import_csv(
        led, args.csvfile, account,
        default_category=default_category,
        date_col=args.date_col, desc_col=args.desc_col,
        amount_col=args.amount_col, category_col=args.category_col,
        dry_run=args.dry_run,
    )
    verb = "Would import" if args.dry_run else "Imported"
    print(f"{verb} {len(rows)} transaction(s) into {account.name}")
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
    p.add_argument("--desc", default="", help="description")
    p.set_defaults(func=cmd_account_add)
    p = account_sub.add_parser("list", help="list accounts with balances")
    p.add_argument("--type", "-t",
                   choices=[t.value for t in AccountType])
    p.add_argument("--all", action="store_true", help="include closed")
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
    p.add_argument("--desc", "-m", required=True, help="description")
    p.add_argument("--payee", default="")
    p.add_argument("--tag", action="append", default=[],
                   help="tag (repeatable)")
    p.add_argument("--post", nargs="+", action="append", required=True,
                   metavar=("ACCOUNT [AMOUNT]", ""),
                   help="posting: account and amount; positive = debit, "
                        "negative = credit; omit the amount on one posting "
                        "to auto-balance (repeatable)")
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
    p.set_defaults(func=cmd_spend)
    p = sub.add_parser("earn", help="record income")
    p.add_argument("amount")
    p.add_argument("source", help="income account (fuzzy match)")
    p.add_argument("--to", dest="target", metavar="ACCOUNT",
                   help="receiving account (default: config default_account "
                        "or Checking)")
    p.add_argument("--desc", "-m")
    p.add_argument("--date", "-d")
    p.set_defaults(func=cmd_earn)
    p = sub.add_parser("transfer", help="move money between accounts")
    p.add_argument("amount")
    p.add_argument("source", metavar="from")
    p.add_argument("target", metavar="to")
    p.add_argument("--desc", "-m")
    p.add_argument("--date", "-d")
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
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("config", help="get or set ledger configuration")
    p.add_argument("action", choices=["get", "set", "list"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # A group command (e.g. `beans tx`) without a subcommand: show help.
        name = getattr(args, "command", None)
        for action in parser._subparsers._group_actions:
            if name and name in action.choices:
                action.choices[name].print_help()
                return 2
        parser.print_help()
        return 0 if name is None else 2
    try:
        return args.func(args)
    except BeansError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
