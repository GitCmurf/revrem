---
document_id: REVREM-TASK-003
type: TASK
title: Re-engineer cli.py from God object into a hexagonal review-loop core
status: Draft
version: '0.1'
last_updated: '2026-05-21'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: A seam-first, behaviour-governed programme to dissolve the 4.9k-line cli.py God object into a reusable hexagonal review-loop engine (functional core + ports/adapters), an outcome ADT, and a thin CLI driver, with the test monolith decomposed in lockstep.
keywords:
- revrem
- refactoring
- architecture
- hexagonal
- ports-and-adapters
- functional-core
- god-object
- cli
- testability
- dependency-injection
- best-practices
- traceability
related_ids:
- REVREM-PLAN-003
- REVREM-TASK-002
- REVREM-TASK-001
- REVREM-DEVEX-001
- REVREM-TEST-001
- REVREM-ADR-003
- REVREM-ADR-006
---

# TASK: Re-engineer `cli.py` from God object into a hexagonal review-loop core

## How To Read This Document

This is an engineering handover for the orchestrator of agentic coding
sessions or a human reviewer assigning work. It is **not** a narrative — for
the post-launch roadmap read `REVREM-PLAN-003`, and for the foundation-phase
PR programme read `REVREM-TASK-002`.

Read in this order:

1. **Context & Evidence** — the measured shape of the problem. Numbers, not
   adjectives.
2. **The Thesis** — the single mental model the whole plan is derived from.
   If you read one section, read this one.
3. **Goal, Non-Goals (YAGNI)** — what we are and are not building. The
   declines are load-bearing; they are how this stays a refactor and not a
   rewrite.
4. **Glossary** — fix vocabulary before the contracts.
5. **Target Architecture** — the abstractions (ports, functional core,
   outcome ADT, state model). File layout is shown last and on purpose: it is
   an *output* of the abstractions, never the goal.
6. **Shared Contracts Registry** — the cross-cutting agreements every wave
   must obey (public-surface sunset, monkeypatch burn-down, output
   governance, the dependency rule, the outcome ADT). **This is the
   load-bearing section.** If a task and the registry disagree, the registry
   wins; amend it in a PR rather than diverging silently.
7. **Wave Dependency Graph + Traceability Matrix** — order and rationale.
8. **Code / Tests / Docs Alignment** + **Global Engineering Rules** — per-PR
   discipline. Read once; cited from each task.
9. **Waves A–D** — PR-sized work packages.
10. **Test Monolith Decomposition** — `tests/test_cli.py` is in scope and
    treated as a co-symptom, not a separate cleanup.
11. **Exit Criteria, Adversarial-Review Anticipation, Sequels.**

## Context & Evidence

`src/code_review_loop/cli.py` is **4,892 lines** and is the package's
single largest module by a factor of 3.3 (next is `profiles.py` at 1,467).
It is the entry point for both console scripts (`code-review-loop` and
`revrem` both resolve to `code_review_loop.cli:main`). It is criticised — 
correctly — as a God object. This task fixes the cause, not the symptom.

The criticism is not stylistic. The following are measured properties of the
file as it stands, and each one is a defect this plan must retire:

| Evidence | Measurement | What it proves |
|---|---|---|
| File size | 4,892 lines, ~140 top-level defs | One module owns parsing, dispatch, config assembly, the loop, five phase executors, progress/terminal I/O, NLP heuristics, summaries, resume, and nine subcommand `*_main` entry points. |
| The loop function | `_run_loop` is **588 lines** (1994–2582) | A single function interleaves preflight, event-sink wiring, phase orchestration, triage routing, policy resolution, prompt composition, artifact writes, terminal I/O, and exit semantics. Engineering-principle target is ≤40. |
| Mutable run state | `summary` dict written **60×**; `iterations` list mutated **17×** | The run's truth is an untyped `dict[str, object]` smeared across the file. This is primitive obsession: a missing domain object. |
| Frozen-config abuse | `object.__setattr__(config, …)` **4×** | A *frozen* dataclass is mutated through a back door to carry run state (`event_sink`, `budget_state`). Config and mutable state are conflated. |
| Time leakage | `datetime.now` / `time.monotonic` at **11 sites** | The loop is nondeterministic. You cannot characterise its output until time is a seam. |
| Half-finished DI | `runner: Runner` is injected, but the five `run_*` phases are called as **module globals** | Dependency injection was started and abandoned. This is the direct cause of the test coupling below. |
| Test reach-in | tests reference **64** distinct `cli.*` symbols and **monkeypatch 18** internals (`run_loop` ×26, `run_codex_review`, `run_remediation`, `run_triage`, `run_commit`, `run_git_preflight`, `refresh_terminal_title`, …) | Tests must reach inside because the module exposes no seams. The coupling is a symptom of the missing abstractions, not a property to preserve. |
| Test monolith | `tests/test_cli.py` is **6,121 lines** | The test file is a parallel God object and a co-symptom of the same disease. |
| Duplicated truth | run state lives in **four** hand-synced shapes: the `summary` dict, the resume payload, run-history, and `events.jsonl` | The same information is maintained four ways, which is why resume is fragile and the summary drifts. |

The repo already has healthy seams to build with (`budgets.py`, `events.py`,
`profiles.py`, `progress.py`, `triage.py`, `policy.py`, `diagnostics.py`,
`harnesses.py`) and a second front-end (`tui.py`) that *should* be able to
drive the loop but currently cannot reach it cleanly. The dispatch in
`main()` is a hand-rolled `if/elif` ladder over `argv[0]` — a clean seam for
a registry.

## The Thesis

> `cli.py` is **four things wearing one trenchcoat**, and **three
> cross-cutting concerns leak through all four**. That is what makes it both
> a God object *and* untestable. Fix the leaks and name the four roles, and
> the file dissolves on its own.

**The four roles (the trenchcoat):**

1. **CLI front-end** — argument parsing, subcommand dispatch, config
   assembly, exit-code mapping.
2. **Loop engine** — the iterate `review → triage → remediate → check →
   commit` state machine.
3. **Phase executors** — the five `run_*` functions that shell out to
   harnesses.
4. **Reporting layer** — summary assembly, run-history, terminal formatting,
   artifact emission.

**The three leaked concerns:**

- **Time** — raw `datetime.now`/`time.monotonic` at 11 sites.
- **Process execution** — `runner` half-injected; phases called as globals.
- **Run state** — an untyped, mutated `dict` plus `object.__setattr__` on a
  frozen config.

**The consequence we will exploit:** there is a **reusable engine trapped
inside a CLI driver**. `tui.py` is a second driver today and a future
SDK/CI surface is a third. The plan frees the engine into a dependency-free
core and demotes `cli.py` to one thin driver over it. File count falls out
of this; it is never a target.

**Two simplifying moves (the leverage):**

- The system is **accidentally half-event-sourced** — `events.jsonl` already
  exists, and resume rehydrates from the summary. The `summary` dict, the
  resume payload, and run-history are the same information in three shapes.
  We **design the engine so those become projections (folds) over the event
  stream**, then land that unification as a staged sequel (Wave E) so the
  core refactor is not blocked on it.
- Exit codes are decided in `main()` from stringly-typed `stopped_reason` /
  `final_status` mutated across 60 sites. We replace them with a closed
  **`RunOutcome` algebraic type** and a single total function
  `outcome → exit_code`, making illegal states unrepresentable and the exit
  contract exhaustive under `mypy`.

## Goal

Deliver a sequence of small, reviewable PRs that turn `cli.py` from a God
object into:

- a **dependency-free review-loop core** (engine + phases + state model +
  review interpretation + policy) that imports no `argparse`, no terminal
  escape codes, and no concrete I/O — only **ports** it declares;
- a set of **adapters** behind those ports (subprocess runner, git, codex
  harness, terminal/Rich progress, jsonl event sink, artifact store, clock);
- a **thin CLI driver** (registry + per-subcommand modules + config
  assembly) and a demonstrated path for **`tui.py` to drive the same core**;
- a **typed `RunState` and `RunOutcome` ADT** replacing the dict-as-object
  and stringly-typed exit logic;
- a **decomposed test suite** that exercises the core with values and fakes
  instead of monkeypatching 18 internals.

Success is measured by **leverage**, not line count (see Exit Criteria).

## Non-Goals (YAGNI — these declines are deliberate)

The taste in this plan is as much in what it refuses as in what it builds.
The following are explicitly **out of scope**, and a PR that introduces any
of them without amending this section should be rejected:

- **No CLI framework swap.** `argparse` stays. No Typer/Click. (Ratified in
  brainstorming; a framework migration is a separate, later task with its own
  help-text/error-format contract.)
- **No new runtime dependency** unless it removes clear operational risk or
  sits behind an optional extra (per `REVREM-TASK-002` dependency
  discipline).
- **No CQRS, no command bus, no separate read/write models.** Lightweight
  fold-over-events only (Wave E), and only where it deletes duplication.
- **No god `Filesystem`/`Path` port.** A focused `ArtifactStore` port earns
  its place; abstracting every path operation does not.
- **No DI container / service-locator framework.** Constructor injection of a
  `RunContext` is the whole mechanism.
- **No async/concurrency rework.** The loop stays synchronous.
- **No plugin system / dynamic harness discovery** beyond the existing
  registry.
- **No behaviour change to the machine contract without a migration note.**
  (See Contract C3.)

A port is justified **only** when it is a genuine test seam or has a real
second implementation in sight. A `Clock` port: yes. An `ArtifactStore`:
yes. A port wrapping a single stable call that is never faked: no — that is
hexagonal cosplay.

## Glossary

- **Core / domain** — the dependency-free review-loop logic: engine, phases,
  `RunState`, `RunOutcome`, review interpretation, policy. Imports no
  adapter, no `argparse`, no terminal codes.
- **Port** — an interface (`Protocol`/ABC) the core *declares* and depends
  on: `Clock`, `ProcessRunner`, `Harness`, `EventSink`, `ProgressReporter`,
  `ArtifactStore`, `GitGateway`.
- **Adapter** — a concrete implementation of a port living at the edge
  (real subprocess, real git, codex harness, terminal/Rich renderer, jsonl
  sink). **Driven adapters** are called by the core; **driving adapters**
  (CLI, TUI, SDK) call into the core.
- **`RunContext`** — the immutable bundle of config + injected ports handed
  to the engine. Replaces the frozen-config-mutation hack.
- **`RunState`** — the typed, in-memory aggregate for one run; replaces the
  `summary` dict and `iterations` list. Built via explicit transitions.
- **`RunOutcome`** — a closed sum type of terminal results (`Clear`,
  `Exhausted`, `SetupFailed`, `BudgetExceeded`, `Cancelled`, `ReviewFailed`,
  …). Mapped to exit codes by one total function.
- **Functional core / imperative shell** — decisions are pure functions of
  state and inputs (`decide`); effects are confined to a thin shell
  (`execute`). The core is tested with values, not mocks.
- **Facade (temporary)** — re-exports left in `cli.py` so the entry point and
  un-migrated tests stay green *between* waves. Scaffolding with a kill-date
  in Wave C, not architecture.
- **Behavior ledger** — `docs/05-planning/behaviour-ledger-task-003.md`: the
  reviewed record of every intentional observable-output change.

## Target Architecture

The architecture is **ports-and-adapters at the edges, functional core /
imperative shell in the engine.** It is described here as abstractions; the
file layout is a consequence shown at the end.

### Ports the core declares

```python
class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...

class ProcessRunner(Protocol):
    def run(self, args: Sequence[str], cwd: Path, *,
            input_text: str | None = None,
            timeout_seconds: float | None = None) -> CommandResult: ...

class Harness(Protocol):                       # one phase executor
    def execute(self, request: PhaseRequest, ctx: RunContext) -> PhaseOutcome: ...

class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...

class ProgressReporter(Protocol):              # semantic, not terminal codes
    def phase(self, phase: str, label: str, status: str, detail: str = "") -> None: ...

class ArtifactStore(Protocol):
    def write(self, name: str, content: str) -> Path: ...

class GitGateway(Protocol):
    def preflight(self, args: Sequence[str]) -> CommandResult: ...
    def repo_root(self, start: Path) -> Path: ...
```

The **dependency rule** is absolute and machine-enforced (Contract C4): the
core imports ports only; adapters import the core; drivers wire adapters into
a `RunContext` and call the core. No edge type ever appears in a core import.

### The engine as a decision-driven loop

The 588-line `_run_loop` is replaced by a short imperative shell over a pure
decision function — landing the refactor *with the grain* of the routing /
triage-v2 / policy work already in the codebase
(`triage.extract_routing_context` → `policy.resolve_routing` →
`prompts_composer.compose_remediation_prompt`):

```python
def run(state: RunState, ctx: RunContext) -> RunOutcome:
    while True:
        decision = policy.next_action(state)        # PURE: state -> Action
        if isinstance(decision, Stop):
            return decision.outcome
        state = execute(decision.action, state, ctx) # SHELL: effects via ports
```

`policy.next_action` is a pure function of `RunState` (no I/O, no clock, no
subprocess) and is therefore tested with values alone. `execute` is the only
place ports are touched. This is what makes the 18 monkeypatches unnecessary:
the decisions have no collaborators to patch, and the effects are swapped by
constructing a `RunContext` with fake ports.

### Phases unified honestly

The five phases are asymmetric today (`run_codex_review` returns
`tuple[str, CommandResult]`; `run_triage` returns a 4-tuple;
`run_remediation` returns `CommandResult`; `run_commit` returns `str`). They
are unified under a `PhaseOutcome` **sum type** — not a
lowest-common-denominator tuple. Forcing false symmetry would be its own
smell; the sum type makes each phase's real result explicit and exhaustive.

### State and outcome as types

`RunState` is an aggregate with invariants enforced by transition methods
(`record_iteration`, `mark_clear`, `mark_failed(reason)`), centralising the
60 scattered `summary[...]` writes and the exit-determining logic in one
place. It serialises via `to_dict()` / `from_dict()` — which also makes
resume **symmetric** (today resume is a bespoke deserialiser with ~15
`_resume_*` helpers). `RunOutcome` is the closed sum type mapped to exit
codes by a single total function (Contract C5).

### Resulting module layout (an output, not the goal)

Helpers go **home** to existing owners, not into shadow wrappers (no
`budget_runtime`, no `progress_io`):

```
core/                         # dependency-free; import-linter enforced
  ports.py                    # the Protocols above + CommandResult, Event, PhaseOutcome
  state.py                    # RunState aggregate + transitions
  outcome.py                  # RunOutcome ADT + exit-code mapping
  engine.py                   # run(state, ctx) decision loop (was _run_loop)
  phases/                     # review / triage / remediate / check / commit (decide+execute split)
  review_interpretation.py    # the NLP heuristics, pure, with a fixture corpus
  policy.py                   # next_action(state) + existing routing (already a module)
adapters/
  subprocess_runner.py        # default_runner + process-tree kill + timeout streaming
  terminal.py                 # titles, escape codes, recovery -> ProgressReporter sink
  git.py                      # GitGateway impl
  artifact_store.py           # ArtifactStore impl
  (events.py / progress.py / harnesses.py / budgets.py already exist; helpers move INTO them)
cli/                          # the thin driver
  __init__.py                 # main() registry dispatch (~10 lines + table)
  args.py                     # all parse_*_args
  config_builder.py           # build_loop_config + profile resolution + coercion
  commands/                   # one module per subcommand: config, suppress, doctor,
                              #   replay, resume, history, policy, triage, bundle
cli.py                        # TEMPORARY facade re-exporting the public surface; deleted in C3
```

`code_review_loop.cli:main` remains the entry point throughout (it becomes a
re-export, then the registry dispatcher). `tui.py` is migrated to construct a
`RunContext` and call `core.engine.run` directly (Wave D), proving the
library/driver split.

## Shared Contracts Registry

Seven cross-cutting contracts. Each is owned by exactly one wave; later waves
consume without redefining. **Drift here causes silent, cross-module bugs.**

### C1. Public Symbol Surface & Facade Sunset (owned by A0, retired by C3)

- The *intended* public API is small: `main`, `LoopConfig` (later
  `RunContext`/`RunState`), `run_loop`/`core.engine.run`, `__version__`, and
  the documented `CommandResult`. Everything else tests reach into is
  **internal**.
- During Waves A–B, `cli.py` re-exports every symbol currently referenced by
  tests so the entry point and un-migrated tests stay green. **The facade
  re-exports by name-binding** (`from core.engine import run as run_loop`),
  never `import core.engine`, so any residual `monkeypatch.setattr(cli, …)`
  still rebinds the name the consumer reads — until that test is migrated.
- A CI test (`tests/test_public_surface.py`) asserts the entry point resolves
  and the *intended* public names import from their final homes.
- **Sunset:** Wave C3 deletes the facade. A symbol may only lose its
  re-export once no test references it (tracked by C2). The facade is
  scaffolding with a kill-date, not a compatibility layer we keep.

### C2. Monkeypatch Burn-Down (owned per extracting wave, zero by C3)

The 18 monkeypatched internals are classified and retired, not preserved:

| Class | Symbols | Resolution |
|---|---|---|
| Patched at the `main()` boundary | `run_loop` (×26), `write_summary`, `default_artifact_dir` | Stay patchable via the driver seam; tests construct inputs/`RunContext`. |
| Consumed *inside* the loop | `run_codex_review`, `run_remediation`, `run_triage`, `run_commit`, `run_subprocess_with_terminal_title_refresh`, `default_runner`, `run_git_preflight`, `lexical_git_repo_root`, `refresh_terminal_title`, `terminal_columns`, `write_terminal_control_to_tty` | Replaced by **fake ports** in `RunContext`. Patching is deleted, not migrated. |
| Module-level state / config knobs | `TERMINAL_TITLE_REFRESH_SECONDS`, `_LAST_CANCELLATION_SIGNAL_AT`, `_RICH_UNAVAILABLE_WARNED`, `datetime` | Become explicit config on the relevant adapter or the `Clock` port. |

- Each extracting PR includes a **burn-down line** in its body: symbols
  retired this PR / symbols remaining. The phase exits when the count is 0
  (or a residue is documented with rationale).
- A ratchet test (`tests/test_monkeypatch_ratchet.py`) asserts the count of
  `monkeypatch.setattr(MODULE, …)` call sites never increases.

### C3. Output Contract Governance — relaxed but instrumented (owned by A2)

Behaviour preservation is **asymmetric**, governed by a change-*detector*,
not a change-*preventer*:

- **Machine contract** — JSON summary shape, `events.jsonl`, and exit codes —
  is **versioned and migration-gated**. Any change carries a `schema_version`
  bump (per `REVREM-TASK-002` C1), a `CHANGELOG.md` entry, and a behavior
  ledger line. Unintended changes **fail CI**.
- **Human presentation** — terminal text, progress rendering, ordering of
  cosmetic output — is **freely improvable**. It is a projection, not a
  contract; tests must not assert on it beyond smoke level.
- The golden-master suite (built in A2) is the instrument: every diff is
  either (a) an intended, ledgered change, or (b) a CI failure. There is no
  silent third option.
- `docs/05-planning/behaviour-ledger-task-003.md` records each intentional
  change: what, why, before/after, contract-version impact.

### C4. The Dependency Rule (owned by B0, enforced phase-wide)

- The core (`core/`) imports **only** the standard library, ports, and other
  core modules. It must not import `argparse`, `adapters/*`, `cli/*`,
  `terminal`, or `tui`.
- Adapters import core; drivers import both. **No cycles.**
- Enforced mechanically by `import-linter` contracts in CI
  (`importlinter` config in `pyproject.toml`), plus a layered-architecture
  contract. This is the hexagon made real; "we’ll be disciplined" is not
  acceptance.

### C5. `RunOutcome` ADT & Exit-Code Mapping (owned by B3)

- Terminal results are a closed sum type. Exit codes are produced by a single
  total function `exit_code(outcome) -> int`, exhaustive under `mypy`
  (`assert_never` in the fallthrough).
- The mapping preserves today's codes exactly (0 clear, 1 error, 2 findings
  remain, 3 budget, 4 setup, 5 cancelled — per `REVREM-TASK-002` C5) unless a
  change is ledgered under C3.
- No `stopped_reason` string is read to decide control flow after B3; strings
  become display labels derived *from* the outcome, not inputs *to* it.

### C6. The `Clock` Seam (owned by A1)

- All wall-clock and monotonic reads go through `ctx.clock`. The default
  adapter is the real clock; tests inject a deterministic fake.
- No `datetime.now()` / `time.monotonic()` / `time.sleep()` appears in
  `core/` after A1. A grep-gate test enforces this.

### C7. `RunContext` & Construction (owned by B0)

- The engine receives **all** collaborators through one immutable
  `RunContext`; it constructs none itself and reads no module globals for
  behaviour.
- Exactly one production assembler (`cli/config_builder.py`) and one test
  helper (`tests/support/fake_context.py`) build a `RunContext`. Drivers
  (CLI, TUI) differ only in which adapters they wire.

## Wave Dependency Graph

```text
A0 baseline + public-surface pin + import-linter scaffold
  ├─> A1 Clock seam                         (unblocks deterministic snapshots)
  │     └─> A2 golden-master + fake ports   (the safety net; needs A1)
  │           └─> A3 RunState behind dict   (to_dict == current, byte-for-byte)
  └─> B0 ports + RunContext + dependency rule (needs A0)
        ├─> B1 review_interpretation (pure + corpus)
        ├─> B2 Phase protocol + 5 executors as ports  (retires run_* patches; needs A2,B0)
        │     └─> B3 engine = decision loop + RunOutcome ADT  (kills _run_loop; needs A3,B2)
        └─> B4 terminal -> ProgressReporter sink           (engine drops terminal import)
              └─> C1 command registry + slim main()
                    └─> C2 config-assembly + arg-parsing units
                          └─> C3 DELETE facade + split test_cli.py + enforce gates
                                └─> D1 prove leverage (TUI drives core; acceptance scenarios)
                                      └─> E1+ (SEQUEL) events-as-source-of-truth folds
```

Parallelism: A1 and B0 may start together after A0. B1 and B4 are
independent of B2/B3 and may run in parallel. C-wave is strictly sequential.
Wave E is a named sequel, not part of this task's exit criteria.

## Traceability Matrix

| Wave | Plan link | Defect retired (from Evidence) | Contract frozen | Leverage unlocked |
|---|---|---|---|---|
| A0 | REVREM-PLAN-003 hardening | — (baseline) | C1 public surface | Safe incremental extraction |
| A1 | REVREM-TEST-001 determinism | Time leakage (11 sites) | C6 Clock | Deterministic tests |
| A2 | REVREM-TEST-001 | Test reach-in (precondition) | C3 output governance | Change-detector safety net |
| A3 | REVREM-PLAN-003 | Mutable dict (60×); frozen abuse (4×) | — | Typed run state |
| B0 | REVREM-ADR-006 architecture | Half-finished DI | C4, C7 | Hexagon + injectable core |
| B1 | engineering-principles §4 | Heuristics inline | — | Reusable, fixture-backed NLP |
| B2 | REVREM-TASK-002 F10 fake harness | Phases as globals; 11 internal patches | C2 burn-down | Mock-free phase tests |
| B3 | REVREM-TASK-002 C5 exit codes | 588-line loop; stringly-typed exits | C5 RunOutcome | Exhaustive exit contract |
| B4 | REVREM-PLAN-002 TUI readiness | Engine welded to terminal | — | Engine renderer-agnostic |
| C1 | REVREM-DEVEX-001 | `if/elif` dispatch ladder | — | Add subcommand w/o central edit |
| C2 | REVREM-DEVEX-001 | Config assembly in God object | — | Isolated front-end |
| C3 | REVREM-TEST-001 | 6,121-line test monolith; facade | C1 sunset, C2 zero | Tests mirror modules |
| D1 | REVREM-PLAN-002 | "Library trapped in driver" | — | TUI/SDK drive same core |

## Code / Tests / Docs Alignment

Per `REVREM-TASK-002`'s alignment contract, every PR leaves runtime, tests,
and docs in agreement. Refactor-specific additions:

| Change type | Code surface | Required tests | Required docs |
|---|---|---|---|
| Port introduced | `core/ports.py` + real adapter | Adapter contract test + a fake used by ≥1 core test | Port table in this doc; ADR if it shifts boundaries |
| Symbol moved home | new module + temporary re-export | Import-from-final-home test | C2 burn-down line in PR body |
| Output changed | engine/adapter | Golden-master diff reviewed as contract | Behavior ledger + CHANGELOG + `schema_version` if machine |
| Outcome/exit change | `core/outcome.py` | Exhaustiveness test + per-code reachability | Exit-code table + `--help` + README |
| Test extracted | new `tests/test_*.py` | Same assertions, no `monkeypatch.setattr(MODULE,…)` added | — |

## Global Engineering Rules

These augment (do not restate) the rules in `REVREM-TASK-002` and
`engineering-principles-v1.1.md`. Cited from each wave.

- **Atomic unit of work** = code + tests + docs (governed by C3 where output
  changes).
- **Single execution owner.** `core.engine.run` is the *only* execution
  owner after B3; CLI, TUI, reports, history, replay consume its outputs.
  (This is `REVREM-TASK-002`'s rule, relocated to its proper home.)
- **Behaviour-preserving by default, ledgered by exception** (C3).
- **The dependency rule is non-negotiable** (C4) and machine-checked.
- **No new monkeypatch targets** (C2 ratchet).
- **Module discipline.** New modules < 600 lines; functions target ≤ 40.
  These are *guardrails, not goals* — acceptance is coupling/leverage (Exit
  Criteria), and a cohesive 250-line module beats four anaemic 60-line ones.
- **Every extraction is reversible.** One concern per PR; each PR green and
  shippable on its own.

## Waves

Each wave is a PR-sized package. Format: **Intent · Changes · Tests · Exit ·
Risk**. Waves cite contracts by id rather than restating them.

### Wave A — Seams & Safety Net

**A0. Baseline, public-surface pin, import-linter scaffold**
- *Intent:* make extraction safe before touching structure.
- *Changes:* add `import-linter` (dev dep) with a placeholder contract; add
  `tests/test_public_surface.py` (C1); create the behavior ledger file (C3);
  add the C2 ratchet test seeded at the current count (18).
- *Tests:* surface test green; ratchet asserts ≤ current.
- *Exit:* CI green; no production code moved.
- *Risk:* low. Pure scaffolding.

**A1. Introduce the `Clock` port** (C6)
- *Intent:* remove the #1 nondeterminism source so output can be pinned.
- *Changes:* add `Clock` to `core/ports.py` (or a pre-core `clock.py`
  pending B0); thread `ctx.clock`/parameter through the 11 time sites; real
  clock is the default so behaviour is identical.
- *Tests:* a fake clock makes `started_at`/durations deterministic; grep-gate
  forbids raw time reads in the engine path.
- *Exit:* loop output is reproducible under a fixed clock.
- *Risk:* medium — touch points are scattered; mitigated by default-real.

**A2. Golden-master suite + fake ports** (C3)
- *Intent:* the change-detector that makes every later wave safe.
- *Changes:* add `tests/support/` with a `FakeRunner`/fake-harness and fake
  clock; capture golden snapshots of JSON summary, `events.jsonl`, and exit
  codes for every subcommand and the loop happy/sad/budget/cancel paths.
- *Tests:* snapshots committed; a diff harness fails on unledgered change.
- *Exit:* every public behaviour has a pinned snapshot. **Depends on A1.**
- *Risk:* medium — building deterministic fixtures is the real work; this is
  why A1 precedes it.

**A3. `RunState` behind the dict**
- *Intent:* introduce the typed aggregate without changing output.
- *Changes:* add `core/state.py`; build `RunState` inside the loop and assert
  `RunState.to_dict()` equals the current `summary` dict byte-for-byte;
  remove the 4 `object.__setattr__` calls by moving run state off the frozen
  config.
- *Tests:* equivalence test against A2 snapshots; frozen-config no longer
  mutated.
- *Exit:* dict is produced *from* `RunState`; 60 scattered writes become
  transitions.
- *Risk:* medium.

### Wave B — Free the Reusable Core

**B0. Ports, `RunContext`, dependency rule** (C4, C7)
- *Intent:* establish the hexagon spine.
- *Changes:* create `core/ports.py` with all Protocols; `RunContext`; wire
  the real adapters; turn the A1 clock into a port; promote the import-linter
  contract to enforce core-imports-no-edge.
- *Tests:* import-linter contract passes; a `RunContext` builds from fakes.
- *Exit:* engine receives all collaborators via `RunContext`.
- *Risk:* medium-high — defines the boundary everything else assumes.

**B1. `review_interpretation` (pure)** (engineering-principles §4)
- *Intent:* extract the reusable, dependency-free NLP heuristics.
- *Changes:* move `detect_review_status` and the prose/finding helpers to
  `core/review_interpretation.py`; add a fixture corpus with provenance.
- *Tests:* fixture-based table tests; cli re-exports during transition.
- *Exit:* heuristics testable and reusable in isolation.
- *Risk:* low — pure functions.

**B2. `Phase` protocol + five executors as ports** (C2)
- *Intent:* finish the abandoned DI; retire the internal monkeypatches.
- *Changes:* define `Harness`/`PhaseOutcome`; convert `run_codex_review`,
  `run_remediation`, `run_triage`, `run_checks`, `run_commit` to phase units
  invoked via `ctx`; split each into pure `decide` + effectful `execute`.
- *Tests:* migrate phase tests to fake harnesses; **delete** the
  corresponding `monkeypatch.setattr(MODULE,…)` sites; burn-down line in PR.
- *Exit:* engine calls phases through `ctx`, not globals.
- *Risk:* high — the central seam; gated by A2 snapshots.

**B3. Engine = decision loop + `RunOutcome` ADT** (C5)
- *Intent:* kill the 588-line function and the stringly-typed exits.
- *Changes:* `core/engine.py` with `run(state, ctx)` over
  `policy.next_action`; `core/outcome.py` with the ADT + total exit mapping;
  `main()` maps outcome → exit via the one function.
- *Tests:* pure `next_action` value tests; exhaustiveness + per-exit-code
  reachability; snapshots unchanged (or ledgered).
- *Exit:* `_run_loop` deleted; no control-flow reads `stopped_reason`.
- *Risk:* high — the heart. **Depends on A3, B2.**

**B4. Terminal → `ProgressReporter` sink**
- *Intent:* decouple the engine from the terminal entirely.
- *Changes:* engine/phases emit semantic progress; `adapters/terminal.py`
  becomes a sink behind `ProgressReporter`; engine drops the `terminal`
  import.
- *Tests:* a recording reporter asserts emitted events; terminal adapter
  tested separately; retires terminal monkeypatches (C2).
- *Exit:* `core/` has no terminal import (C4 check passes).
- *Risk:* medium.

### Wave C — Collapse the Front-End & Retire Scaffolding

**C1. Command registry + slim `main()`**
- *Intent:* replace the `if/elif` ladder with a registry.
- *Changes:* `cli/__init__.py` registry; per-subcommand modules under
  `cli/commands/` (config, suppress, doctor, replay, resume, history, policy,
  triage, bundle); `main()` becomes table dispatch (~10 lines).
- *Tests:* per-subcommand tests relocated; dispatch test; snapshots hold.
- *Exit:* adding a subcommand touches only its module + the registry table.
- *Risk:* medium — `resume` carries the ~15 `_resume_*` deserialisers; folds
  into `RunState.from_dict` (symmetry with A3).

**C2. Config-assembly + arg-parsing units**
- *Intent:* isolate the remaining front-end logic.
- *Changes:* `cli/config_builder.py` (`build_loop_config`, profile
  resolution, coercion) and `cli/args.py` (all `parse_*_args`).
- *Tests:* config-assembly tests extracted from `test_cli.py`.
- *Exit:* `cli.py` holds only the temporary facade.
- *Risk:* low-medium.

**C3. Delete the facade + split the test monolith** (C1 sunset, C2 zero)
- *Intent:* remove scaffolding; finish the co-symptom.
- *Changes:* delete `cli.py` re-exports (keep the thin entry-point shim);
  migrate residual `MODULE.X` references; split `tests/test_cli.py` per the
  Decomposition section; promote import-linter + ratchet + grep gates to
  required.
- *Tests:* full suite green from the new layout; ratchet at 0.
- *Exit:* no facade; monkeypatch count 0; `test_cli.py` decomposed.
- *Risk:* medium — large mechanical diff; do last, when seams exist.

### Wave D — Prove Leverage

**D1. Demonstrate the library/driver split**
- *Intent:* prove the thesis, not just assert it.
- *Changes:* migrate `tui.py` to build a `RunContext` and call
  `core.engine.run` directly; add acceptance tests for the leverage claims.
- *Tests:* (a) import-linter proves `core` has zero CLI/terminal/argparse
  deps; (b) TUI-drives-core integration test; (c) "add a no-op subcommand in
  one module" test; (d) "swap a review heuristic via a fake `Harness`" test.
- *Exit:* all Exit Criteria below demonstrably met.
- *Risk:* low — mostly verification.

### Wave E — Sequel (named, not in this task's exit criteria)

**E1+. Events as the source of truth.** Make `RunState`/summary, the resume
payload, and run-history **projections (folds)** over `events.jsonl`,
deleting the parallel bookkeeping. Designed-for by A3/B3 (typed state, event
emission already on the stream) but staged so the core refactor is not
blocked. Carries its own spec when scheduled.

## Test Monolith Decomposition (`tests/test_cli.py`, 6,121 lines)

The test file is a co-symptom and is dismantled *as the seams land*, not in a
separate cleanup:

- **During A2:** new behaviour is pinned by golden-master + fakes, not by
  reaching into internals.
- **During B2/B3/B4:** every retired monkeypatch deletes or rewrites its
  test to use fake ports / value-based assertions (C2 ratchet enforces no
  regression).
- **During C3:** the residue splits to mirror modules:
  `test_review_interpretation.py` (fixture corpus),
  `test_engine.py` (pure `next_action` + loop transitions with fakes),
  `test_phase_*.py`, `test_<subcommand>.py`, and a thin
  `test_cli_e2e.py` for golden `main()` paths.
- **End state:** the 64-symbol / `MODULE.X` reach-in shrinks to the intended
  public API; no test imports an engine internal.

## Phase Exit Criteria — leverage, not line count

The task is complete when **all** hold:

1. **Core is dependency-free.** `import-linter` proves `core/` imports no
   `argparse`, no `adapters/*`, no `cli/*`, no terminal, no `tui`. (C4)
2. **Engine is drivable without the CLI.** A test constructs a `RunContext`
   and runs a full loop with fakes, no `argparse` and no real subprocess.
3. **The TUI drives the same core** through a `RunContext` (D1).
4. **Adding a subcommand or swapping a heuristic is a one-module change**,
   demonstrated by acceptance tests (D1).
5. **Monkeypatch count is 0** (C2 ratchet) and the facade is deleted (C1).
6. **Exits are exhaustive.** `RunOutcome → exit_code` is total and
   `mypy`-checked; every code has a reachability test (C5).
7. **No nondeterminism in the core.** No raw time reads in `core/` (C6).
8. **The dependency graph is acyclic** (import-linter layered contract).
9. **`test_cli.py` is decomposed**; tests mirror modules.
10. **Machine contract is unchanged or fully ledgered** (C3); human output
    changes are noted but unconstrained.

Line-count and function-length guardrails (modules < 600, functions ≤ 40)
are *checked but advisory*: a justified exception in a PR body is acceptable;
a coupling or cycle violation is not.

## Adversarial-Review Anticipation

Pre-empting the sharp questions a reviewer will (rightly) ask:

- **"You can't snapshot a nondeterministic CLI, so A2 is impossible."**
  Correct — which is why A1 (the `Clock` seam) precedes A2 and A2 also
  injects a fake runner. Determinism is built before it is relied on.
- **"Moving the loop will silently break `monkeypatch.setattr(cli,
  'run_codex_review')`."** Acknowledged as the central risk (C2). It is not
  worked around with a permanent facade; the patches are *deleted* as phases
  become ports, gated by A2 snapshots so a silent break fails CI.
- **"This is hexagonal cosplay for a local CLI."** The Non-Goals enumerate
  the declines (no CQRS, no god-filesystem port, no DI container, no async).
  A port exists only as a test seam or a real second implementation;
  functional-core/imperative-shell — not ceremony — is what removes the
  mocks.
- **"You relaxed byte-identity, so you can break users."** The relaxation is
  asymmetric and instrumented (C3): the machine contract stays
  migration-gated and CI-enforced; only human presentation is free.
- **"15 modules is just fragmentation."** File count is explicitly an output
  (Target Architecture) and acceptance is leverage (Exit Criteria), not line
  count. Helpers move to existing owners; no shadow wrappers.
- **"Big-bang risk at the end."** Risk is front-loaded: the dangerous core
  work (B2/B3) happens mid-programme behind the A-wave net, not as a final
  cutover. C3 is mechanical and last.

## Open Questions

- Final package shape: `core/` + `adapters/` + `cli/` subpackages vs. flat
  modules with naming discipline. (Leaning subpackages for the import-linter
  contract clarity; confirm at B0.)
- Whether `policy.next_action` subsumes the existing `policy.resolve_routing`
  or sits beside it. (Resolve when B3 meets the routing code.)
- Exact home for `CommandResult` (a port-adjacent value type): `core/ports.py`
  vs. a dedicated `core/types.py`. (Cosmetic; decide at B0.)
