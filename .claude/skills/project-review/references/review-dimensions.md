# Review dimensions — detailed checklists per lens

These are prompts for your attention, not a form to fill out. Use them to make
sure you have looked at what matters, then report only what is actually present in
the code. An empty lens is a fine, honest outcome — say "nothing notable" and move
on rather than padding.

The five lenses map to the skill's framing: the first four produce ranked,
PR-ready backlog findings; the fifth (new features) is quarantined and held to a
higher bar.

## Table of contents
- [1. Robustness of design](#1-robustness-of-design)
- [2. Refactoring opportunities](#2-refactoring-opportunities)
- [3. Enhancements to existing features](#3-enhancements-to-existing-features)
- [4. Hidden bugs](#4-hidden-bugs)
- [5. Potential new features](#5-potential-new-features)
- [Language-specific gotchas](#language-specific-gotchas)

---

## 1. Robustness of design

The core question: will this system behave correctly under inputs, load, and
failure conditions it does not currently exercise — not just the happy path it was
built against?

- **Failure modes.** What happens when a dependency is down, a request times out,
  a disk is full, a queue backs up? Are failures contained, or do they cascade?
- **Error handling strategy.** Is there a coherent approach, or a mix of swallowed
  exceptions, bare catches, and inconsistent error propagation? Are errors
  actionable, or do they lose context as they bubble up?
- **Edge and boundary conditions.** Empty/single-element collections, null/None,
  zero, negative, very large values, off-by-one at boundaries, empty strings,
  unicode/multibyte, timezones/DST, leap years.
- **Concurrency.** Shared mutable state without synchronization, race conditions,
  non-atomic check-then-act, deadlock potential, async ordering assumptions,
  unawaited promises/futures, thread-unsafe use of shared clients.
- **Resource management.** Files, sockets, DB connections, locks, handles not
  released on every path (especially error paths). Connection pools sized and
  bounded. Context managers / `defer` / try-with-resources / `using` used.
- **Single points of failure.** A component whose failure takes down the system;
  missing ret/retry/backoff/circuit-breaking where it matters; no graceful
  degradation.
- **Data integrity.** Operations that should be atomic but aren't, missing
  rollback, partial writes, idempotency for retried operations.
- **Input trust boundaries.** Where does untrusted data enter, and is it validated
  there or assumed-clean deep inside the system?

## 2. Refactoring opportunities

Code is read far more than written; this lens is about the next engineer and the
long-term cost of the current shape.

- **Duplication.** Copy-pasted logic that should be shared; parallel structures
  that drift out of sync; the same constant or rule expressed in several places.
- **Dead code.** Commented-out blocks, unreachable branches, unused
  variables/imports/parameters, exports nobody consumes, feature flags long since
  decided.
- **Tangled abstractions.** God objects/modules, circular dependencies, leaky
  layering (a low-level module reaching up into a high-level one), business logic
  smeared across the UI/transport layer.
- **Over- and under-engineering.** Premature generality, needless indirection, a
  plugin system with one plugin — and the converse, a 300-line function or a
  module that does five unrelated things and should be split.
- **Naming.** Names that mislead, abbreviations only the author understands,
  inconsistent vocabulary for the same concept across the codebase.
- **Module boundaries.** Are responsibilities cleanly separated, or does changing
  one thing force edits in five files? Is the public surface of a module minimal
  and intentional?
- **Testability.** Hidden dependencies, hard-coded singletons, side effects in
  constructors, and other shapes that make code hard to test in isolation — often
  the root cause of thin test coverage.

## 3. Enhancements to existing features

Improvements to something that already exists — making it more correct,
performant, usable, or maintainable. Distinct from new features (which add
capability) and from bugs (which fix broken behavior).

- **Correctness hardening.** A feature that works for the common case but quietly
  mishandles a real sub-case (pagination past the first page, partial results,
  concurrent edits).
- **Performance.** N+1 queries, work repeated inside loops, missing batching or
  caching of expensive stable results, blocking I/O on hot paths, loading whole
  datasets into memory instead of streaming, missing indexes/pagination for query
  patterns the code really uses, algorithmic complexity that won't hold at real
  data sizes.
- **Usability/DX.** Confusing CLI flags or error messages, missing `--help`,
  defaults that surprise, an API that's easy to misuse.
- **Observability.** Missing logging/metrics/tracing around a critical path that
  would make production issues debuggable.
- **Maintainability of the feature.** Configuration hard-coded where it should be
  a parameter; a feature that can only be extended by editing its core.

## 4. Hidden bugs

Latent defects the code will hit under inputs or conditions it does not currently
exercise. **The bar here is verification, not suspicion** — confirm against real
call sites and data flow before reporting, and cite the line that triggers it.

- **Does behavior match intent?** Re-read what the feature claims to do (docstring,
  README, tests) and check the code actually does it. Subtle goal/behavior
  mismatches are among the most valuable catches.
- **Control flow.** Missing `break`/`return`, switch fallthrough, inverted
  conditions, `&&` vs `||`, early returns that skip cleanup.
- **Null/undefined safety.** Dereferencing something that can be null; optional
  chaining missing where a value can be absent; defaults that mask a real bug.
- **Type and contract mismatches.** Units/encoding (seconds vs ms, bytes vs
  chars), nullability assumptions, a function whose callers pass values its body
  doesn't actually handle.
- **State and ordering.** Assumptions about call order, initialization races,
  stale caches, mutation of shared/aliased data.
- **Off-by-one and boundary.** Slice/index arithmetic, inclusive vs exclusive
  ranges, loop termination.
- **Error-path bugs.** The defect that only shows up when something upstream
  fails — the catch block that references an unset variable, the cleanup that
  double-frees, the retry that duplicates a side effect.

For each suspected bug, do the confirmation work: open the definition, find the
callers (`grep`/`rg` for the symbol), and either confirm with a concrete trigger
or downgrade your confidence and say what would confirm it.

## 5. Potential new features

Net-new capability the project does not have. This is product speculation, so the
bar is high and the output is quarantined (see SKILL.md §5).

- **Ground every idea in observed evidence.** A TODO/FIXME pointing at it, a
  half-built abstraction that clearly anticipated it, a workaround repeated in
  several places that the feature would eliminate, a usage pattern in tests or
  scripts that implies a missing capability.
- **Reject the generic.** If the idea ("add SSO", "add a dashboard", "add dark
  mode") could be pasted into any project's review unchanged, it does not belong.
- **No backlog docs by default.** Feature ideas are not PR-ready; only create
  backlog files for them if the user explicitly asks.
- **Cap and rank low.** ~5 max, P2/P3. If the code gives you nothing concrete,
  leave this section nearly empty.

## Language-specific gotchas

Apply the ones relevant to the project's languages.

- **Python** — mutable default arguments; bare `except:`; `==` vs `is` for
  None/singletons; late-binding closures in loops; `yaml.load` vs `safe_load`;
  f-strings in SQL; blocking calls in async code; integer/float division.
- **JavaScript/TypeScript** — `==` vs `===`; missing `await` (floating promises);
  `any` defeating the type system; mutating props/state directly; `for...in` over
  arrays; unhandled promise rejections; `JSON.parse` without try/catch.
- **Go** — ignored `error` returns; `defer` in loops; loop variable capture in
  goroutines (pre-1.22); nil map writes; missing comma-ok idiom; data races on
  shared maps.
- **Java/Kotlin** — NPEs from unchecked nullability; resource leaks without
  try-with-resources; `equals`/`hashCode` contract; mutable shared state;
  swallowed `InterruptedException`.
- **SQL** — missing `WHERE` on `UPDATE`/`DELETE`; implicit type coercion; `NOT IN`
  with NULLs; missing transaction boundaries; non-sargable predicates.
- **Shell** — unquoted variables; missing `set -euo pipefail`; parsing `ls`;
  unvalidated input in command construction.
