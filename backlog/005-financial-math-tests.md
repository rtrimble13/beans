# 005 — Forecast `trend` and analysis ratios lack numeric tests

- **Lens:** Refactoring / Testability
- **Priority:** P2 (Impact: Medium · Effort: Medium)
- **Severity:** — (coverage gap, not a known defect)
- **Confidence:** Medium — read the math; verified no asserting tests exist

## Problem

The suite is strong (125 tests), but the two pieces of genuinely non-trivial
arithmetic are covered only by smoke tests that assert the command *runs*, not
that it produces correct numbers:

- **`forecast._project` least-squares `trend` branch** (`beans/forecast.py:27`)
  computes a slope and extrapolates it. The only forecast tests
  (`tests/test_status.py:42`, `:67`) exercise the recurring-projection path;
  `tests/test_cli.py:124 test_forecast_runs` just checks the command succeeds.
  No test pins the slope/intercept output for a known series, and the `trend`
  branch only activates with `len(history) >= 2` — a sign error or an
  off-by-one in `mean_y + slope * (n - 1 + step)` would ship green.
- **`analysis.analyze` ratios** (`beans/analysis.py:42`) — savings rate,
  liquidity runway, debt-to-assets, debt-to-annual-income — are exercised only
  by `tests/test_cli.py:166 test_analyze_runs`, which asserts the command runs.

## Impact

These outputs are advice a user acts on (how many months of runway, how fast net
worth is trending). A regression here is both plausible (floating-point and sign
conventions) and invisible to the current suite.

## Proposed fix

Add focused unit tests with hand-computed expected values:

- `test_project_trend_linear`: feed a perfectly linear series (e.g.
  `[100, 200, 300, 400]`) and assert the projected steps continue the line
  (`500, 600, …`), plus a flat series → constant, plus the `len < 2` fallback to
  `average`.
- `test_project_average`: mean of a known series.
- `test_analyze_ratios`: a tiny fixture ledger with known income/expenses/cash/
  assets/liabilities, asserting each ratio's exact value, including the
  `None`-when-denominator-zero branches (`income == 0`, `assets == 0`,
  `monthly_expenses is None`).

## Acceptance criteria

- `_project` has direct numeric assertions for both `trend` and `average` and
  the short-history fallback.
- `analyze` has at least one fixture asserting every ratio and its null path.

## Effort

Medium — pure unit tests, no production change; the hand-computed expected
values are the bulk of the work.
