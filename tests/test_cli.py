import json

import pytest

from beans.cli import main


@pytest.fixture
def ledger_file(tmp_path):
    path = str(tmp_path / "ledger.db")
    assert main(["-f", path, "init"]) == 0
    return path


def run(capsys, ledger_file, *argv):
    code = main(["-f", ledger_file, *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_init_twice_fails(capsys, ledger_file):
    code, _, err = run(capsys, ledger_file, "init")
    assert code == 1
    assert "already initialized" in err


def test_missing_ledger_errors(capsys, tmp_path):
    code, _, err = run(capsys, str(tmp_path / "nope.db"), "balances")
    assert code == 1
    assert "beans init" in err


def test_full_workflow(capsys, ledger_file):
    code, out, _ = run(
        capsys, ledger_file, "tx", "add",
        "--date", "2026-01-01", "--desc", "Opening",
        "--post", "Assets:Checking", "5000",
        "--post", "Equity:Opening Balances",
    )
    assert code == 0
    assert "#1" in out

    code, out, _ = run(capsys, ledger_file, "earn", "6000", "Salary",
                       "--date", "2026-01-15")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "spend", "1800", "Rent",
                       "--date", "2026-02-01")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "transfer", "500",
                       "Checking", "Savings", "--date", "2026-02-02")
    assert code == 0

    code, out, _ = run(capsys, ledger_file, "report", "income",
                       "--period", "2026", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["total_income"] == "6000.00"
    assert data["net_income"] == "4200.00"

    code, out, _ = run(capsys, ledger_file, "report", "balance",
                       "--date", "2026-12-31", "--json")
    data = json.loads(out)
    assert data["balanced"] is True
    assert data["net_worth"] == "9200.00"

    code, out, _ = run(capsys, ledger_file, "report", "cashflow",
                       "--period", "2026", "--json")
    data = json.loads(out)
    assert data["net_change"] == data["cash_ending"]

    code, out, _ = run(capsys, ledger_file, "report", "trial")
    assert code == 0
    assert "Totals" in out


def test_balancing_posting(capsys, ledger_file):
    code, out, _ = run(
        capsys, ledger_file, "tx", "add", "--desc", "Paycheck",
        "--date", "2026-01-15",
        "--post", "Assets:Checking", "4000",
        "--post", "Assets:Investments:Retirement", "1000",
        "--post", "Income:Salary",
    )
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "tx", "show", "1", "--json")
    txn = json.loads(out)
    amounts = {p["account"]: p["amount"] for p in txn["postings"]}
    assert amounts["Income:Salary"] == "-5000.00"


def test_foreign_amount_tracks_negative_base_leg(capsys, ledger_file):
    # A foreign posting on a credit (negative) leg must carry a negative
    # foreign amount: _signed_foreign re-signs the magnitude to the base leg.
    run(capsys, ledger_file, "account", "add", "Assets:EUR Savings",
        "--type", "asset", "--currency", "EUR")
    run(capsys, ledger_file, "currency", "set", "EUR", "1.10",
        "--date", "2026-01-01")
    code, _, _ = run(capsys, ledger_file, "tx", "add", "--desc", "drawdown",
                     "--date", "2026-02-01",
                     "--post", "Assets:EUR Savings", "-1100", "1000",
                     "--post", "Assets:Checking", "1100")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "account", "list", "--json")
    eur = {a["name"]: a for a in json.loads(out)}["Assets:EUR Savings"]
    assert eur["foreign_balance"] == "-1000.00"


def test_two_balancing_postings_rejected(capsys, ledger_file):
    code, _, err = run(
        capsys, ledger_file, "tx", "add", "--desc", "bad",
        "--post", "Assets:Checking",
        "--post", "Income:Salary",
    )
    assert code == 1
    assert "balancing" in err


def test_no_write_path_posts_to_a_closed_account(capsys, ledger_file):
    # Record then reverse an Entertainment expense so it can be closed at a
    # zero balance, and capture a transaction id to clone via --like.
    code, out, _ = run(capsys, ledger_file, "tx", "add", "--desc", "movie",
                       "--date", "2026-01-01",
                       "--post", "Expenses:Entertainment", "20",
                       "--post", "Assets:Checking", "-20")
    assert code == 0
    like_id = out.split("#")[1].split()[0]
    code, _, _ = run(capsys, ledger_file, "tx", "add", "--desc", "refund",
                     "--date", "2026-01-02",
                     "--post", "Assets:Checking", "20",
                     "--post", "Expenses:Entertainment", "-20")
    assert code == 0
    code, _, _ = run(capsys, ledger_file, "account", "close",
                     "Expenses:Entertainment")
    assert code == 0

    # Every write path must reject the closed account with the same message.
    code, _, err = run(capsys, ledger_file, "spend", "5", "Entertainment")
    assert code == 1 and "Expenses:Entertainment is closed" in err

    code, _, err = run(capsys, ledger_file, "tx", "add", "--desc", "x",
                       "--post", "Expenses:Entertainment", "5",
                       "--post", "Assets:Checking", "-5")
    assert code == 1 and "Expenses:Entertainment is closed" in err

    code, _, err = run(capsys, ledger_file, "tx", "add", "--like", like_id,
                       "--date", "2026-03-01")
    assert code == 1 and "Expenses:Entertainment is closed" in err


def test_transfer_to_closed_account_rejected(capsys, ledger_file):
    code, _, _ = run(capsys, ledger_file, "account", "close", "Assets:Savings")
    assert code == 0
    code, _, err = run(capsys, ledger_file, "transfer", "100",
                       "Checking", "Savings")
    assert code == 1 and "Assets:Savings is closed" in err


def test_void_and_list(capsys, ledger_file):
    run(capsys, ledger_file, "earn", "100", "Salary", "--date", "2026-01-01")
    code, _, _ = run(capsys, ledger_file, "tx", "void", "1")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "tx", "list", "--json")
    assert json.loads(out) == []


def test_budget_cycle(capsys, ledger_file):
    code, _, _ = run(capsys, ledger_file, "budget", "set",
                     "Groceries", "500")
    assert code == 0
    run(capsys, ledger_file, "spend", "300", "Groceries",
        "--date", "2026-06-05")
    code, out, _ = run(capsys, ledger_file, "budget", "report",
                       "--period", "2026-06", "--json")
    assert code == 0
    data = json.loads(out)
    [row] = data["rows"]
    assert row["budget"] == "500.00"
    assert row["actual"] == "300.00"


def test_export_json_then_restore_round_trip(capsys, ledger_file, tmp_path):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "Opening", "--post", "Assets:Checking", "5000",
        "--post", "Equity:Opening Balances")
    run(capsys, ledger_file, "spend", "1800", "Rent", "--date", "2026-02-01")
    out_file = str(tmp_path / "ledger.json")
    code, _, _ = run(capsys, ledger_file, "export", "json", "-o", out_file)
    assert code == 0

    restored = str(tmp_path / "restored.db")
    code, out, _ = run(capsys, restored, "restore", out_file)
    assert code == 0
    assert "Restored ledger" in out

    # The restored ledger reports the same balance sheet.
    code, src, _ = run(capsys, ledger_file, "report", "balance",
                       "--date", "2026-12-31", "--json")
    code, dst, _ = run(capsys, restored, "report", "balance",
                       "--date", "2026-12-31", "--json")
    assert json.loads(dst)["net_worth"] == json.loads(src)["net_worth"]
    assert json.loads(dst)["balanced"] is True


def test_restore_into_existing_ledger_fails(capsys, ledger_file, tmp_path):
    out_file = str(tmp_path / "ledger.json")
    run(capsys, ledger_file, "export", "json", "-o", out_file)
    # ledger_file is already initialized -> restore must refuse.
    code, _, err = run(capsys, ledger_file, "restore", out_file)
    assert code == 1
    assert "already initialized" in err


def test_restore_failure_leaves_no_partial_ledger(capsys, tmp_path):
    # A malformed export must not leave a half-built ledger file behind when
    # restore created it fresh.
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a beans export"}')
    target = tmp_path / "fresh.db"
    code, _, err = run(capsys, str(target), "restore", str(bad))
    assert code == 1
    assert "not a beans export" in err
    assert not target.exists()


def test_forecast_runs(capsys, ledger_file):
    run(capsys, ledger_file, "budget", "set", "Groceries", "500")
    run(capsys, ledger_file, "budget", "set", "Salary", "4000")
    code, out, _ = run(capsys, ledger_file, "forecast", "--months", "2",
                       "--use-budget", "--json")
    assert code == 0
    data = json.loads(out)
    assert len(data["months"]) == 2
    assert data["months"][0]["net"] == "3500.00"


def test_account_management(capsys, ledger_file):
    code, out, _ = run(capsys, ledger_file, "account", "add",
                       "Expenses:Pets", "--type", "expense")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "account", "modify",
                       "Expenses:Pets", "--rename", "Expenses:Pet Care")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "account", "list", "--json")
    names = {a["name"] for a in json.loads(out)}
    assert "Expenses:Pet Care" in names
    assert "Expenses:Pets" not in names


def test_import_csv(capsys, ledger_file, tmp_path):
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text(
        "date,description,amount,category\n"
        "2026-03-01,Pay,1000.00,Salary\n"
        "2026-03-02,Food,-50.00,Groceries\n"
        "2026-03-03,Misc,-10.00,\n"
    )
    code, out, _ = run(capsys, ledger_file, "import", str(csv_file),
                       "--account", "Checking",
                       "--category", "Expenses:Other")
    assert code == 0
    assert "Imported 3" in out
    code, out, _ = run(capsys, ledger_file, "balances", "--json")
    data = json.loads(out)
    assert data["sections"]["asset"]["Assets:Checking"] == "940.00"


def test_analyze_runs(capsys, ledger_file):
    run(capsys, ledger_file, "earn", "1000", "Salary", "--date", "2026-01-05")
    run(capsys, ledger_file, "spend", "400", "Rent", "--date", "2026-01-06")
    code, out, _ = run(capsys, ledger_file, "analyze", "--period", "2026",
                       "--json")
    assert code == 0
    data = json.loads(out)
    assert data["savings_rate_pct"] == 60.0


def test_networth(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "Opening", "--post", "Assets:Checking", "5000",
        "--post", "Equity:Opening Balances")
    code, out, _ = run(capsys, ledger_file, "networth", "--months", "2",
                       "--json")
    assert code == 0
    data = json.loads(out)
    assert len(data["rows"]) == 2
    assert data["rows"][-1]["net_worth"] == "5000.00"


def test_config(capsys, ledger_file):
    code, _, _ = run(capsys, ledger_file, "config", "set",
                     "default_account", "Savings")
    assert code == 0
    run(capsys, ledger_file, "spend", "25", "Dining", "--date", "2026-01-01")
    code, out, _ = run(capsys, ledger_file, "register", "Savings", "--json")
    data = json.loads(out)
    assert data["rows"][0]["amount"] == "-25.00"


def test_recurring_cycle(capsys, ledger_file):
    code, out, _ = run(
        capsys, ledger_file, "recur", "add", "rent",
        "--freq", "monthly", "--start", "2026-01-01",
        "--post", "Expenses:Housing:Rent", "1800",
        "--post", "Assets:Checking",
    )
    assert code == 0
    assert "first due 2026-01-01" in out

    code, out, _ = run(capsys, ledger_file, "recur", "run",
                       "--to", "2026-03-15", "--dry-run")
    assert code == 0
    assert "Would post 3" in out

    code, out, _ = run(capsys, ledger_file, "recur", "run",
                       "--to", "2026-03-15", "--json")
    assert code == 0
    data = json.loads(out)
    assert len(data["posted"]) == 3
    assert data["posted"][0]["amount"] == "1800.00"

    code, out, _ = run(capsys, ledger_file, "recur", "list", "--json")
    [rule] = json.loads(out)["rules"]
    assert rule["posted_count"] == 3
    assert rule["next_due"] == "2026-04-01"

    code, out, _ = run(capsys, ledger_file, "recur", "show", "rent")
    assert code == 0
    assert "monthly" in out

    code, _, _ = run(capsys, ledger_file, "recur", "pause", "rent")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "recur", "run",
                       "--to", "2026-12-31")
    assert "Posted 0" in out
    code, _, _ = run(capsys, ledger_file, "recur", "resume", "rent")
    assert code == 0

    code, _, _ = run(capsys, ledger_file, "recur", "remove", "rent")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "recur", "list")
    assert "No recurring rules" in out
    # Posted history survives rule removal.
    code, out, _ = run(capsys, ledger_file, "report", "income",
                       "--period", "2026", "--json")
    assert json.loads(out)["total_expenses"] == "5400.00"


def test_report_income_all_compare_does_not_error(capsys, ledger_file):
    # Regression for #12: --period all + --compare used to hard-error with a
    # non-zero exit; it must now exit 0 and emit the degrade note.
    run(capsys, ledger_file, "earn", "6000", "Salary", "--date", "2026-01-15")
    code, out, _ = run(capsys, ledger_file, "report", "income",
                       "--period", "all", "--compare")
    assert code == 0
    assert "comparison unavailable" in out
    code, out, _ = run(capsys, ledger_file, "report", "income",
                       "--period", "all", "--compare", "--json")
    assert code == 0
    data = json.loads(out)
    assert "compare" not in data and "compare_note" in data


def test_undo(capsys, ledger_file):
    run(capsys, ledger_file, "earn", "100", "Salary", "--date", "2026-01-01")
    run(capsys, ledger_file, "earn", "200", "Salary", "--date", "2026-01-02")
    code, out, _ = run(capsys, ledger_file, "undo")
    assert code == 0
    assert "Voided transaction #2" in out
    code, out, _ = run(capsys, ledger_file, "tx", "list", "--json")
    assert [t["id"] for t in json.loads(out)] == [1]
    # Nothing left after undoing everything.
    run(capsys, ledger_file, "undo")
    code, _, err = run(capsys, ledger_file, "undo")
    assert code == 1
    assert "no transactions" in err


def test_search(capsys, ledger_file):
    run(capsys, ledger_file, "spend", "10", "Dining",
        "--date", "2026-01-01", "-m", "Pizza night", "--payee", "Luigi")
    run(capsys, ledger_file, "spend", "20", "Groceries",
        "--date", "2026-01-02")
    code, out, _ = run(capsys, ledger_file, "search", "pizza", "--json")
    assert code == 0
    [txn] = json.loads(out)
    assert txn["description"] == "Pizza night"
    code, out, _ = run(capsys, ledger_file, "search", "luigi", "--json")
    assert len(json.loads(out)) == 1
    code, out, _ = run(capsys, ledger_file, "search", "zzz")
    assert "no transactions match" in out


def test_tx_add_like(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-15",
        "--desc", "Paycheck", "--payee", "MegaCorp",
        "--post", "Assets:Checking", "4000", "--post", "Income:Salary")
    code, out, _ = run(capsys, ledger_file, "tx", "add",
                       "--like", "1", "--date", "2026-02-15")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "tx", "show", "2", "--json")
    txn = json.loads(out)
    assert txn["date"] == "2026-02-15"
    assert txn["description"] == "Paycheck"
    assert txn["payee"] == "MegaCorp"
    amounts = {p["account"]: p["amount"] for p in txn["postings"]}
    assert amounts["Income:Salary"] == "-4000.00"
    # --like and --post are mutually exclusive.
    code, _, err = run(capsys, ledger_file, "tx", "add", "--like", "1",
                       "--post", "Assets:Checking", "1")
    assert code == 1
    assert "mutually exclusive" in err


def test_budget_feedback_on_spend(capsys, ledger_file):
    run(capsys, ledger_file, "budget", "set", "Groceries", "500")
    code, out, _ = run(capsys, ledger_file, "spend", "450", "Groceries",
                       "--date", "today")
    assert code == 0
    assert "90% of" in out
    assert "budget used" in out


def test_due_reminder_on_stderr(capsys, ledger_file):
    run(capsys, ledger_file, "recur", "add", "rent", "--freq", "monthly",
        "--start", "2026-01-01", "--post", "Expenses:Housing:Rent", "1800",
        "--post", "Assets:Checking")
    code, _, err = run(capsys, ledger_file, "balances")
    assert code == 0
    assert "recurring rule(s) due" in err
    # JSON output stays clean.
    code, out, err = run(capsys, ledger_file, "balances", "--json")
    json.loads(out)
    assert "recurring" not in err


def test_clear_and_reconcile(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "Opening", "--post", "Assets:Checking", "1000",
        "--post", "Equity:Opening Balances")
    run(capsys, ledger_file, "spend", "300", "Rent", "--date", "2026-01-10")
    code, out, _ = run(capsys, ledger_file, "clear", "Checking",
                       "--through", "2026-01-05")
    assert code == 0
    assert "Cleared 1 posting(s)" in out
    code, out, _ = run(capsys, ledger_file, "reconcile", "Checking",
                       "--balance", "1000", "--json")
    data = json.loads(out)
    assert data["difference"] == "0.00"
    assert len(data["uncleared"]) == 1
    code, out, _ = run(capsys, ledger_file, "clear", "Checking", "2")
    code, out, _ = run(capsys, ledger_file, "reconcile", "Checking",
                       "--balance", "700", "--json")
    assert json.loads(out)["difference"] == "0.00"


def test_period_cli(capsys, ledger_file):
    run(capsys, ledger_file, "earn", "100", "Salary", "--date", "2026-01-01")
    code, out, _ = run(capsys, ledger_file, "period", "close", "2026-01-31")
    assert code == 0
    code, _, err = run(capsys, ledger_file, "spend", "10", "Dining",
                       "--date", "2026-01-15")
    assert code == 1
    assert "closed through" in err
    code, out, _ = run(capsys, ledger_file, "period", "status")
    assert "closed through 2026-01-31" in out
    code, _, _ = run(capsys, ledger_file, "period", "reopen")
    assert code == 0
    code, _, _ = run(capsys, ledger_file, "spend", "10", "Dining",
                     "--date", "2026-01-15")
    assert code == 0


def test_rule_cli_and_import(capsys, ledger_file, tmp_path):
    code, _, _ = run(capsys, ledger_file, "rule", "add", "WHOLE FOODS",
                     "Groceries")
    assert code == 0
    csv_file = tmp_path / "bank.csv"
    csv_file.write_text("date,description,amount\n"
                        "2026-03-01,WHOLE FOODS #1,-50.00\n")
    code, out, _ = run(capsys, ledger_file, "import", str(csv_file),
                       "--account", "Checking")
    assert code == 0
    assert "Imported 1" in out
    # Re-import: deduped.
    code, out, _ = run(capsys, ledger_file, "import", str(csv_file),
                       "--account", "Checking")
    assert "Imported 0" in out
    assert "1 duplicate(s) skipped" in out
    code, out, _ = run(capsys, ledger_file, "rule", "list", "--json")
    assert json.loads(out)[0]["pattern"] == "WHOLE FOODS"


def test_list_commands_json_via_jsonify_pipeline(capsys, ledger_file):
    # The list commands now serialize through reports.jsonify. Pin the
    # money-as-decimal-string conversion and the count-vs-money distinction
    # so the unified pipeline can't silently change the --json contract.
    run(capsys, ledger_file, "budget", "set", "Groceries", "600")
    run(capsys, ledger_file, "rule", "add", "WHOLE FOODS", "Groceries")
    run(capsys, ledger_file, "price", "set", "VTI", "280",
        "--date", "2026-01-01")
    run(capsys, ledger_file, "currency", "set", "EUR", "1.10",
        "--date", "2026-01-01")

    code, out, _ = run(capsys, ledger_file, "budget", "list", "--json")
    assert code == 0
    assert json.loads(out) == [{"account": "Expenses:Food:Groceries",
                                "amount": "600.00", "period": "monthly"}]

    code, out, _ = run(capsys, ledger_file, "price", "list", "--json")
    assert json.loads(out) == [{"symbol": "VTI", "date": "2026-01-01",
                                "price": "280.00"}]

    code, out, _ = run(capsys, ledger_file, "currency", "rates", "--json")
    assert json.loads(out) == [{"currency": "EUR", "date": "2026-01-01",
                                "rate": "1.10"}]

    # rule id is a count, not money — it must stay an int, not "1.00".
    code, out, _ = run(capsys, ledger_file, "rule", "list", "--json")
    assert json.loads(out)[0]["id"] == 1


def test_goal_cli(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "Opening", "--post", "Assets:Savings", "5000",
        "--post", "Equity:Opening Balances")
    code, out, _ = run(capsys, ledger_file, "goal", "add", "house",
                       "--account", "Savings", "--target", "20000",
                       "--by", "2030-01-01")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "goal", "list", "--json")
    [row] = json.loads(out)["rows"]
    assert row["progress_pct"] == 25.0
    code, _, _ = run(capsys, ledger_file, "goal", "remove", "house")
    assert code == 0


def test_invest_cli(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "Opening", "--post", "Assets:Checking", "10000",
        "--post", "Equity:Opening Balances")
    code, out, _ = run(capsys, ledger_file, "invest", "buy", "VTI", "10",
                       "--price", "280", "--account", "Brokerage",
                       "--date", "2026-02-01")
    assert code == 0
    code, _, _ = run(capsys, ledger_file, "price", "set", "VTI", "300",
                     "--date", "2026-03-01")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "invest", "list", "--json")
    [row] = json.loads(out)["rows"]
    assert row["unrealized"] == "200.00"
    code, out, _ = run(capsys, ledger_file, "invest", "mark",
                       "--date", "2026-03-15")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "invest", "sell", "VTI", "5",
                       "--price", "300", "--account", "Brokerage",
                       "--date", "2026-04-01")
    assert code == 0
    assert "realized gain" in out
    code, out, _ = run(capsys, ledger_file, "report", "balance",
                       "--date", "2026-04-30", "--json")
    assert json.loads(out)["balanced"] is True


def test_status_cli_and_bare_invocation(capsys, ledger_file):
    run(capsys, ledger_file, "earn", "1000", "Salary", "--date", "today")
    code, out, _ = run(capsys, ledger_file, "status")
    assert code == 0
    assert "BEANS STATUS" in out
    # Bare `beans` shows the dashboard once a ledger exists.
    code = main(["-f", ledger_file])
    out = capsys.readouterr().out
    assert code == 0
    assert "BEANS STATUS" in out


def test_bare_invocation_without_ledger(capsys, tmp_path):
    code = main(["-f", str(tmp_path / "none.db")])
    out = capsys.readouterr().out
    assert code == 0
    assert "usage:" in out


def test_completions(capsys, ledger_file):
    code, out, _ = run(capsys, ledger_file, "completions", "bash")
    assert code == 0
    assert "complete -F _beans beans" in out
    assert "reconcile" in out and "invest" in out
    code, out, _ = run(capsys, ledger_file, "completions", "zsh")
    assert code == 0
    assert "#compdef beans" in out


def test_account_list_names(capsys, ledger_file):
    capsys.readouterr()  # drain the fixture's init output
    code, out, _ = run(capsys, ledger_file, "account", "list", "--names")
    assert code == 0
    lines = out.strip().splitlines()
    assert "Assets:Checking" in lines
    assert all("  " not in line for line in lines)


def test_multicurrency_cli(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "Opening", "--post", "Assets:Checking", "10000",
        "--post", "Equity:Opening Balances")
    code, out, _ = run(capsys, ledger_file, "account", "add",
                       "Assets:EUR Savings", "--type", "asset",
                       "--currency", "eur")
    assert code == 0
    assert "denominated in EUR" in out
    code, _, _ = run(capsys, ledger_file, "currency", "set", "EUR",
                     "1.10", "--date", "2026-01-01")
    assert code == 0
    # Explicit foreign amount on a transfer.
    code, _, _ = run(capsys, ledger_file, "transfer", "1100",
                     "Checking", "EUR Savings", "--date", "2026-02-01",
                     "--foreign", "1000")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "account", "list", "--json")
    accounts = {a["name"]: a for a in json.loads(out)}
    eur = accounts["Assets:EUR Savings"]
    assert eur["currency"] == "EUR"
    assert eur["foreign_balance"] == "1000.00"
    assert eur["balance"] == "1100.00"
    # Rate moves; revalue books the unrealized FX gain.
    run(capsys, ledger_file, "currency", "set", "EUR", "1.25",
        "--date", "2026-03-01")
    code, out, _ = run(capsys, ledger_file, "currency", "list", "--json")
    [row] = json.loads(out)["rows"]
    assert row["unrealized"] == "150.00"
    code, out, _ = run(capsys, ledger_file, "currency", "revalue",
                       "--date", "2026-03-15", "--json")
    assert code == 0
    [adj] = json.loads(out)["adjustments"]
    assert adj["adjustment"] == "150.00"
    code, out, _ = run(capsys, ledger_file, "report", "balance",
                       "--date", "2026-03-31", "--json")
    assert json.loads(out)["balanced"] is True
    code, out, _ = run(capsys, ledger_file, "currency", "rates")
    assert "1.25" in out


def test_currency_list_json_foreign_decimals(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "Opening", "--post", "Assets:Checking", "1000",
        "--post", "Equity:Opening Balances")
    run(capsys, ledger_file, "account", "add", "Assets:Yen", "--type",
        "asset", "--currency", "JPY")
    run(capsys, ledger_file, "currency", "set", "JPY", "0.0067",
        "--date", "2026-01-01")
    code, _, _ = run(capsys, ledger_file, "transfer", "100",
                     "Checking", "Yen", "--date", "2026-02-01",
                     "--foreign", "14925")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "currency", "list", "--json")
    assert code == 0
    [row] = json.loads(out)["rows"]
    # JPY has no minor units: the foreign balance must not gain ".00".
    assert row["foreign_balance"] == "14925"
    assert row["book"] == "100.00"


def test_export_and_backup_cli(capsys, ledger_file, tmp_path):
    run(capsys, ledger_file, "earn", "1000", "Salary",
        "--date", "2026-01-05")
    code, out, _ = run(capsys, ledger_file, "export", "json")
    assert code == 0
    data = json.loads(out)
    assert data["format"] == "beans-export"
    assert len(data["transactions"]) == 1

    out_file = tmp_path / "dump.csv"
    code, out, _ = run(capsys, ledger_file, "export", "csv",
                       "--output", str(out_file))
    assert code == 0
    assert "Exported CSV" in out
    assert "Income:Salary" in out_file.read_text()

    code, out, _ = run(capsys, ledger_file, "backup", str(tmp_path))
    assert code == 0
    assert "Backed up ledger to" in out


def test_account_liquidity_flags(capsys, ledger_file):
    code, out, _ = run(capsys, ledger_file, "account", "add",
                       "Liabilities:Mortgage", "--type", "liability",
                       "--noncurrent")
    assert code == 0
    assert "noncurrent" in out
    code, out, _ = run(capsys, ledger_file, "account", "list", "--json")
    liq = {a["name"]: a["liquidity"] for a in json.loads(out)}
    assert liq["Liabilities:Mortgage"] == "noncurrent"
    assert liq["Assets:Checking"] == "current"
    # Reclassify back to current.
    code, _, _ = run(capsys, ledger_file, "account", "modify",
                     "Liabilities:Mortgage", "--current")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "account", "list", "--json")
    liq = {a["name"]: a["liquidity"] for a in json.loads(out)}
    assert liq["Liabilities:Mortgage"] == "current"
    # Non-current is rejected on income/expense accounts.
    code, _, err = run(capsys, ledger_file, "account", "modify",
                       "Salary", "--noncurrent")
    assert code == 1
    assert "asset and liability" in err


def test_loan_lifecycle(capsys, ledger_file):
    run(capsys, ledger_file, "tx", "add", "--date", "2026-01-01",
        "--desc", "draw", "--post", "Assets:Checking", "30000",
        "--post", "Liabilities:Loans", "-30000")
    code, out, _ = run(capsys, ledger_file, "loan", "add", "--account",
                       "Loans", "--principal", "30000", "--rate", "6.25",
                       "--term", "60", "--start", "2026-01-01")
    assert code == 0
    assert "583.48" in out  # derived payment
    code, out, _ = run(capsys, ledger_file, "loan", "list", "--date",
                       "2026-06-30", "--json")
    [row] = json.loads(out)["rows"]
    assert row["balance"] == "30000.00"
    # Current + non-current portions tie to the balance.
    assert (float(row["current_portion"]) + float(row["noncurrent_portion"])
            == 30000.0)
    assert 0 < float(row["current_portion"]) < 30000.0

    # Classified balance sheet splits the loan; --flat does not.
    code, out, _ = run(capsys, ledger_file, "report", "balance", "--date",
                       "2026-06-30", "--json")
    data = json.loads(out)
    assert "Liabilities:Loans" in data["liabilities_current"]
    assert "Liabilities:Loans" in data["liabilities_noncurrent"]

    code, out, _ = run(capsys, ledger_file, "report", "balance", "--date",
                       "2026-06-30", "--flat")
    assert "Current Liabilities" not in out

    # Pay one instalment: principal + interest split, books stay balanced.
    code, out, _ = run(capsys, ledger_file, "loan", "pay", "Loans",
                       "--date", "2026-02-01", "--from", "Checking")
    assert code == 0
    assert "156.25 interest" in out
    code, out, _ = run(capsys, ledger_file, "report", "trial", "--json")
    trial = json.loads(out)
    assert trial["total_debits"] == trial["total_credits"]

    code, out, _ = run(capsys, ledger_file, "loan", "remove", "Loans")
    assert code == 0
    code, out, _ = run(capsys, ledger_file, "loan", "list", "--json")
    assert json.loads(out)["rows"] == []


def test_loan_add_marks_noncurrent_only_when_long_term(capsys, ledger_file):
    def liq(name):
        _, out, _ = run(capsys, ledger_file, "account", "list", "--json")
        return {a["name"]: a["liquidity"] for a in json.loads(out)}[name]

    run(capsys, ledger_file, "account", "add", "Liabilities:Car",
        "--type", "liability")
    run(capsys, ledger_file, "account", "add", "Liabilities:Payday",
        "--type", "liability")

    # A >12-month loan is long-term: mark the account non-current and say so.
    _, out, _ = run(capsys, ledger_file, "loan", "add", "--account", "Car",
                    "--principal", "20000", "--rate", "5", "--term", "48",
                    "--start", "2026-01-01")
    assert "marked non-current" in out
    assert liq("Liabilities:Car") == "noncurrent"

    # A <=12-month loan is short-term: leave the account classification alone.
    _, out, _ = run(capsys, ledger_file, "loan", "add", "--account", "Payday",
                    "--principal", "1200", "--rate", "10", "--term", "6",
                    "--start", "2026-01-01")
    assert "marked non-current" not in out
    assert liq("Liabilities:Payday") == "current"


def test_loan_add_rejects_non_amortizing_payment(capsys, ledger_file):
    run(capsys, ledger_file, "account", "add", "Liabilities:BadLoan",
        "--type", "liability")
    # Payment below the first month's interest (20000 * 10%/12 = 166.67).
    code, _, err = run(capsys, ledger_file, "loan", "add", "--account",
                       "BadLoan", "--principal", "20000", "--rate", "10",
                       "--term", "60", "--payment", "150")
    assert code == 1
    assert "never amortize" in err


def test_group_command_shows_help(capsys, ledger_file):
    code = main(["-f", ledger_file, "tx"])
    out = capsys.readouterr().out
    assert code == 2
    assert "subcommand" in out
