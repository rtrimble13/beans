#!/usr/bin/env bash
#
# Build the throwaway ledger used by the trend-briefing vignette
# (10-reporting-skill.md): thirteen months of history to 2026-09-04, with a
# raise, a grocery drift, a subscription that starts, an insurance payment
# that quietly lapses, and one large medical bill.
#
#   ./sample-trend-ledger.sh /tmp/trend-demo.db
#
set -euo pipefail
LEDGER="${1:-/tmp/trend-demo.db}"
export BEANS_LEDGER="$LEDGER"

rm -f "$LEDGER"
beans init >/dev/null
beans tx add --date 2025-08-01 --desc "Opening balances" \
    --post Assets:Checking 8000 \
    --post Assets:Savings 21000 \
    --post "Liabilities:Credit Card" -1900 \
    --post "Equity:Opening Balances" >/dev/null

# A standing instruction for the insurance payment — Phase 3 of the skill
# reconciles this against what actually happened.
beans recur add insurance --freq monthly --start 2025-09-05 \
    --post Expenses:Insurance 145 --post Assets:Checking >/dev/null

python3 - "$LEDGER" <<'PY'
import random
import subprocess
import sys

random.seed(11)
ledger = sys.argv[1]


def run(*args):
    subprocess.run(["beans", "-f", ledger, *args], check=True,
                   stdout=subprocess.DEVNULL)


months = [(2025, m) for m in range(9, 13)] + [(2026, m) for m in range(1, 9)]
for index, (year, month) in enumerate(months):
    stamp = f"{year}-{month:02d}"
    # A raise lands in March 2026.
    run("earn", "6000" if index < 6 else "6600", "Salary",
        "--date", f"{stamp}-15", "--desc", "Paycheck")
    run("spend", "1800", "Expenses:Housing:Rent", "--date", f"{stamp}-01")
    # Groceries creep by about $22 a month, under normal noise.
    run("spend", str(520 + 22 * index + random.randint(-18, 18)), "Groceries",
        "--date", f"{stamp}-08", "--payee", "Market")
    run("spend", str(200 + random.randint(-25, 25)), "Dining",
        "--date", f"{stamp}-13", "--payee", "Cafe")
    run("spend", str(180 + random.randint(-30, 30)), "Utilities",
        "--date", f"{stamp}-22")
    if index < 8:          # the insurance payment stops after April 2026
        run("spend", "145", "Expenses:Insurance", "--date", f"{stamp}-05",
            "--payee", "Insurer")
    if index >= 4:         # a streaming subscription starts in January 2026
        run("spend", "38", "Entertainment", "--date", f"{stamp}-19",
            "--payee", "Streaming")
    run("transfer", "700", "Checking", "Savings", "--date", f"{stamp}-26")

# One large one-off, big enough to drag an average but not a median.
run("spend", "2400", "Health", "--date", "2026-03-11", "--payee", "Clinic")
# September has begun: rent has posted, the paycheck has not. This is the trap.
run("spend", "1800", "Expenses:Housing:Rent", "--date", "2026-09-01")
PY

echo "Seeded $LEDGER — 13 months to 2026-09-04."
echo "Try:  beans -f $LEDGER report income --period 2026-08 --compare"
