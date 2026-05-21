---
document_id: REVREM-TASK-003
type: TASK
title: Re-engineer cli.py from God object into a hexagonal review-loop core
status: Draft
version: '0.2'
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

`src/code_review_loop/cli.py` is **4,946 lines** and is the package's
single largest module by a factor of 3.4 (next is `profiles.py` at 1,467).
It is the entry point for both console scripts (`code-review-loop` and
`revrem` both resolve to `code_review_loop.cli:main`). It is criticised — 
correctly — as a God object. This task fixes the cause, not the symptom.

The criticism is not stylistic. The following are measured properties of the
file as it stands, and each one is a defect this plan must retire:

| Evidence | Measurement | What it proves |
|---|---|---|
| File size | 4,946 lines, 166 top-level defs | One module owns parsing, dispatch, config assembly, the loop, five phase executors, progress/terminal I/O, NLP heuristics, summaries, resume, and nine subcommand `*_main` entry points. |
| The loop function | `_run_loop` is **617 lines** (1994–2610) | A single function interleaves preflight, event-sink wiring, phase orchestration, triage routing, policy resolution, prompt composition, artifact writes, terminal I/O, and exit semantics. Engineering-principle target is ≤40. |
| Mutable run state | `summary` dict written **60×**; `iterations` list mutated **17×** | The run's truth is an untyped `dict[str, object]` smeared across the file. This is primitive obsession: a missing domain object. |
| Frozen-config abuse | `object.__setattr__(config, …)` **4×** | A *frozen* dataclass is mutated through a back door to carry run state (`event_sink`, `budget_state`). Config and mutable state are conflated. |
| Time leakage | `datetime.now` / `time.monotonic` at **11 sites** | The loop is nondeterministic. You cannot characterise its output until time is a seam. |
| Half-finished DI | `runner: Runner` is injected, but the five `run_*` phases are called as **module globals** | Dependency injection was started and abandoned. This is the direct cause of the test coupling below. |
| Test reach-in | tests reference **64** distinct `cli.*` symbols and **monkeypatch 18** internals (`run_loop` ×26, `run_codex_review`, `run_remediation`, `run_triage`, `run_commit`, `run_git_preflight`, `refresh_terminal_title`, …) | Tests must reach inside because the module exposes no seams. The coupling is a symptom of the missing abstractions, not a property to preserve. |
| Test monolith | `tests/test_cli.py` is **6,245 lines** | The test file is a parallel God object and a co-symptom of the same disease. |
| Duplicated truth | run state lives in **four** hand-synced shapes: the `summary` dict, the resume payload, run-history, and `events.jsonl` | The same information is maintained four ways, which is why resume is fragile and the summary drifts. |

**Measurement provenance (reproducible; re-run before handoff).** The numbers
above are a snapshot of `feat/triage` as of `last_updated`. They drift as the
file changes, so each is backed by an exact command rather than an adjective:

```bash
wc -l src/code_review_loop/cli.py tests/test_cli.py src/code_review_loop/profiles.py
# _run_loop length: span from its def to the next top-level def
awk '/^def _run_loop/{s=NR} s&&NR>s&&/^(def |class )/{print NR-s" lines ("s"–"NR-1")";exit}' \
  src/code_review_loop/cli.py
# run_loop monkeypatch call-sites (note: spans test_cli.py AND test_resume.py)
grep -rnc 'setattr(MODULE, "run_loop"' tests/ | awk -F: '{n+=$2} END{print n" sites"}'
# distinct internal symbols monkeypatched (C2 ratchet baseline)
grep -rohE 'monkeypatch\.setattr\(MODULE, "[^"]+"' tests/ | sort -u | wc -l
```

A reviewer who re-runs these and finds a delta should treat the delta as the
current truth and update this table; the *shape* of the argument (one module
owning four roles) is invariant to ±100 lines. One caveat already found in
review: the `run_loop` patch count is **26** (23 in `tests/test_cli.py`, 3 in
`tests/test_resume.py`) — a count that scopes only `test_cli.py` under-reports
it as 23. The C2 ratchet (below) counts *distinct internal symbols* (18), a
different metric from *call-sites*; do not conflate them.

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
  assembly) and a demonstrated path for a **non-CLI caller (TUI/SDK) to
  drive the same core** (without changing the TUI's runtime role this phase);
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
  on: `Clock`, `RunIdentity`, `ProcessRunner`, `Harness`, `EventSink`,
  `ProgressReporter`, `ArtifactStore`, `GitGateway`.
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

class RunIdentity(Protocol):                    # deterministic run-scoped ids
    def new_run_id(self) -> str: ...

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

### The engine as a state machine (functional core / imperative shell)

The 588-line `_run_loop` is replaced by a short imperative shell over a pure
decision function. The **concrete deliverable is a small state machine over
the existing fixed phase sequence** (`review → triage → remediate → check →
commit`); the value is that the loop's *shape* becomes data and its decisions
become pure:

```python
def run(state: RunState, ctx: RunContext) -> RunOutcome:
    while True:
        decision = decide(state)                     # PURE: RunState -> Decision
        if isinstance(decision, Stop):
            return decision.outcome
        state = execute(decision.action, state, ctx) # SHELL: effects via ports
```

`decide` is a **new** pure function introduced by this task and living in
`core/engine.py` — it is *not* an existing function and is deliberately
**distinct from `policy.resolve_routing`**, which already exists but solves a
different problem (selecting the *remediation harness/model* once we have
decided to remediate). `decide` selects the *next phase*; `resolve_routing`
configures *one* phase. Today `decide` simply encodes the current fixed
sequence, so behaviour is preserved.

The forward-looking move — landing the refactor *with the grain* of the
triage-v2 / routing work already in the codebase
(`triage.extract_routing_context` → `policy.resolve_routing` →
`prompts_composer.compose_remediation_prompt`) — is that `decide` is the
documented **extension seam** where future policy-driven phase selection
plugs in *without touching the shell*. We are not building that now (it is not
in scope); we are leaving the one seam that makes it a local change later.

Because `decide` is a pure function of `RunState` (no I/O, no clock, no
subprocess) it is tested with values alone, and `execute` is the only place
ports are touched. This is what makes the 18 monkeypatches unnecessary: the
decisions have no collaborators to patch, and effects are swapped by building
a `RunContext` with fake ports.

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
  engine.py                   # run(state, ctx) state machine + pure decide() (was _run_loop)
  phases/                     # review / triage / remediate / check / commit (decide+execute split)
  review_interpretation.py    # the NLP heuristics, pure, with a fixture corpus
  policy.py                   # remediation routing (resolve_routing): pure logic only
  routing_types.py            # Profile/TriageRouteConfig/TriageRoutingRule DTOs lifted from profiles.py
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
re-export, then the registry dispatcher). The library/driver split is proven
in Wave D by a **headless, non-CLI test driver** that builds a `RunContext`
and calls `core.engine.run` directly — **not** by rewiring `tui.py` into the
execution path at runtime. The TUI's runtime role is unchanged this phase
(it stays a control panel and artifact viewer, per the `REVREM-TASK-002`
"no second execution engine" constraint); making the engine *drivable by* a
non-CLI caller is the deliverable, and lifting the TUI into execution is a
later, separately-gated milestone. See Wave D for the exact scope boundary.

### `policy.py` cannot enter the core "unchanged" — and won't

`policy.py` is the one existing module that the naive layout would drop into
`core/` verbatim, and it is the one that would break the dependency rule on
arrival: it imports `from code_review_loop.profiles import Profile,
TriageRouteConfig, TriageRoutingRule`, and `profiles.py` is an edge module
(config loading, validation against harness capabilities). A core module that
imports an edge module violates C4 the moment it lands. The plan resolves this
explicitly rather than discovering it at B0:

- **Chosen resolution (a): lift the pure routing DTOs into the core.** The
  three types `policy.py` consumes are pure, frozen config records with no I/O.
  They move into `core/routing_types.py`; `profiles.py` re-exports them during
  transition and keeps its *edge* concerns (loading from disk, validating a
  profile against installed harnesses). `policy.py` then imports only core
  types and is genuinely dependency-free.
- **Rejected alternative (b): keep `policy.py` outside `core/`** as a
  driver-side domain module, with the engine consuming routing decisions
  through a port. Rejected because routing is pure decision logic with no
  effect to abstract — a port here would be hexagonal cosplay (see Non-Goals),
  and `decide`/`resolve_routing` already want to call it directly.

Earlier drafts of the layout described `policy.py` as "unchanged by this
task"; that was **wrong** and the layout above is corrected. The routing
*logic* (`resolve_routing`) is behaviour-preserved, but its imports change and
its config DTOs relocate.
This split is owned by **B1** (alongside `review_interpretation`), gated by the
import-linter contract from **B0**, and the DTO lift carries a C2-style
re-export burn-down line.

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

- **Two distinct metrics, do not conflate them.** The *burn-down narrative*
  tracks **18 distinct internal symbols** (the table above; goal: 0). The
  *ratchet test* tracks **module-targeted call-sites** — every
  `monkeypatch.setattr(MODULE, …)` occurrence — seeded at the current count of
  **57**, asserting it never increases. (The all-tests `monkeypatch.setattr`
  total is ~119, but most target non-`MODULE` objects and are out of scope.)
- Each extracting PR includes a **burn-down line** in its body: symbols
  retired this PR / symbols remaining (of 18), and call-sites remaining (of
  57). The phase exits when the symbol count is 0 (or a residue is documented
  with rationale).
- The ratchet test (`tests/test_monkeypatch_ratchet.py`) asserts the
  call-site count is `<=` its committed baseline and updates the baseline
  downward as patches are retired.

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
  `terminal`, `tui`, or `profiles` (an edge module — its pure routing DTOs are
  lifted into `core/routing_types.py` in B1b precisely so the core never
  reaches into it).
- Adapters import core; drivers import both. **No cycles.**
- Enforced mechanically by `import-linter` contracts in CI
  (`importlinter` config in `pyproject.toml`), plus a layered-architecture
  contract. This is the hexagon made real; "we’ll be disciplined" is not
  acceptance.

### C5. `RunOutcome` ADT & Exit-Code Mapping (owned by B3)

- Terminal results are a closed sum type. Exit codes are produced by a single
  total function `exit_code(outcome) -> int`, exhaustive under `mypy`
  (`assert_never` in the fallthrough).
- **Scope: `RunOutcome` is the *loop-execution* outcome only**, mapping to
  codes 0 clear, 1 error, 2 findings remain, 3 budget, 4 setup, 5 cancelled
  (per `REVREM-TASK-002` C5), unless a change is ledgered under C3.
- **Subcommands have their own outcomes; code 6 is not lost.** `revrem doctor
  --strict` returns **6** today (`cli.py:4169`, documented at
  `REVREM-DEVEX-001`) — a *command-level* result, not a loop result. The C1
  registry must not re-introduce ad-hoc `return 6` literals (that is the smell
  C5 exists to kill). Chosen model: each outcome type — `RunOutcome` and each
  subcommand's own closed `CommandOutcome` (e.g. doctor's
  `Ok`/`WarningsStrict`/`SetupFailed`) — owns a **total** `exit_code(self) ->
  int`, exhaustive under `mypy` *within that type* (`assert_never` per ADT).
  No subcommand holds a bare `return <int>`; the registry just calls
  `outcome.exit_code()`. (Rejected: a single `exit_code(RunOutcome |
  CommandOutcome)` function — an open-ended union grows with every new
  subcommand and **loses** the `assert_never` guarantee, defeating C5's
  purpose. Also rejected: one mega-ADT subsuming loop and every subcommand —
  it couples unrelated commands and bloats the loop's outcome type.)
- No `stopped_reason` string is read to decide control flow after B3; strings
  become display labels derived *from* the outcome, not inputs *to* it.

### C6. The Determinism Seam: Clock **and** `RunIdentity` (owned by A1)

The Clock is necessary but **not sufficient** for reproducible snapshots. A2's
golden-master promise is only honest if *every* nondeterminism source feeding
the machine contract is either **injected** (made a seam) or **normalized**
(canonicalized in the snapshot comparator). The plan commits a strategy per
source rather than discovering uncovered ones during A2:

Three dispositions, not one. *(As-built in A1; the original "11 sites → inject"
line was a simplification that did not survive contact with the code — some
monotonic reads govern real I/O/signals and **must** stay real, and budget
wall-time is cheaper to normalize than to thread a clock through its helpers.)*

| Source | Site | Disposition |
|---|---|---|
| `run_id` | `cli.py` loop | **Inject** via `RunIdentity.new_run_id()`. |
| `started_at`, `finished_at` | summary | **Inject** via `clock.now()` (the latter through `write_summary`/`add_summary_contract_fields`). |
| Remediation `wall_time_seconds` | routing-outcome artifact + event | **Inject** via `clock.monotonic()`. |
| `Event.ts` | every emitted event | **Inject** — stamped at `JsonlSink.emit` time from the sink's injected clock. The dataclass `default_factory` stays as a test-time fallback. |
| Artifact-dir suffix `{timestamp}-{id}` | `default_artifact_dir` | **Inject** (clock + `RunIdentity`). |
| Double-Ctrl-C debounce; subprocess timeout deadline | signal handler; runner | **Exempt (stays real)** — real-time semantics; faking breaks cancellation/process-killing. Annotated `# det-exempt:`. |
| Terminal display timestamps; bundle "Saved on" date | progress/bundle | **Exempt (stays real)** — human presentation (C3), not machine contract. Annotated `# det-exempt:`. |
| Budget wall-time fields (`wall_elapsed_seconds`, budget elapsed) | summary | **Normalize** in the A2 comparator — *not* injected in A1, to avoid threading a clock through the budget helpers (`budgets.py` keeps its existing `now=` seam). |
| Cwd, git state, absolute paths, byte-size/mtime | summary/resume | **Normalize** in the A2 comparator. |

- Determinism-critical reads go through `clock` / `identity` (passed as kwargs
  in A1, wrapped into `RunContext` in B0). Defaults are the real clock / real
  `uuid4`; tests inject deterministic fakes.
- The grep-gate (`tests/test_determinism_gate.py`) scans the engine-path files
  (`cli.py`, `events.py`) and fails on any raw `datetime.now` / `time.monotonic`
  / `uuid.uuid4` read that is **neither** routed through a seam **nor** annotated
  `# det-exempt: <reason>` on the same line. It is line-number-free (keys off the
  marker), so it survives edits. `budgets.py` is out of the gate's scope this
  wave (its wall-time is normalized, per the row above).
- The A2 golden masters cover the **machine contract only** (JSON summary,
  `events.jsonl`, exit codes) through the comparator's normalizer; human
  presentation is explicitly out of snapshot scope (C3).

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
        ├─> B1 review_interpretation + routing DTOs into core (frees policy.py)
        ├─> B2 Phase protocol + 5 executors as ports  (retires run_* patches; needs A2,B0)
        │     └─> B3 engine = decision loop + RunOutcome ADT  (kills _run_loop; needs A3,B2)
        └─> B4 terminal -> ProgressReporter sink           (engine drops terminal import)
              └─> C1 command registry + slim main()
                    └─> C2 config-assembly + arg-parsing units
                          └─> C3 DELETE facade + split test_cli.py + enforce gates
                                └─> D1 prove leverage (engine drivable headless; acceptance scenarios)
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
| A3 | REVREM-PLAN-003 | Mutable dict (60×) | — | Typed run state |
| B0 | REVREM-ADR-006 architecture | Half-finished DI; frozen abuse (4×) | C4, C7 | Hexagon + injectable core |
| B1 | engineering-principles §4 | Heuristics inline; `policy.py`→`profiles.py` edge import | C4 (policy.py) | Reusable, fixture-backed NLP + edge-free routing |
| B2 | REVREM-TASK-002 F10 fake harness | Phases as globals; 11 internal patches | C2 burn-down | Mock-free phase tests |
| B3 | REVREM-TASK-002 C5 exit codes | 588-line loop; stringly-typed exits | C5 RunOutcome | Exhaustive exit contract |
| B4 | REVREM-PLAN-002 TUI readiness | Engine welded to terminal | — | Engine renderer-agnostic |
| C1 | REVREM-DEVEX-001 | `if/elif` dispatch ladder | — | Add subcommand w/o central edit |
| C2 | REVREM-DEVEX-001 | Config assembly in God object | — | Isolated front-end |
| C3 | REVREM-TEST-001 | 6,121-line test monolith; facade | C1 sunset, C2 zero | Tests mirror modules |
| D1 | REVREM-PLAN-002 | "Library trapped in driver" | — | Engine drivable by non-CLI caller (TUI/SDK-ready) |

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

Each wave is a work package that lands as **one or more** PR-sized changes
(noted where a wave is necessarily multiple PRs). Format: **Intent · Changes
· Tests · Exit · Risk**. Waves cite contracts by id rather than restating
them.

### Wave A — Seams & Safety Net

**A0. Baseline, public-surface pin, import-linter scaffold**
- *Intent:* make extraction safe before touching structure.
- *Changes:* add `import-linter` (dev dep) with a placeholder contract; add
  `tests/test_public_surface.py` (C1); create the behavior ledger file (C3);
  add the C2 ratchet test seeded at the current call-site count (57; the
  burn-down narrative separately tracks the 18 distinct symbols — see C2).
- *Tests:* surface test green; ratchet asserts ≤ current.
- *Exit:* CI green; no production code moved.
- *Risk:* low. Pure scaffolding.

**A1. Introduce the `Clock` and `RunIdentity` ports** (C6)
- *Intent:* remove the nondeterminism sources so output can be pinned. The
  Clock alone is insufficient (see C6 table) — `uuid4` and `Event.ts` are
  pinned in the same wave so A2 is not built on a leaky seam.
- *Changes:* add `clock.py` (`Clock`/`SystemClock`/`utc_iso`) and `identity.py`
  (`RunIdentity`/`SystemRunIdentity`) as pre-core shims (re-homed as ports in
  B0); thread `clock`/`identity` as kwargs through `run_loop` → `_run_loop`,
  `write_summary` → `add_summary_contract_fields`, and `default_artifact_dir`;
  inject `run_id`, `started_at`, `finished_at`, remediation `wall_time_seconds`,
  and the artifact-dir suffix; stamp `Event.ts` at `JsonlSink.emit` from the
  injected clock. Real clock / real `uuid4` are the defaults so behaviour is
  identical. Per the C6 dispositions, real-I/O/signal monotonic reads and
  human-display timestamps stay real (annotated `# det-exempt:`), and budget
  wall-time is deferred to A2 normalization.
- *Tests:* `tests/test_clock_identity_seam.py` proves a fake clock + identity
  make `run_id`, `started_at`, `finished_at`, every event `ts`, and the
  artifact-dir suffix deterministic; `tests/test_determinism_gate.py` fails on
  any unmarked raw time/uuid read in `cli.py`/`events.py`.
- *Exit:* loop output is reproducible under a fixed clock and identity.
- *Risk:* medium — touch points are scattered; mitigated by default-real.

**A2. Golden-master suite + fake ports** (C3) — **two PRs**
- *Intent:* the change-detector that makes every later wave safe. Too large for
  one atomic PR (the plan itself notes "building deterministic fixtures is the
  real work"); split so the machinery lands and proves itself before the
  breadth of cases is added.
  - **A2a — vertical slice (machinery + one path).** Add `tests/support/`
    (`fakes.py` with `FakeClock`/`FakeRunIdentity`/`FakeRunner`,
    `normalize.py`, `snapshot.py`) and `tests/conftest.py` to make `support`
    importable; capture the loop **review-clear** path as the first committed
    golden snapshot (summary + `events.jsonl`), normalized to the machine
    contract; prove the detector *fails on diff* with a negative test. The
    normalizer is kept minimal — only the canonicalizations this path exercises
    (run-dir paths → `<RUN_DIR>`, `wall_elapsed_seconds` → `<DURATION>`); git
    SHAs are null here and byte sizes are stable, so those placeholders are
    deferred to A2b with their first real consumer.
  - **A2b — breadth.** Using the A2a helpers, add golden snapshots for the
    findings-remain / budget / cancel loop paths and each subcommand; extend
    the normalizer (git SHA, byte-size/mtime) only as each consumer needs it.
- *Tests:* snapshots committed; a diff harness fails on unledgered change.
- *Exit:* the machinery is in place and proven on one path (A2a); every
  machine-contract behaviour has a pinned, normalized snapshot (A2b).
  **Depends on A1** (both ports) so the fixtures are not leaky.
- *Risk:* medium — building deterministic fixtures + the normalizer is the
  real work; this is why A1 precedes it and A2a proves the harness end-to-end
  before A2b scales it.

**A3. `RunState` behind the dict** (shadow only)
- *Intent:* introduce the typed aggregate without changing output. **Scope is
  deliberately narrow:** A3 shadows the `summary` dict; it does **not** touch
  the frozen-config back door, because that is not just run state (see below).
- *Changes:* add `core/state.py`; build `RunState` inside the loop and assert
  `RunState.to_dict()` equals the current `summary` dict byte-for-byte; the
  60 scattered `summary[...]` writes become `RunState` transitions while the
  dict is still the emitted artifact.
- *Non-change (intentional):* the 4 `object.__setattr__(config, …)` calls set
  `event_sink` and `budget_state`, which are **collaborators read across
  review/triage/remediation/summary/budget accounting**, not mere run-state
  fields. They have nowhere to live until `RunContext` exists, so their
  removal is **owned by B0/C7**, not A3. Attempting it here would force a
  premature, half-built context.
- *Tests:* equivalence test against A2 snapshots.
- *Exit:* the summary dict is produced *from* `RunState`; the frozen-config
  mutation still exists and is explicitly carried into B0.
- *Risk:* medium.

  > **B0 follow-through (cross-reference, not duplicated work):** when
  > `RunContext` lands in B0, `event_sink` and `budget_state` move onto it and
  > the 4 `object.__setattr__` calls are deleted there. B0's exit criterion
  > includes "frozen-config no longer mutated"; A3's does not.

### Wave B — Free the Reusable Core

**B0. Ports, `RunContext`, dependency rule** (C4, C7)
- *Intent:* establish the hexagon spine.
- *Changes:* create `core/ports.py` with all Protocols; `RunContext`; wire
  the real adapters; turn the A1 clock into a port; promote the import-linter
  contract to enforce core-imports-no-edge. **Relocate `event_sink` and
  `budget_state` off the frozen `LoopConfig` onto `RunContext`, deleting the 4
  `object.__setattr__` calls** that A3 deliberately left in place.
- *Tests:* import-linter contract passes; a `RunContext` builds from fakes;
  grep-gate asserts zero `object.__setattr__(config, …)` remain.
- *Exit:* engine receives all collaborators via `RunContext`; the frozen
  config is no longer mutated.
- *Risk:* medium-high — defines the boundary everything else assumes.

**B1. Pure-domain extraction: `review_interpretation` + routing DTOs**
(engineering-principles §4) — **two PRs**
- *Intent:* extract the reusable, dependency-free domain logic and sever the
  one core-bound module (`policy.py`) from its edge import of `profiles.py`.
- *Changes:*
  - **B1a — `review_interpretation`.** Move `detect_review_status` and the
    prose/finding helpers to `core/review_interpretation.py`; add a fixture
    corpus with provenance; `cli` re-exports during transition.
  - **B1b — routing DTOs into core.** Lift `Profile`, `TriageRouteConfig`,
    `TriageRoutingRule` into `core/routing_types.py`; `profiles.py` re-exports
    them (and keeps its edge loading/validation); repoint `policy.py` to the
    core types so it imports no edge module. `resolve_routing` behaviour is
    unchanged.
- *Tests:* fixture-based table tests for the heuristics; routing tests import
  from core homes; import-linter (from B0) proves `policy.py` is edge-free.
- *Exit:* heuristics and routing testable/reusable in isolation; `policy.py`
  satisfies C4.
- *Risk:* low — pure functions and a mechanical DTO move; the only hazard is a
  missed re-export, caught by the import-from-final-home test.

**B2. `Phase` protocol + five executors as ports** (C2)
- *Intent:* finish the abandoned DI; retire the internal monkeypatches.
- *Changes:* define `Harness`/`PhaseOutcome`; convert `run_codex_review`,
  `run_remediation`, `run_triage`, `run_checks`, `run_commit` to phase units
  invoked via `ctx`; split each into pure `decide` + effectful `execute`.
- *Tests:* migrate phase tests to fake harnesses; **delete** the
  corresponding `monkeypatch.setattr(MODULE,…)` sites; burn-down line in PR.
- *Exit:* engine calls phases through `ctx`, not globals.
- *Risk:* high — the central seam; gated by A2 snapshots.

**B3. Engine state machine + `RunOutcome` ADT** (C5) — **three PRs**
- *Intent:* kill the 588-line function and the stringly-typed exits. This is
  too large for one atomic PR; it lands as three, each green and shippable:
  - **B3a — Read `_run_loop` in full, then extract the engine as a procedural
    shell.** *Mandatory first deliverable (a gate, not a note):* read the whole
    function (1994–2610) line-by-line and produce a **branch → transition →
    outcome table** committed to the behavior ledger, with one row per
    control-flow branch — at minimum: routing outcome, commit-hook retry, final
    review, cancellation (incl. the double-Ctrl-C path), and budget-failure
    (the retry logic ~line 2392) — mapping each to its `RunState` transition and
    its `RunOutcome` variant. This table is what B3b/B3c are audited against;
    without it, "the state machine preserves behaviour" is unverifiable. *Then*
    move the loop body to `core/engine.py` as `run(state, ctx)`, calling phases
    via `ctx` (building directly on B2). Behaviour and structure otherwise
    unchanged. Retires the `run_loop`-internal coupling. **If a branch in the
    tail contradicts the fixed-sequence `decide` shape, raise it against this
    doc before writing B3b.**
  - **B3b — Introduce the state-machine shape.** Add the pure `decide(state)`
    function (encoding the current fixed sequence) and the `execute` shell;
    the loop becomes `decide`/`execute`. Pure-function value tests added.
  - **B3c — `RunOutcome` ADT + total exit mapping.** Add `core/outcome.py`;
    `decide` returns `Stop(outcome)`; `main()` maps outcome → exit via one
    total function; no control-flow reads `stopped_reason`.
- *Tests:* pure `decide` value tests; exit-code exhaustiveness
  (`assert_never`) + per-code reachability; A2 snapshots unchanged (or
  ledgered under C3).
- *Exit:* `_run_loop` deleted; `decide`/`execute` separation in place;
  exits exhaustive.
- *Risk:* high — the heart. **Depends on A3, B2.** Risk is contained by the
  three-PR split and the A2 net.

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
  triage, bundle); `main()` becomes table dispatch (~10 lines). Each command
  returns a `CommandOutcome` whose own total `exit_code()` produces its code
  (C5) — no command holds a literal `return <int>` (including doctor's code 6).
- *Tests:* per-subcommand tests relocated; dispatch test; snapshots hold; a
  grep-gate asserts no bare `return <int>` exit literals survive in `cli/`.
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
- *Changes (largest line item first):*
  - **Migrate the 26 `monkeypatch.setattr(MODULE, "run_loop", …)` sites.**
    These keep working through Waves A–C only because `main()` and the facade
    co-locate `run_loop`; deleting the facade removes the patch target. This
    is the biggest single item in the wave and is **not purely mechanical** —
    each site is rewritten to either patch the engine at its final home
    (`core.engine.run`, where `main()` looks it up) or, preferably, to drive
    `main()` with a `RunContext`/fakes so the engine runs for real. Done in
    its own PR before the facade is removed.
  - Delete `cli.py` re-exports (keep only the thin entry-point shim so
    `code_review_loop.cli:main` resolves); migrate residual read-only
    `MODULE.X` references.
  - Split `tests/test_cli.py` per the Decomposition section.
  - Promote import-linter + ratchet + grep gates from advisory to required.
- *Tests:* full suite green from the new layout; ratchet at 0.
- *Exit:* no facade; monkeypatch count 0; `test_cli.py` decomposed.
- *Risk:* medium-high — the `run_loop` site migration is real work; do last,
  when the engine seam (B3) exists to migrate onto.

### Wave D — Prove Leverage

**D1. Demonstrate the library/driver split**
- *Intent:* prove the thesis, not just assert it.
- *Constraint:* `REVREM-TASK-002` mandates the TUI remain "a control panel
  and artifact viewer, not a second execution engine" and that "no second
  execution engine has been introduced." This task **honours that**: we prove
  the engine is *drivable by a non-CLI caller*, **without** turning the TUI
  into an execution engine at runtime.
- *Changes:* add a headless SDK-style driver in tests/support that builds a
  `RunContext` and calls `core.engine.run`; add acceptance tests for the
  leverage claims. No runtime change wires the TUI into execution — that is
  gated by the milestone that lifts the task-002 constraint.
- *Tests:* (a) import-linter proves `core` has zero CLI/terminal/argparse
  deps; (b) a **headless integration test** drives a full loop through a
  `RunContext` with no `argparse` and no real subprocess (proving the engine
  is driver-agnostic and *available* to the TUI/SDK); (c) "add a no-op
  subcommand in one module" test; (d) "swap a review heuristic via a fake
  `Harness`" test.
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
  `test_engine.py` (pure `decide` + loop transitions with fakes),
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
3. **The engine is drivable by a non-CLI caller** — a headless integration
   test runs a full loop through a `RunContext`, proving the core is
   *available* to the TUI/SDK. (Wiring the TUI into execution at runtime is
   out of scope while the `REVREM-TASK-002` "no second execution engine"
   constraint holds; D1.)
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
- Exact home for `CommandResult` (a port-adjacent value type): `core/ports.py`
  vs. a dedicated `core/types.py`. (Cosmetic; decide at B0.)
- **`_run_loop` full-read is resolved into a B3a gate, not left open.** This
  plan was written from a sampling of `_run_loop` (1994–2610, with the
  budget-retry tail ~line 2392 read in outline only), which is acceptable for
  a *plan* but not for *implementation*. Rather than leave it as a risk, B3a
  now **mandates** a line-by-line read plus a committed branch → transition →
  outcome table as its first deliverable (see Wave B3a). The B3 risk rating
  already assumes control-flow surprises in the tail; the gate forces them to
  surface before B3b/B3c build on the state-machine shape.
