"""Optional scrubbing of free-text fields before tool JSON is sent to a
provider.

When ``ai.redact`` is on, payee and description strings are replaced with a
stable placeholder (a short hash) so the shape and the numbers survive — the
model can still reason about amounts, accounts, and counts — while the raw
merchant/memo text never leaves the machine. Account *names* are structural
(the chart of accounts) and are left intact.
"""

from __future__ import annotations

import hashlib

# Keys whose string values carry free-form, potentially sensitive text.
_SENSITIVE_KEYS = {"payee", "description", "desc", "memo", "note"}


def _placeholder(text: str) -> str:
    if not text:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"[redacted:{digest}]"


def scrub(value):
    """Return a copy of ``value`` with sensitive free-text fields replaced."""
    if isinstance(value, dict):
        return {
            k: (_placeholder(v) if k in _SENSITIVE_KEYS and isinstance(v, str)
                else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value
