# Review dimensions — detailed checklists

These are prompts for your attention, not a form to fill out. Use them to make
sure you have looked at the things that matter, then report only what is actually
present in the code. An empty section is fine — say "nothing notable" and move on.

## Table of contents
- [Correctness & bugs](#correctness--bugs)
- [Security](#security)
- [Performance & scale](#performance--scale)
- [Maintainability & tests](#maintainability--tests)
- [Language-specific gotchas](#language-specific-gotchas)

---

## Correctness & bugs

The core question: will this behave correctly for all realistic inputs and states,
not just the one the author tested?

- **Does it match intent?** Re-read the PR description. Does the code actually
  accomplish what it claims? A subtle mismatch between stated goal and behavior is
  one of the most valuable things to catch.
- **Edge cases.** Empty collections, single-element collections, null/None/nil,
  zero, negative numbers, very large values, off-by-one at boundaries, empty
  strings, unicode and multibyte characters, duplicate keys, timezones and DST,
  leap years.
- **Error handling.** Are errors caught and handled, or swallowed silently? Are
  exceptions caught too broadly (hiding real failures)? On failure, is state left
  consistent, or partially mutated? Are error messages actionable?
- **Control flow.** Missing `break`/`return`, fallthrough in switch/case,
  inverted conditions, `&&` vs `||` mistakes, early returns that skip cleanup.
- **Null/undefined safety.** Dereferencing something that can be null. Optional
  chaining missing where a value can be absent. Default values that mask bugs.
- **Concurrency.** Shared mutable state without synchronization, race conditions,
  deadlock potential, non-atomic check-then-act, async ordering assumptions,
  unawaited promises/futures, thread-unsafe use of shared clients.
- **Resource management.** Files, sockets, DB connections, locks, and handles
  that may not be closed/released on every path (especially error paths). Context
  managers / `defer` / `try-with-resources` / `using` used where appropriate.
- **Data integrity.** Transactions that should be atomic but aren't, missing
  rollback, partial writes, idempotency for retried operations.
- **Type and contract correctness.** Signature changes that break callers, return
  type changes, nullability changes, units/encoding mismatches (seconds vs ms,
  bytes vs chars).
- **Backward compatibility.** Changed public APIs, serialized formats, DB schemas,
  config keys, or migration ordering that could break existing data or clients.

When you suspect a bug, **confirm it** by reading the definitions and call sites
involved, and cite the specific line that triggers it.

## Security

Treat any code touching user input, authentication, authorization, external
systems, file paths, or serialization as high-scrutiny. Search the whole changed
surface, not just obviously "security" files.

- **Injection.** SQL built by string concatenation/interpolation instead of
  parameterized queries; OS command construction from user input; XSS from
  unescaped output into HTML; template, LDAP, NoSQL, or header injection.
- **AuthN/AuthZ.** Missing permission checks on new endpoints/actions; checks that
  can be bypassed; privilege escalation; insecure direct object references (acting
  on an ID without verifying ownership); trusting client-supplied identity.
- **Secrets.** API keys, tokens, passwords, or private keys committed in code,
  config, tests, or fixtures. Secrets logged. Credentials in URLs.
- **Input validation.** Unvalidated/unsanitized input used in queries, paths,
  redirects, or deserialization. Missing length/range/format checks.
- **Path & SSRF.** Path traversal (`../`) from user-controlled filenames;
  server-side requests to user-controlled URLs without allowlisting.
- **Deserialization.** Untrusted data through unsafe deserializers (`pickle`,
  Java native serialization, `yaml.load` without SafeLoader, etc.).
- **Crypto.** Weak/obsolete algorithms (MD5/SHA1 for security, ECB mode), hardcoded
  IVs/salts, predictable randomness for tokens, disabled TLS verification.
- **Dependencies.** New or bumped dependencies — are they reputable, necessary,
  and pinned? Any known-vulnerable versions? Lockfile updated consistently?
- **Information disclosure.** Stack traces, internal paths, or PII in errors,
  logs, or responses.

## Performance & scale

Judge against the data sizes and request rates this code will realistically face,
not micro-optimizations that don't matter.

- **N+1 queries.** A query inside a loop over results of another query — the
  classic ORM trap. Look for DB or API calls inside iteration.
- **Algorithmic complexity.** Nested loops over large inputs, O(n²) where O(n)
  is easy, repeated linear scans that could be a set/map lookup.
- **Unnecessary work.** Recomputing invariants inside loops, redundant
  serialization, copying large structures, fetching more data than used.
- **I/O on hot paths.** Blocking/synchronous I/O where it stalls request handling;
  missing batching; missing caching of expensive, stable results.
- **Memory.** Loading entire large datasets/files into memory instead of
  streaming; unbounded caches/queues/collections that grow without limit; leaks
  from retained references or unremoved listeners.
- **Database.** Missing indexes for new query patterns; `SELECT *` pulling wide
  rows; missing pagination on endpoints that can return many rows; lock contention.

## Maintainability & tests

Code is read far more than written; this dimension is about the next engineer.

- **Clarity.** Would a teammate understand this without the PR context? Confusing
  names, magic numbers, deeply nested conditionals, overly clever one-liners.
- **Consistency.** Does it follow the conventions of *this* codebase (error
  handling style, logging, module layout, naming)? Compare to neighboring files.
- **Duplication & dead code.** Copy-pasted logic that should be shared; commented-
  out code; unreachable branches; unused variables/imports/parameters.
- **Abstraction fit.** Over-engineering (premature generality, needless layers)
  and under-engineering (a 200-line function that should be split) are both costs.
- **Docs & comments.** Public APIs documented; comments explain *why* not *what*;
  no stale comments contradicting the code.
- **Tests — the big one.** Do tests exist for the new behavior? Do they cover the
  edge cases above, or only the happy path? For a bugfix, is there a regression
  test that fails without the fix? Are tests deterministic (no time/order/network
  flakiness)? Are assertions meaningful, or do they just check "no exception"? Are
  mocks hiding real integration risk? Missing tests for critical logic is a High,
  not a Nit.

## Language-specific gotchas

Apply the ones relevant to the PR's languages.

- **Python** — mutable default arguments; bare `except:`; `==` vs `is` for
  None/singletons; late-binding closures in loops; `yaml.load` vs `safe_load`;
  f-strings in SQL; blocking calls in async code; integer/float division.
- **JavaScript/TypeScript** — `==` vs `===`; missing `await` (floating promises);
  `any` defeating the type system; mutating props/state directly; `for...in` over
  arrays; unhandled promise rejections; `JSON.parse` without try/catch.
- **Go** — ignored `error` returns; `defer` in loops; loop variable capture in
  goroutines (pre-1.22); nil map writes; not checking the comma-ok idiom; data
  races on shared maps.
- **Java/Kotlin** — NPEs from unchecked nullability; resource leaks without
  try-with-resources; `equals`/`hashCode` contract; mutable shared state;
  swallowed `InterruptedException`.
- **SQL** — missing `WHERE` on `UPDATE`/`DELETE`; implicit type coercion; `NOT IN`
  with NULLs; missing transaction boundaries; non-sargable predicates.
- **Shell** — unquoted variables; `set -euo pipefail` missing; parsing `ls`;
  unvalidated input in command construction.
