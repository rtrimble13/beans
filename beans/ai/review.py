"""`beans ai review` — the conversational financial analyst.

Unlike `ask`, this is not an open-ended agent loop. It gathers a **fixed,
curated** set of read-only reports into one deterministic bundle and asks the
model for a structured narrative — more prompt-engineering than
orchestration. Because the bundle is deterministic, two runs on the same
ledger differ only in phrasing, never in which numbers are considered.
"""

from __future__ import annotations

import json
import sys

from beans.utils import BeansError

from . import prompts
from .runner import Runner


def _bundle_spec(period: str | None, compare: str | None,
                 focus: str | None) -> list[tuple[str, list[str]]]:
    """The ordered (label, argv) pairs gathered for a review."""
    per = ["--period", period] if period else []
    spec = [
        ("income_statement", ["report", "income", "--json", "--compare"]
         + per),
        ("balance_sheet", ["report", "balance", "--json"]),
        ("cash_flow", ["report", "cashflow", "--json"] + per),
        ("analysis", ["analyze", "--json"] + per),
        ("budget", ["budget", "report", "--json"] + per),
        ("net_worth", ["networth", "--json"]),
    ]
    if compare:
        spec.append(("income_statement_comparison",
                     ["report", "income", "--json", "--period", compare]))
    if focus == "economic":
        spec.append(("economic_balance_sheet",
                     ["economic", "bs", "--json"]))
    return spec


def assemble_bundle(led, *, period=None, compare=None,
                    focus=None, redact=False) -> dict:
    """Run the fixed report set in-process and collect their JSON. A report
    that legitimately can't run (e.g. no budgets set) is recorded with its
    error rather than aborting the review.

    ``redact`` mirrors the ai.redact preference so a review scrubs
    payee/description text before it is sent, exactly as ``ask`` does."""
    runner = Runner(led, redact=redact)
    statements: dict[str, object] = {}
    for label, argv in _bundle_spec(period, compare, focus):
        # argv[0]/[1] name the command; strip the leading tokens that the
        # tool name already implies by re-running through cli directly.
        result = runner._execute(label, argv)
        if result.ok:
            statements[label] = result.data
        else:
            statements[label] = {"unavailable": result.error}
    return {"period": _period_label(period, statements), "statements":
            statements}


def _period_label(period: str | None, statements: dict) -> str:
    if period:
        return period
    income = statements.get("income_statement")
    if isinstance(income, dict):
        for key in ("period", "label"):
            if isinstance(income.get(key), str):
                return income[key]
    return "current period"


def _collect_numbers(value, acc: set) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _collect_numbers(v, acc)
    elif isinstance(value, list):
        for v in value:
            _collect_numbers(v, acc)
    elif isinstance(value, (int, float)):
        acc.add(_norm_num(value))
    elif isinstance(value, str):
        acc.add(value.strip())


def _norm_num(value) -> str:
    """Normalize a number for membership testing (drop trailing zeros)."""
    try:
        from decimal import Decimal
        d = Decimal(str(value)).normalize()
        return format(d, "f")
    except Exception:
        return str(value)


def _fabrication_warnings(findings: dict, bundle: dict) -> list[str]:
    """Best-effort check that every from/to value in the structured findings
    appears somewhere in the bundle — a guard against invented figures."""
    numbers: set = set()
    _collect_numbers(bundle, numbers)
    normalized = {_norm_num(n) for n in numbers
                  if isinstance(n, (int, float)) or _is_num(n)}
    warnings = []
    for change in findings.get("changes", []):
        for side in ("from", "to"):
            val = change.get(side)
            if val is None:
                continue
            if _norm_num(val) not in normalized:
                warnings.append(
                    f"change {change.get('metric', '?')}.{side}={val} "
                    "was not found in the bundle")
    return warnings


def _is_num(text: str) -> bool:
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def dry_run(led, cfg, *, period=None, compare=None, focus=None,
            out=None) -> int:
    """Print the exact bundle that *would* be sent; send nothing."""
    from . import data_flow_line
    out = out or sys.stdout
    bundle = assemble_bundle(led, period=period, compare=compare, focus=focus,
                             redact=cfg.redact)
    print("── beans ai review — dry run (no request sent) ───────────────",
          file=out)
    print(data_flow_line(cfg), file=out)
    print("\nThe bundle that would be sent:\n", file=out)
    print(json.dumps(bundle, indent=2), file=out)
    print("\nNothing was sent. Re-run without --dry-run to review for real.",
          file=out)
    return 0


def run_review(led, *, client, cfg, period=None, compare=None, focus=None,
               brief=False, structured=False, out=None) -> int:
    """Assemble the bundle, ask the model, and print the narrative (prose) or
    validated findings (structured --json)."""
    out = out or sys.stdout
    bundle = assemble_bundle(led, period=period, compare=compare, focus=focus,
                             redact=cfg.redact)
    system = prompts.review_system(brief=brief, focus=focus,
                                   structured=structured)
    user = ("Here is the financial bundle to review as JSON:\n\n"
            + json.dumps(bundle, indent=2))
    resp = client.complete([{"role": "user", "content": user}],
                           tools=None, system=system)
    text = (resp.text or "").strip()

    if not structured:
        print(text, file=out)
        return 0

    findings = _parse_findings(text)
    if findings is None:
        raise BeansError("the model did not return valid JSON findings; "
                         "re-run without --json for a prose review")
    warnings = _fabrication_warnings(findings, bundle)
    for w in warnings:
        print(f"beans: warning: {w}", file=sys.stderr)
    print(json.dumps(findings, indent=2), file=out)
    return 0


def _parse_findings(text: str) -> dict | None:
    """Parse the model's JSON, tolerating an accidental code fence."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
    candidate = candidate.strip()
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            obj = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None
