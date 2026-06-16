# Severity rubric

Assign exactly one severity per finding. When torn between two levels, ask: "what
happens if this ships unfixed?" The answer usually picks the level. Consistency
matters more than precision — the author uses severity to triage, so don't inflate.

## Blocker — must fix before merge
The change is not safe to merge as-is. Typical cases:
- A security vulnerability (injection, auth bypass, secret exposure, SSRF).
- Data loss or corruption, or a non-atomic operation that can leave inconsistent
  state.
- A crash, hang, or unhandled error on a realistic input or path.
- Breaks existing behavior, a public API, or backward compatibility.
- The PR does not actually accomplish what it claims to do.

## High — should fix before merge
A real defect, just narrower in blast radius than a Blocker:
- A bug that triggers on a plausible edge case (empty input, concurrency, boundary).
- A significant performance regression (N+1 on a hot path, O(n²) on real-sized data).
- Missing tests for critical or risky new logic, or for the bug a fix PR addresses.
- A meaningful security weakness that requires unusual conditions to exploit.

## Medium — worth fixing
Won't necessarily block merge, but the author should seriously consider it:
- Maintainability problems that will bite later (confusing design, duplication,
  poor abstraction).
- Edge cases that are unlikely but possible.
- Error handling that's too broad or swallows useful information.
- Missing tests for non-critical paths.

## Low — minor improvement
Small, clearly optional improvements that make the code a bit better:
- Clearer naming, extracting a magic number, a simpler equivalent expression.
- Helpful comment or doc that's currently missing.

## Nit — style/taste, optional
Cosmetic preferences with no functional impact. Prefix the finding with "Nit:".
Keep these to a minimum and skip anything a linter/formatter would catch. Several
nits and zero real findings means: say the PR looks good.

---

## Mapping severity to a PR verdict
- Any **Blocker** or **High** → **Request changes**.
- Only **Medium/Low/Nit** → **Approve with comments**.
- Nothing beyond a couple of nits → **Approve**.

When posting to the PR, this maps to the GitHub review event: Request changes →
`REQUEST_CHANGES`, otherwise `COMMENT`. Reserve `APPROVE` for when the human
explicitly asks you to approve on their behalf.
