# The AI assistant

**What you'll accomplish:** turn on `beans`' optional AI assistant, point it at
a provider (hosted or fully local), and use it two ways — ask questions in
plain English (`beans ai ask`) and get a CFO-style narrative review of your
finances (`beans ai review`). Along the way you'll see the transparency
switches that keep it honest: `--dry-run` (see exactly what would be sent, send
nothing), `--explain` (see every command and figure behind an answer), and the
graceful notice you get when the feature isn't set up. The assistant never
computes money itself — it reads the same JSON that `beans <command> --json`
produces — so its numbers can't drift from your statements.

**Prerequisites:** comfort with [Getting started](01-getting-started.md) —
`init`, opening balances, `spend`/`earn`, and the three statements.

> The AI assistant is **opt-in and off by default.** It is the only part of
> `beans` that reaches the network. Everything else in the tool stays pure
> standard library and fully offline.

```sh
export BEANS_LEDGER=/tmp/ai-demo.db
```

## 1. A small ledger to reason about

```sh
beans init
beans tx add --date 2026-01-01 --desc 'Opening balances' \
  --post Assets:Checking 6000 \
  --post Assets:Savings 12000 \
  --post 'Liabilities:Credit Card' -900 \
  --post 'Equity:Opening Balances'
beans earn 6000 Salary --date 2026-01-15 --desc 'January paycheck'
beans spend 1800 Rent      --date 2026-01-02
beans spend 420  Dining    --date 2026-01-20
beans spend 380  Groceries --date 2026-01-22
beans budget set Expenses:Food:Dining 300 --period monthly
```

## 2. What happens before it's installed or configured

`beans ai` degrades cleanly. With no provider configured, the commands don't
error — they tell you how to turn the feature on and exit successfully, leaving
the rest of the tool untouched:

```sh
beans ai ask "how am I doing?"
```

```
beans ai needs the optional AI extra and a provider key.
  Install:   pip install "beans-ledger[ai]"
  Configure: set ANTHROPIC_API_KEY (or BEANS_AI_KEY) in your environment,
             or run `beans ai config set ai.base_url <url>` to
             point at a local model (e.g. Ollama). See
             `beans ai config` and `beans ai` for the details.
```

Install the extra (it adds **no** third-party dependency — the client uses the
standard library) and set a key:

```sh
pip install "beans-ledger[ai]"
export ANTHROPIC_API_KEY=sk-...        # or BEANS_AI_KEY, or an OpenAI key
```

You can also record non-secret preferences in the ledger so you don't repeat
flags. Settings live under a self-contained `ai.*` namespace:

```sh
beans ai config set ai.provider anthropic
beans ai config list
```

```
ai.provider = anthropic
```

## 3. See what would be sent — before sending anything

Financial data leaving your machine is a real change in the trust model, so
`beans ai` makes it inspectable. `--dry-run` shows precisely what a request
*would* contain and sends nothing to any provider. For `ask`, that's the
question and the read-only tools the agent could choose:

```sh
beans ai ask --dry-run "am I over budget on dining this month?"
```

```
── beans ai ask — dry run (no request sent) ──────────────────
Data flow: the JSON of the read-only beans commands the assistant runs is sent to anthropic (model claude-sonnet-5) over HTTPS.

Question:
  am I over budget on dining this month?

Tools the assistant could call (read-only):
  • get_income_statement — Income statement (revenue, expenses, net) with common-size percentages; pass compare=true to include the prior period.
  • get_balance_sheet — Classified balance sheet (assets, liabilities, equity) as of a date.
  • get_cashflow — Direct-method statement of cash flows for a period.
  • get_analysis — Financial ratios and analysis: savings rate, liquidity runway, current ratio, debt-to-assets, debt-to-income, and top expenses.
  • list_transactions — List transactions, optionally filtered by period, account, or count.
  ...
```

For `review`, `--dry-run` prints the exact bundle of report JSON that would be
sent — this is the whole payload, nothing more:

```sh
beans ai review --dry-run --period 2026-01
```

```
── beans ai review — dry run (no request sent) ───────────────
Data flow: the JSON of the read-only beans commands the assistant runs is sent to anthropic (model claude-sonnet-5) over HTTPS.

The bundle that would be sent:

{
  "period": "2026-01",
  "statements": {
    "income_statement": {
      "report": "income_statement",
      "period": "January 2026",
      "income": { "Income:Salary": "6000.00" },
      "expenses": {
        "Expenses:Food:Dining": "420.00",
        "Expenses:Food:Groceries": "380.00",
        "Expenses:Housing:Rent": "1800.00"
      },
      "total_income": "6000.00",
      "total_expenses": "2600.00",
      "net_income": "3400.00",
      ...
    },
    ...
  }
}
```

Only the **output of read-only reporting commands** is ever sent — never the
ledger file itself. If you'd rather scrub merchant/memo text too, turn on
redaction: `beans ai config set ai.redact true` replaces payee and description
strings with stable placeholders before anything is sent.

## 4. Ask a question

With a key set, drop the `--dry-run` and ask for real. The assistant plans,
runs whitelisted read-only commands in-process, reads their JSON, and answers.
(Model phrasing varies run to run; the *numbers* come straight from your
ledger.)

```sh
beans ai ask "am I over budget on dining this month?"
```

```
Yes — you're over your Dining budget for January. You've spent $420.00
against a $300.00 monthly budget, so you're $120.00 (40%) over. Groceries
($380.00) has no budget set, and your overall month is still comfortably
positive: $6,000.00 in, $2,600.00 out, $3,400.00 net.
```

Want to see the work? `--explain` prints every command the agent ran and the
JSON it read, so any figure is auditable:

```sh
beans ai ask --explain "am I over budget on dining this month?"
```

```
...the same answer...

── commands run ──────────────────────────────────────────────

$ beans budget report --json --period this-month
  {"ok": true, "result": { ... "Expenses:Food:Dining": {"budget": "300.00", "actual": "420.00", ...} ... }}
```

Run `beans ai ask` with no question for an interactive REPL that keeps context
across turns — ask a follow-up like "and how about groceries?" and it
remembers what you were talking about.

### Writes stay gated

By default `ask` is strictly read-only. If you ask it to *record* something, it
won't touch the ledger unless you pass `--allow-writes`, and even then it shows
the exact command and waits for your confirmation:

```sh
beans ai ask --allow-writes "record that I spent 15 on coffee today"
```

```
I'd run:  beans spend 15 Expenses:Food:Dining --desc "coffee"
Proceed? [y/N]
```

Answer `n` and nothing happens; the money math is always done by `beans`, never
by the model.

## 5. Run a review

`beans ai review` is different from `ask`: instead of an open-ended loop, it
gathers a fixed, deterministic bundle — income statement (with prior-period
comparison), balance sheet, cash flow, ratios, budget variance, and net-worth
trend — and asks for one structured briefing. Because the bundle is fixed, two
runs on the same ledger differ only in wording, never in which numbers matter.

```sh
beans ai review --period 2026-01
```

```
Headline: A strong month — you saved 57% of a $6,000 income and net worth
is climbing.

What changed: This is your first active month, so there's no prior period to
compare against yet; the $3,400 net income flows straight into net worth.

Concerns:
  • Dining is 40% over its $300 budget ($420 spent) — the one line running hot.
  • Groceries ($380) has no budget, so it's unmonitored.

Suggestions:
  • Either right-size the Dining budget to ~$425 or trim eating out next month.
  • Add a Groceries budget so the whole Food category is tracked.

Not licensed financial advice.
```

Two flags shape it: `--brief` gives a 3-bullet TL;DR, and `--focus economic`
adds a narration of your economic balance sheet (human capital, lifetime
consumption, economic vs accounting net worth).

For scripting, `--json` emits structured findings instead of prose — the same
machine-readable convention every `beans` report follows:

```sh
beans ai review --period 2026-01 --json | jq '.concerns'
```

```json
[
  {"severity": "medium", "area": "budget",
   "detail": "Dining $420 vs $300 budget (40% over)."},
  {"severity": "low", "area": "budget",
   "detail": "Groceries $380 has no budget set."}
]
```

## 6. Keep everything on your machine

If you'd prefer no financial data leave your computer at all, point the
assistant at any OpenAI-compatible local endpoint (Ollama, LM Studio, vLLM).
No hosted key is needed:

```sh
beans ai config set ai.provider openai
beans ai config set ai.base_url http://localhost:11434/v1
beans ai config set ai.model llama3.1
beans ai ask "what's my runway if I lost my job today?"
```

Now the data-flow line reads *"sent to your local model … (nothing leaves your
machine)"*, and everything else — the tools, the write-gating, `--explain`,
`--dry-run` — works exactly the same.

## Where to go next

- The [MANUAL's `ai` section](../MANUAL.md#ai--ai-assistant-optional) is the
  full reference: every flag, every `ai.*` config key, and the provider
  resolution order.
- Everything the assistant reads is a normal `beans` command — the other
  vignettes show those reports in depth, and `--explain` will point you at the
  exact ones behind any answer.

When you're done, just delete the scratch ledger file.
