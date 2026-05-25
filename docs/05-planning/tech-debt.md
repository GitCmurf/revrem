---
document_id: REVREM-LEDGER-004
type: LEDGER
title: Tech Debt Register
status: Draft
version: '0.1'
last_updated: '2026-05-25'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Register of code review and simplification findings that are intentionally deferred to larger refactors or planned phase transitions.
keywords:
- revrem
- tech-debt
- refactoring
- planning
- task-003
related_ids:
- REVREM-TASK-003
---

# Tech Debt

Issues identified during code review and simplification passes that were deferred because they require larger refactors, are tied to a planned phase transition, or are acceptable at current scale.

---

## TD-001 — `ctx: RunContext | None = None` threading through all phase functions

**Location:** `src/code_review_loop/cli.py` — 16 phase functions including `run_codex_review`, `run_remediation`, `run_triage`, `run_checks`, `run_commit`, `write_summary`, `emit_artifact_write_events`, and others.

**Problem:** Every phase function carries `ctx: RunContext | None = None` as a trailing parameter. Call sites that don't yet wire `ctx` silently degrade (the function emits no events, no type error). The `| None` default means there is no compile-time contract that `ctx` is always present.

**Planned fix (phase C3):** Once all call sites are wired, remove the `| None` defaults and make `ctx: RunContext` a required parameter in each function. The comment "dead once phase_* is always wired (C3)" already marks the intent.

**Best practice:** Optional seam parameters are acceptable during incremental migration, but the migration should be completed before the feature is considered stable. A required parameter with no default is self-documenting about the contract.

---

## TD-002 — `acc.iteration` is redundant state in `LoopAccumulator`

**Location:** `src/code_review_loop/cli.py:1975–1978` (`_run_loop`)

**Problem:** `LoopAccumulator` carries `iteration: int`, but this is always the same as the `for iteration in range(...)` loop variable. It is re-synced via `replace(acc, iteration=iteration, ...)` at the top of each loop body. Redundant state that must be kept in sync is a maintenance hazard.

**Fix:** Remove `iteration` from `LoopAccumulator`. Pass the loop variable directly wherever the iteration number is needed downstream (e.g. `decide(cfg, acc, event)` or logging). This requires tracing all uses of `acc.iteration` inside the loop body.

**Best practice:** Derived values should not be stored in state. If a value can be computed from other state (here: the loop index), it should be computed at the use site, not carried in a data structure.

**Status (2026-05-25):** RESOLVED in Wave C3c cleanup. `LoopAccumulator` no longer stores `iteration`; `decide()` accepts the loop iteration explicitly for the commit-hook retry-budget branch, and `_run_loop` passes the loop variable at commit decision sites.

---

## TD-003 — `_execute_stop` repeats the same tail pattern across four outcome branches

**Location:** `src/code_review_loop/cli.py:1770–1815` (`_execute_stop`)

**Problem:** Each of the four `isinstance` branches sets `final_status`, `stopped_reason`, optional fields, conditionally sets `excerpt`, calls `write_summary`, then either returns or raises. The three returning branches (`OutcomeClear`, `OutcomeFindings`, `OutcomeUnknown`) share an identical `write_summary` + `return summary` tail. Only `OutcomeFailed` diverges structurally (raises instead of returning).

**Fix:** Extract a shared helper for the common tail:
```python
def _apply_stop_common(state, outcome, excerpt, summary, config, clock, ctx):
    state.set_stopped_reason(outcome.reason)
    if outcome.check_failures: state.set_pending_check_failures(True)
    if excerpt: state.set_latest_review_excerpt(excerpt)
    write_summary(config, summary, clock=clock, ctx=ctx)
```
Each branch sets its `final_status` and any unique fields, then calls the helper. `OutcomeFailed` calls the helper then raises.

**Best practice:** When a sequence of steps is repeated with minor variation, extract the shared tail and call it from each branch. Copy-paste with minor variation is the dominant source of bugs where one branch gets fixed but the others don't.

**Status (2026-05-25):** RESOLVED in Wave C3c cleanup. `_execute_stop()` now applies the repeated `stopped_reason`, optional check-failure flag, optional excerpt, and `write_summary()` steps through one shared tail helper.

---

## TD-004 — Routing-payload assembly is inlined in `_run_loop` (RESOLVED 2026-05-24)

**Location (historical):** `src/code_review_loop/cli.py:2129–2265` (triage resolution block inside `_run_loop`)

**Resolution:** Extracted to `_build_routing_payload(resolved_route, triage_payload, run_id, iteration, remediation_input, config)` in `src/code_review_loop/cli/__init__.py` during REVREM-TASK-003 Wave C2b. The `_run_loop` call site is now a single ~8-line call; the function is independently unit-testable and pure with respect to loop state. Golden-master and artifact-schema suites unchanged.

**Best practice:** Loop bodies should describe control flow, not compute artifacts. Any block of code that builds a data structure from inputs should be a named function.

---

## TD-005 — `OutcomeFailed.reason` is stringly-typed; `outcome_to_exit_code` dispatches on raw strings

**Location:** `src/code_review_loop/core/outcome.py:55–80`

**Problem:** `outcome_to_exit_code` dispatches on `outcome.reason` string literals (`"budget_ceiling_hit"`, `"setup_failed"`, `"cancelled"`) to produce exit codes 3, 4, 5. The `reason` field is typed as `str` with no constraint. A typo or new `reason` value silently falls through to exit code 1 with no type error.

**Fix:** Type `OutcomeFailed.reason` as `Literal["budget_ceiling_hit", "setup_failed", "cancelled", "loop_exhausted", ...]` (enumerate all valid values). Alternatively, use a `StrEnum`. `outcome_to_exit_code` then benefits from exhaustiveness checking if the match is structured appropriately.

**Best practice:** String fields used for control flow dispatch should be `Literal` types or enums. `str` typed fields are not checked at call sites — a rename or new value silently breaks dispatch.

**Status (2026-05-25):** RESOLVED in Wave C3c cleanup. `OutcomeFailed.reason` is now typed as an `OutcomeFailedReason` `Literal[...]` union covering all current failed stopped reasons.

---

## TD-006 — `harness_registry()` copies the registry dict on every call

**Location:** `src/code_review_loop/harnesses.py:335–339`

**Problem:** Every call to `harness_registry()` does `dict(HARNESS_REGISTRY)` unconditionally, even in production where the fake harness is never enabled and the result is always the same. The function is called once per phase command build (`_resolve_executable`, `validate_harness_name`, `require_implemented_harness`, `check_route_capabilities`) — O(N·D) times per iteration across the fallback-chain validation pass.

**Note:** The copy is load-bearing when the fake harness is enabled (tests mutate the returned dict to inject `"fake"`). Removing it requires changing the fake harness injection pattern first (e.g., injecting via a function argument rather than mutating the return value).

**Fix:** Once the fake harness injection pattern is revised, cache the production registry and only copy when `fake_harness_enabled()` is true.

**Best practice:** Functions that return a dict copy to protect against mutation should document the reason. If the mutation pattern is test-only, consider making the test inject the registry directly via a parameter rather than relying on a side-effecting copy.

---

## TD-007 — `triage.extract_routing_context` does blocking file I/O on the remediation hot path

**Location:** `src/code_review_loop/triage.py:173–228` (`extract_routing_context`)

**Problem:** `extract_routing_context` is called every iteration from `_run_loop`. It opens and reads up to 1 MB of each `affected_path` listed in the triage payload, then scans all content against 12 `SENSITIVE_SIGNALS` keys. With many affected files or large files, this is synchronous blocking I/O inside the main loop with no caching or deduplication across iterations.

**Note:** At typical repo sizes (< 20 affected files, < 100 KB each) this is not a practical problem. The concern is that future triage payloads from monorepo runs could make this slow without any visible bottleneck in the loop output.

**Fix (if needed):** Cache the results keyed by `(path, mtime)`, or limit the per-file read to the first N bytes if the signal patterns are typically found near the top of files.

**Best practice:** Document the expected performance contract in the function docstring (e.g., "expected < 20 files, < 100 KB each"). This makes the assumption explicit and flags future callers that change the expected scale.
