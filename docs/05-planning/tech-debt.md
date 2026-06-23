---
document_id: REVREM-LEDGER-004
type: LEDGER
title: Tech Debt Register
status: Approved
version: '0.5'
last_updated: '2026-06-23'
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

## Current State

This register currently has two open items: TD-008 (partially mitigated) and
TD-009 (the headless-suppression module-global latch). Earlier debt items
TD-001 through TD-007 are resolved and retained as historical context.

---

## TD-008 — External review prompt truncation can make prompted reviews incomplete (OPEN)

**Location:** `src/code_review_loop/adapters/review.py`,
`src/code_review_loop/cli/config_builder.py`, prompted review harnesses such as
Gemini, Claude, OpenCode, and Kilo.

**Problem:** Non-Codex review harnesses do not have Codex's native
`codex review --base` command, so RevRem composes an explicit review prompt for
them. That prompt includes a generated read-only context bundle containing the
base branch, working directory, current `HEAD`, base commit, merge base,
`git status --short`, `git diff --stat <base>...HEAD`,
`git diff --name-status <base>...HEAD`, the full `git diff <base>...HEAD`,
`git diff --cached`, and `git diff`. RevRem writes the full generated context
and provider-facing prompt to artifacts so operators can inspect what was
available.

Before sending the prompt to a prompted provider, RevRem trims it by character
count using `runtime.external_review_input_chars` /
`--external-review-input-chars`. The conservative default is `80000`
characters. Gemini uses the same `80000` character default because its
headless CLI currently receives prompts through a single `--prompt` argument,
which must stay below operating-system per-argument limits. Progress output,
events, and `summary.external_review_coverage` report the sent prompt size,
generated context size, delivery mode, truncation policy, and whether the
prompt was truncated, for example
`prompt=80.0k/511.2k argv-prompt truncated`.

This bound is intentional. It avoids overflowing provider context windows,
keeps very large dogfood runs from becoming unbounded in latency or cost, and
does not require fragile provider-specific token accounting. For harnesses that
support stdin or prompt files, it also lets RevRem keep large prompts out of
argv/process listings; Gemini's current `--prompt` path instead relies on a
smaller byte guard to avoid operating-system argument limits. However, the
tradeoff is real: when the
provider receives only the first bounded slice of a large generated context,
its review can miss omitted files or late diff hunks. A `REVIEW_STATUS: clear`
from a prompted harness is therefore a clear result over the supplied prompt,
not necessarily over the full saved context when truncation occurred. Operators
can now set `external_review_truncation_policy = "fail"` or pass
`--external-review-truncation-policy fail` to stop before provider execution
when the generated review context would be truncated.

The dogfood evidence is mixed. OpenCode/minimax produced useful findings even
with an `80k` prompt cap on a `500k+` generated context, including the stale
git-context-cache bug. That success does not eliminate the risk: a different
patch could place the important regression outside the supplied prefix.
Gemini Pro likely has enough context for larger prompts, but CLI behaviour,
quota, latency, and non-API context limits still need provider-specific proof.

**Possible remediations:**

- Add harness/model capability metadata for safe review context size, and make
  the cap a first-class capability rather than a mostly global runtime setting.
- Use token-aware budgeting where providers expose reliable tokenizers, while
  retaining conservative character-count fallback for unknown CLIs.
- Replace prefix trimming with prioritized diff packing: file list and stats
  first, then high-risk modules, changed tests, failed-check context, and only
  then lower-signal hunks.
- Add a chunked or multi-pass prompted review mode that reviews the full diff
  in bounded sections and then asks for an aggregate status.
- Add harness/model capability metadata for the default truncation policy, so
  large-context models can opt into higher caps or fail-closed defaults with
  provider-specific evidence.
- Provide an operator shortcut to rerun the latest prompted review with a
  larger cap or a specific harness/model chosen for large context.

**Best practice:** Any bounded prompt sent to a reviewer should make its
coverage boundary visible. If the model did not receive the whole generated
review context, the run summary and operator output should preserve that fact
clearly enough that humans and automation can decide whether a follow-up review
is required.

---

## TD-009 — Headless ANSI suppression relies on a module-global latch (`_NO_TTY_FORCED`) (OPEN)

**Location:** `src/code_review_loop/progress.py` (`_NO_TTY_FORCED`,
`force_terminal`, `_console_and_text`, `rich_live_progress`, and the
`print_rich_event` / `print_rich_message` / `print_rich_continuation` helpers).

**Problem:** Whether RevRem suppresses ANSI escape sequences on stderr is gated
by `force_terminal()`, which reads a module-level mutable global,
`_NO_TTY_FORCED`. The `print_rich_*` helpers build their own fallback `Console`
via `_console_and_text()` *without* a `no_tty` argument, so they cannot know the
run is headless except by consulting this latch. The latch is set by
`rich_live_progress(no_tty=...)` and restored in a `finally`, so correctness of
`--no-tty` depends on every entry into that context manager latching and
restoring the global in balance — including early-return paths (compact mode,
missing `rich`) and exceptions thrown into the `with` body.

This is fragile: a mutable global used for control flow is invisible at the
`print_rich_*` call sites, the latch and the live-panel concern are conflated in
one context manager, and the unit tests have to assert `_NO_TTY_FORCED is False`
as a precondition to detect leaks from a sibling test that failed to restore it.
It already produced one real bug — when `progress_style != "rich"` the context
manager returned before latching, so `revrem --no-tty --progress-style compact`
leaked ANSI on an interactive non-CI terminal despite the flag's documented
promise (fixed 2026-06-23 by latching before the early return; see
`tests/test_headless_output.py::test_compact_mode_no_tty_latches_and_suppresses_ansi_fallback`).
The fix closed the symptom but left the global-state design in place.

**Possible remediations:**

- Thread `no_tty` (or a small `OutputContext`/headless flag) explicitly through
  the `print_rich_*` helpers and their adapter call sites
  (`adapters/terminal.py`, `adapters/phase_support.py`), so each console is
  built from an explicit argument and `force_terminal` takes no hidden global.
- Alternatively, resolve the headless decision once at run setup and pass an
  immutable rendering context (or a pre-configured `Console` factory) down to
  the helpers, removing per-call recomputation of `force_terminal`.
- If a process-scoped flag must remain, encapsulate it behind a single
  set-once/read accessor with explicit ownership rather than a bare module
  global mutated by a context manager.

**Best practice:** State that drives control flow should be passed explicitly,
not read from a module-level global that callers can neither see nor verify.
When a value is process-scoped by necessity, it should have one owner and a
named accessor, so correctness does not depend on every context manager
restoring it in balance.

---

## TD-001 — `ctx: RunContext | None = None` threading through all phase functions (RESOLVED 2026-05-25)

**Location (historical):** `src/code_review_loop/cli.py` phase functions, later
the migrated runner/adapter phase helpers during Wave C.

**Problem:** Every phase function carried `ctx: RunContext | None = None` as a
trailing parameter. Call sites that did not yet wire `ctx` silently degraded
(the function emitted no events, no type error). The `| None` default meant
there was no compile-time contract that `ctx` was always present.

**Resolution:** Wave C3 removed nullable runner/adapter execution contexts.
Phase execution now goes through required `RunContext` ports and
`rg -n "ctx: RunContext \\| None"` has no hits in `src/code_review_loop`.

**Best practice:** Optional seam parameters are acceptable during incremental migration, but the migration should be completed before the feature is considered stable. A required parameter with no default is self-documenting about the contract.

---

## TD-002 — `acc.iteration` is redundant state in `LoopAccumulator` (RESOLVED 2026-05-25)

**Location (historical):** `src/code_review_loop/cli.py:1975–1978`
(`_run_loop`), later `src/code_review_loop/core/engine.py`
(`LoopAccumulator`)

**Problem:** `LoopAccumulator` carries `iteration: int`, but this is always the same as the `for iteration in range(...)` loop variable. It is re-synced via `replace(acc, iteration=iteration, ...)` at the top of each loop body. Redundant state that must be kept in sync is a maintenance hazard.

**Resolution:** Removed `iteration` from `LoopAccumulator`. The engine carries
iteration as `EngineState.iteration` and passes it to `decide()` only where the
transition table needs it.

**Best practice:** Derived values should not be stored in state. If a value can be computed from other state (here: the loop index), it should be computed at the use site, not carried in a data structure.

**Status (2026-05-25):** RESOLVED in Wave C3c cleanup. `LoopAccumulator` no longer stores `iteration`; `core.engine.run()` carries `EngineState.iteration` and passes it into `decide()` for max-iteration and commit-hook retry decisions.

---

## TD-003 — `_execute_stop` repeats the same tail pattern across four outcome branches (RESOLVED 2026-05-25)

**Location (historical):** `src/code_review_loop/cli.py:1770–1815`
(`_execute_stop`), now `src/code_review_loop/runner.py` (`_execute_stop`)

**Problem:** Each of the four `isinstance` branches sets `final_status`, `stopped_reason`, optional fields, conditionally sets `excerpt`, calls `write_summary`, then either returns or raises. The three returning branches (`OutcomeClear`, `OutcomeFindings`, `OutcomeUnknown`) share an identical `write_summary` + `return summary` tail. Only `OutcomeFailed` diverges structurally (raises instead of returning).

**Resolution:** Extracted a shared helper for the common tail:
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

**Resolution:** Extracted to `_build_routing_payload(resolved_route, triage_payload, run_id, iteration, remediation_input, config)` in `src/code_review_loop/runner.py` during REVREM-TASK-003 Wave C2b. The routing call site is now a named helper path inside the runner executor; the payload builder is independently unit-testable and pure with respect to loop state. Golden-master and artifact-schema suites unchanged.

**Best practice:** Loop bodies should describe control flow, not compute artifacts. Any block of code that builds a data structure from inputs should be a named function.

---

## TD-005 — `OutcomeFailed.reason` is stringly-typed; `outcome_to_exit_code` dispatches on raw strings (RESOLVED 2026-05-25)

**Location:** `src/code_review_loop/core/outcome.py:55–80`

**Problem:** `outcome_to_exit_code` dispatches on `outcome.reason` string literals (`"budget_ceiling_hit"`, `"setup_failed"`, `"cancelled"`) to produce exit codes 3, 4, 5. The `reason` field is typed as `str` with no constraint. A typo or new `reason` value silently falls through to exit code 1 with no type error.

**Fix:** Type `OutcomeFailed.reason` as `Literal["budget_ceiling_hit", "setup_failed", "cancelled", "loop_exhausted", ...]` (enumerate all valid values). Alternatively, use a `StrEnum`. `outcome_to_exit_code` then benefits from exhaustiveness checking if the match is structured appropriately.

**Best practice:** String fields used for control flow dispatch should be `Literal` types or enums. `str` typed fields are not checked at call sites — a rename or new value silently breaks dispatch.

**Status (2026-05-25):** RESOLVED in Wave C3c cleanup. `OutcomeFailed.reason` is now typed as an `OutcomeFailedReason` `Literal[...]` union covering all current failed stopped reasons.

---

## TD-006 — `harness_registry()` copies the registry dict on every call (RESOLVED 2026-05-25)

**Location (historical):** `src/code_review_loop/harnesses.py:335–339`

**Problem:** Every call to `harness_registry()` does `dict(HARNESS_REGISTRY)` unconditionally, even in production where the fake harness is never enabled and the result is always the same. The function is called once per phase command build (`_resolve_executable`, `validate_harness_name`, `require_implemented_harness`, `check_route_capabilities`) — O(N·D) times per iteration across the fallback-chain validation pass.

**Resolution:** `harness_registry()` now returns cached immutable mapping
proxies: one production registry and one fake-enabled registry. Tests assert
both reuse and immutability, so callers cannot rely on mutating a defensive
copy.

**Best practice:** Functions that return a dict copy to protect against mutation should document the reason. If the mutation pattern is test-only, consider making the test inject the registry directly via a parameter rather than relying on a side-effecting copy.

---

## TD-007 — `triage.extract_routing_context` does blocking file I/O on the remediation hot path (RESOLVED 2026-05-25)

**Location:** `src/code_review_loop/triage.py:173–228` (`extract_routing_context`)

**Problem:** `extract_routing_context` is called every routed iteration. It opens and reads up to 1 MB of each `affected_path` listed in the triage payload, then scans all content against 12 `SENSITIVE_SIGNALS` keys. With many affected files or large files, this is synchronous blocking I/O inside the main loop with no caching or deduplication across iterations.

**Note:** At typical repo sizes (< 20 affected files, < 100 KB each) this is not a practical problem. The concern is that future triage payloads from monorepo runs could make this slow without any visible bottleneck in the loop output.

**Resolution:** The runner executor now owns a per-run routing-context cache.
`extract_routing_context(..., cache=...)` keys file-scan results by resolved
path, `st_mtime_ns`, and size, reuses unchanged scans across iterations, and
invalidates automatically when the file changes. Tests cover cache reuse and
invalidation.

**Best practice:** Document the expected performance contract in the function docstring (e.g., "expected < 20 files, < 100 KB each"). This makes the assumption explicit and flags future callers that change the expected scale.
