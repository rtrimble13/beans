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


def test_two_balancing_postings_rejected(capsys, ledger_file):
    code, _, err = run(
        capsys, ledger_file, "tx", "add", "--desc", "bad",
        "--post", "Assets:Checking",
        "--post", "Income:Salary",
    )
    assert code == 1
    assert "balancing" in err


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


def test_group_command_shows_help(capsys, ledger_file):
    code = main(["-f", ledger_file, "tx"])
    out = capsys.readouterr().out
    assert code == 2
    assert "subcommand" in out
