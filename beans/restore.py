"""Restore a ledger from a `beans export json` document.

The inverse of `export.export_json`: rebuild every entity — accounts,
transactions (with void/cleared flags and foreign amounts), budgets,
recurring rules, goals, lots, prices, and FX rates — into a fresh, empty
ledger. This makes the JSON export round-trippable: load it back to move a
ledger between machines, restore from a text backup, or inspect/edit and
reload it.

Reconstruction goes through the normal ledger write methods, so every
transaction is re-validated to balance and the books still tie. Entities are
loaded in dependency order: FX rates before transactions (so any foreign
derivation has a rate), transactions before clears/voids, and account
closures plus the period-close lock last (so historical postings aren't
rejected on the way in).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from beans.ledger import Ledger
from beans.models import AccountType, Posting
from beans.utils import BeansError, currency_decimals, parse_amount, parse_date

EXPORT_FORMAT = "beans-export"

# Entity collections reported in the import summary, in load order.
SUMMARY_KEYS = ("accounts", "transactions", "budgets", "recurring", "goals",
                "loans", "import_rules", "lots", "prices", "fx_rates")


def restore_ledger(led: Ledger, data: dict) -> dict:
    """Rebuild `led` (which must be empty/uninitialized) from a beans-export
    document. Returns a count of entities restored per collection."""
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise BeansError(
            "not a beans export: expected a JSON document with "
            f'"format": "{EXPORT_FORMAT}" (from `beans export json`)'
        )
    if led.get_meta("currency"):
        raise BeansError(
            f"ledger at {led.path} is already initialized — restore into a "
            "fresh ledger path (-f / $BEANS_LEDGER) or an empty file"
        )

    meta = data.get("meta") or {}
    led.initialize(currency=meta.get("currency") or "USD", with_chart=False)
    # Preserve the exported precision and provenance verbatim, rather than
    # the currency-based defaults initialize() picks.
    if meta.get("decimals") is not None:
        led.set_meta("decimals", str(meta["decimals"]))
    if meta.get("created"):
        led.set_meta("created", meta["created"])
    if meta.get("default_account"):
        led.set_meta("default_account", meta["default_account"])
    decimals = led.decimals

    def money(text: str, code: str | None = None) -> int:
        return parse_amount(text, currency_decimals(code) if code else decimals)

    # -- accounts (created open; retired ones are closed at the very end) --
    closed_names: list[str] = []
    for a in data.get("accounts", []):
        type_ = AccountType(a["type"])
        cashflow = a.get("cashflow")
        # Reconstruct the explicit cash-flow override only when it differs
        # from the type's default, preserving the "uses default" state.
        cf_category = (cashflow
                       if cashflow and cashflow != type_.default_cashflow
                       else None)
        led.add_account(a["name"], type_, is_cash=a.get("is_cash", False),
                        cf_category=cf_category,
                        description=a.get("description", ""),
                        currency=a.get("currency"),
                        liquidity=a.get("liquidity", "current"))
        if a.get("closed"):
            closed_names.append(a["name"])
    by_name = {a.name: a for a in led.accounts(include_closed=True)}

    def account(name: str):
        acct = by_name.get(name)
        if acct is None:
            raise BeansError(f"export references unknown account {name!r}")
        return acct

    # -- FX rates first, so foreign-amount derivation always has a rate ----
    for r in data.get("fx_rates", []):
        try:
            rate = Decimal(str(r["rate"]))
        except InvalidOperation:
            raise BeansError(f"invalid exchange rate {r['rate']!r}")
        led.set_fx_rate(r["currency"], parse_date(r["date"]), rate)

    # -- transactions, in id order so the new ids line up with the export --
    cleared_by_account: dict[str, list[int]] = {}
    void_ids: list[int] = []
    txns = sorted(data.get("transactions", []), key=lambda t: t["id"])
    for t in txns:
        postings = []
        for p in t["postings"]:
            foreign = p.get("foreign_amount")
            postings.append(Posting(
                account_id=account(p["account"]).id,
                amount=money(p["amount"]),
                foreign_amount=(money(foreign, p.get("currency"))
                                if foreign is not None else None),
            ))
        txn = led.add_transaction(
            parse_date(t["date"]), t.get("description", ""), postings,
            payee=t.get("payee", "") or "", tags=t.get("tags") or [])
        # Cleared flags are restored after all txns exist; a void txn's
        # postings are never cleared (set_cleared ignores void txns anyway).
        if not t.get("void"):
            for p in t["postings"]:
                if p.get("cleared"):
                    cleared_by_account.setdefault(p["account"], []).append(
                        txn.id)
        else:
            void_ids.append(txn.id)

    for name, ids in cleared_by_account.items():
        led.set_cleared(account(name), txn_ids=ids)
    for txn_id in void_ids:
        led.void_transaction(txn_id)

    # -- budgets, rules, goals, lots, prices -------------------------------
    for b in data.get("budgets", []):
        led.set_budget(account(b["account"]), money(b["amount"]), b["period"])
    for r in data.get("import_rules", []):
        led.add_import_rule(r["pattern"], account(r["account"]))
    for g in data.get("goals", []):
        led.add_goal(g["name"], account(g["account"]),
                     money(g["target"]), parse_date(g["target_date"]))
    for lot in data.get("lots", []):
        led.add_lot(account(lot["account"]), lot["symbol"], lot["quantity"],
                    money(lot["cost"]), parse_date(lot["acquired"]))
    for pr in data.get("prices", []):
        led.set_price(pr["symbol"], parse_date(pr["date"]), money(pr["price"]))
    for ln in data.get("loans", []):
        led.add_loan(account(ln["account"]), money(ln["principal"]),
                     Decimal(str(ln["annual_rate"])), ln["term_months"],
                     money(ln["payment"]), parse_date(ln["start_date"]),
                     frequency=ln.get("frequency", "monthly"))

    # -- recurring rules (definition + occurrence counter + active state) --
    for rec in data.get("recurring", []):
        postings = [Posting(account_id=account(p["account"]).id,
                            amount=money(p["amount"]))
                    for p in rec["postings"]]
        created = led.add_recurring(
            rec["name"], rec["frequency"], parse_date(rec["start"]), postings,
            end=parse_date(rec["end"]) if rec.get("end") else None,
            description=rec.get("description", ""),
            payee=rec.get("payee", "") or "", tags=rec.get("tags") or [])
        if rec.get("occurrences"):
            with led.db:
                led.db.execute(
                    "UPDATE recurring SET occurrences = ? WHERE id = ?",
                    (rec["occurrences"], created.id))
        if not rec.get("active", True):
            led.set_recurring_active(created, False)

    # -- finalize: close retired accounts, then lock closed periods --------
    for name in closed_names:
        led.close_account(account(name))
    if meta.get("closed_through"):
        led.set_meta("closed_through", meta["closed_through"])

    return {key: len(data.get(key, [])) for key in SUMMARY_KEYS}
