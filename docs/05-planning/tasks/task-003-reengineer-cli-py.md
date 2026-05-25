---
document_id: REVREM-TASK-003
type: TASK
title: Re-engineer cli.py from God object into a hexagonal review-loop core
status: Draft
version: '0.2'
last_updated: '2026-05-24'
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
- **`RunContext`** — the immutable bundle of injected **collaborators / ports**
  handed to the engine. Replaces the frozen-config-mutation hack. *(As-built
  from B0a: config is **not** a `RunContext` field yet — `LoopConfig` lives in
  `cli.py` and pulls in `profiles` (edge), so a core-homed `RunContext` holding
  it would violate C4. Phases take `config` and `ctx` separately until
  `LoopConfig` is core-homed post-B1, at which point config folds onto the
  context.)*
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
  behaviour. *(As-built clarification from B0a: **config is not one of the
  collaborators** carried on `RunContext` yet. C7's literal "config + ports"
  collides with C4 — `LoopConfig` is an edge type (`cli.py`, imports
  `profiles`) and a core-homed `RunContext` cannot import it. Phases consume
  `config` alongside `ctx` until `LoopConfig` is core-homed post-B1. The
  contract still holds: every **collaborator** flows through `RunContext`.)*
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
  - **A2b — loop-path breadth.** Using the A2a helpers, add golden snapshots
    for the remaining **loop terminations**: findings-remain/exhausted (no
    triage, `final_review=False`, `max_iterations=1`), token-budget ceiling, and
    operator cancellation. The latter two terminate by raising `RunLoopFailed`
    (the test reads `exc.summary`). The FakeRunner gains a one-line extension —
    a mapped `BaseException` is raised rather than returned — so cancellation can
    be driven through `run_loop(config, runner, …)`. No new normalizer
    placeholders are required on these paths (non-git fixture → null
    `git_state`, no SHAs; byte sizes stable).
  - **A2c — subcommand breadth.** Add per-subcommand machine-contract snapshots
    and extend the normalizer (git SHA, byte-size/mtime) as each consumer needs
    it. **Split out of A2b** because a subcommand's terminal result is its own
    `CommandOutcome` ADT (C5), not the loop's `RunOutcome`; pinning those is
    cleaner once C1/C5 stabilise the outcome types, and bundling them into A2b
    would make one commit span two unrelated output shapes.
- *Tests:* snapshots committed; a diff harness fails on unledgered change.
- *Exit:* the machinery is in place and proven on one path (A2a); every
  machine-contract **loop** behaviour has a pinned, normalized snapshot (A2b);
  every subcommand machine-contract behaviour is pinned (A2c).
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
- *As-built ("(b1)"):* `RunState` wraps the **live** summary dict + iterations
  list (the same objects the loop reads), so the ~46 `summary[...]` reads and 17
  iteration mutations are untouched; only the 33 in-loop scalar terminal writes
  move behind low-level `set_*` transitions. `to_dict()` returns the live dict,
  so an in-process `to_dict() == summary` check is vacuous — the real
  byte-for-byte gate is the **A2 golden masters staying identical**, backed by
  `tests/test_cli.py` for the un-snapshotted branches. Transitions are
  deliberately low-level (one per write site); semantic methods land in B3.

  > **B0 follow-through (cross-reference, not duplicated work):** when
  > `RunContext` lands in B0, `event_sink` and `budget_state` move onto it and
  > the 4 `object.__setattr__` calls are deleted there. B0's exit criterion
  > includes "frozen-config no longer mutated"; A3's does not.

### Wave B — Free the Reusable Core

**B0. Ports, `RunContext`, dependency rule** (C4, C7) — **two PRs**
- *Intent:* establish the hexagon spine. Split into two commits because the spec
  does two unrelated things — define the structural spine, and surgically
  relocate live collaborators off a frozen dataclass — and bundling both is the
  "big-bang" risk the Adversarial-Review section warns against.
  - **B0a — structural spine (additive, low risk).** Create `core/ports.py` as
    the canonical import surface. **Home `CommandResult` here** (moved out of
    `cli.py`, which re-exports it — it is the value type the runner port forces
    into the core). Define `ProcessRunner` (formalizing the `Runner` callable)
    and `RunContext` (**collaborators only**: `clock`, `identity`, `runner`,
    `event_sink`, `budget_state` — *not* config; see C7 as-built note).
    **Re-export** `Clock`/`RunIdentity`/`EventSink` from their current homes
    rather than physically moving them — moving `Clock` into the core while
    `events` still imports it would create an import cycle; the dependency
    *inversion* is deferred to B2 with the layered contract. Promote the
    import-linter contract to a **partial** dependency rule: `core.*` may not
    import `cli` or `argparse` (expanded forbidden-list, not a near-empty
    `layered` contract — there is no `adapters/` package to layer against until
    B2). **Defer** `Harness`/`ProgressReporter`/`ArtifactStore`/`GitGateway` to
    B2/B4 (no consumer today; writing them now is the "hexagonal cosplay"
    Non-Goal). No relocation, no `setattr` removal, no `ctx` threading.
  - **B0b — relocation (behavioral, medium-high risk).** Build `RunContext` in
    `run_loop`; thread `ctx` through `_run_loop` and the phase functions
    (strategy: add a `ctx` param to the functions that read
    `event_sink`/`budget_state`, keeping their `config` param — the dual param
    vanishes when `LoopConfig` is core-homed); **relocate `event_sink` and
    `budget_state` off the frozen `LoopConfig` onto `RunContext`, deleting the 4
    `object.__setattr__` calls** that A3 deliberately left in place; remove the
    two `LoopConfig` fields; add the grep-gate.
- *Tests:* import-linter contract passes; a `RunContext` builds from fakes
  (B0a); grep-gate asserts zero `object.__setattr__(config, …)` remain (B0b);
  A2 snapshots unchanged across the relocation.
- *Exit:* engine receives all collaborators via `RunContext`; the frozen
  config is no longer mutated.
- *Risk:* medium-high — defines the boundary everything else assumes (the risk
  is concentrated in B0b; B0a is additive).

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

### As-Built State at Wave C Start

*Re-read this before implementing any C wave. The numbers below are live measurements, not targets.*

```bash
wc -l src/code_review_loop/cli.py                             # 4,801 lines
awk '/^def _run_loop/{s=NR} s&&NR>s&&/^(def |class )/{print NR-s" lines";exit}' \
  src/code_review_loop/cli.py                                 # _run_loop: 638 lines (1832–2469)
grep -rnc 'monkeypatch\.setattr(MODULE,' tests/              # 58 monkeypatch sites
grep -c 'monkeypatch\.setattr(MODULE,' tests/test_cli.py     # 47 in test_cli.py alone
```

**What was and was not done in Waves A and B:**

Waves A and B are complete. The following now exist: `core/ports.py`,
`core/state.py`, `core/outcome.py`, `core/engine.py` (with `decide()` and all
`Action` types), `core/review_interpretation.py`, `core/routing_types.py`,
`adapters/checks.py`, `adapters/commit.py`, `adapters/remediation.py`,
`adapters/review.py`, `adapters/terminal.py`, `adapters/triage.py`.

**Critical as-built fact:** The six adapter files are **thin shims**, not real
implementations. Each lazily imports its implementation from `cli.py`:
```python
# adapters/review.py — pattern repeated in all five phase adapters
def execute(self, request, ctx):
    from code_review_loop.cli import run_codex_review  # lazy — avoids circular import
    ...
```
The real phase code (`run_codex_review` at line 917, `run_remediation` at 1079,
`run_triage` at 1128, `run_checks` at 1229, `run_commit` at 1443) is still in
`cli.py`. The adapter docstrings say "until C3". **C3's primary job is to
complete this migration**, moving the implementations into the adapters so the
lazy back-imports can be deleted.

**`_run_loop` is still 638 lines** (line 1832). It calls `decide()` from
`core/engine.py` but the shell — terminal contexts, summary writes, phase
dispatch — is still inlined. `run_loop` (line 1815) is the public wrapper.

**Wave C remediation baseline (2026-05-25).** C1, C2, C3a, the first C3b
import-boundary pass, and the low-risk C3c cleanup items have landed, but Wave
C is **not complete**. The console-script target ``code_review_loop.cli:main``
is now a 27-line entry shim and the old ``monkeypatch.setattr(MODULE, ...)``
reach-in pattern is ratcheted to zero; however, the loop body was moved to
``code_review_loop.runner`` rather than dissolved into ``core.engine.run``. Treat
that commit as a green checkpoint, not the Wave C finish line.

* **C3a is complete.** Every phase implementation now lives in its adapter
  module; no adapter still uses a lazy ``from code_review_loop.cli import
  run_X`` back-import.

  | Phase       | Canonical home                                      |
  |-------------|-----------------------------------------------------|
  | checks      | ``adapters/_checks_impl.py``                        |
  | review      | ``adapters/_review_impl.py``                        |
  | git preflight | ``adapters/git.py`` (new)                          |
  | remediation | ``adapters/_remediation_impl.py``                   |
  | triage      | ``adapters/_triage_impl.py``                        |
  | commit      | ``adapters/_commit_impl.py``                        |

  ``cli/__init__.py`` no longer owns the loop body, but this is only a driver
  relocation. Adapter phase tests and loop integration tests import final homes
  directly instead of using the old ``MODULE`` alias against
  ``code_review_loop.cli``.

  Remediation update: loop-shell helpers used by the moved phases
  (``progress_event``,
  ``write_artifact``, ``_combined_output``, ``phase_timeout_seconds``,
  ``ensure_model_budget``, ``record_model_charge``,
  ``set_phase_terminal_title``, ``log_review_findings``,
  ``review_status_diagnostics``, ``DEFAULT_REMEDIATION_PROMPT``,
  ``DEFAULT_REVIEW_PROMPT``, ``CommitFailed``, ``REVREM_COMMIT_SUFFIX``
  and friends) now have an adapter-neutral home in
  ``code_review_loop.adapters.phase_support``. Adapter implementation modules
  no longer import ``code_review_loop.runner``; the import-linter contract now
  forbids adapters from importing either ``code_review_loop.runner`` or
  ``code_review_loop.cli`` directly or indirectly. Follow-up remediation moved
  the command entrypoint to ``cli/main.py``, moved command helpers into
  command modules, and moved resume preconditions/config reconstruction to
  ``code_review_loop.resume``. ``code_review_loop.runtime`` now owns
  ``RunLoopFailed`` and terminal summary formatting.

  Surgical C3b-style test patches were applied to the legacy phase patches and
  the remaining old ``MODULE`` monkeypatch sites. The ratchet baseline is now
  ``0`` for ``monkeypatch.setattr(MODULE, ...)``.

  ``cli/__init__.py`` is now 6 lines, down from 4946 at the start of Wave C.
  ``resume`` no longer imports the executable driver; the resume command calls
  ``runner.resume_run`` after preconditions pass. Follow-up remediation renamed
  the relocated loop driver from ``loop`` to ``runner`` and deleted the legacy
  ``_run_loop`` symbol. The current runner session shell is 35 lines, with the
  happy path delegated to named helpers. Production phase decisions now pass
  through ``core.engine.run`` via a runner-local executor bridge, and
  `tests/test_runner_engine_gate.py` fails if `runner.py` reintroduces direct
  ``decide()`` calls.

* **C3c tech-debt cleanup is mostly complete.** TD-001, TD-002, TD-003, and
  TD-005 are resolved: `RunContext` is required in the runner/adapter execution
  helpers, `LoopAccumulator` no longer stores `iteration`, `_execute_stop` has a
  shared stop-tail helper, and `OutcomeFailed.reason` is now a `Literal[...]`
  union. `RunState.to_dict()` now returns a fresh projection instead of the live
  source of truth.

  Test decomposition is complete for Wave C. The original CLI monolith has been
  reduced to an 87-line smoke/e2e file, and progress/terminal-title,
  commit/check, triage-loop, config/profile/history,
  doctor/preflight/bug-bundle, fake harness, resume/initial-review,
  review-helper/command-construction, suppressions, subprocess/terminal-title,
  loop-outcome/budget/cancellation, and summary formatting coverage now live in
  `tests/test_cli_progress_integration.py`,
  `tests/test_cli_commit_integration.py`,
  `tests/test_cli_triage_integration.py`,
  `tests/test_cli_config_integration.py`,
  `tests/test_cli_doctor_integration.py`,
  `tests/test_cli_fake_harness_integration.py`,
  `tests/test_cli_resume_integration.py`,
  `tests/test_cli_review_helpers.py`,
  `tests/test_cli_suppressions_integration.py`,
  `tests/test_cli_subprocess_integration.py`,
  `tests/test_cli_loop_outcomes_integration.py`, and
  `tests/test_cli_summary_integration.py`.

* **Gate status at this checkpoint:** targeted runner/adapter gates pass:
  `./.venv/bin/ruff check src/code_review_loop/runner.py`,
  `./.venv/bin/mypy src`, `./.venv/bin/lint-imports`, and focused pytest
  selections for loop, commit/check, progress, cancellation, budget, triage, and
  routing paths. The full local gate passed after the final decomposition:
  `./.venv/bin/ruff check .`, `./.venv/bin/mypy src`,
  `./.venv/bin/lint-imports`, `uv run --locked meminit check --format json`,
  and `./.venv/bin/pytest -q` (`727 passed`).

**Required remediation before declaring Wave C done.**

1. DONE in remediation: ``core.engine.run(state, ctx)`` exists as a
   dependency-free orchestration path over ``decide`` plus an injected
   executor, and the production runner consumes it for phase decisions instead
   of calling ``decide()`` directly.
2. DONE in remediation: replace the partial import rules with contracts that
   prove core does not import drivers/adapters, adapters do not import
   ``cli`` or ``runner``, and resume planning does not import ``runner``.
3. DONE in remediation: delete the ``cli.__getattr__`` compatibility facade.
4. DONE in remediation: legacy phase fallback branches are removed and
   ``RunContext`` phase harnesses are required. TD-001 nullable execution
   contexts are gone from runner and adapter execution helpers.
5. DONE in remediation: the driver module has been renamed to ``runner``,
   resume execution is owned by ``runner.resume_run``, ``_run_loop`` is gone,
   ``_run_session`` is 35 lines, and production phase decisions are mediated by
   ``core.engine.run``.
6. DONE in remediation: decompose ``tests/test_cli_integration.py`` into
   behavior-level modules. The remaining file is an 87-line smoke/e2e surface;
   focused modules now cover progress/terminal-title, commit/check,
   triage-loop, config/profile/history, doctor/preflight/bug-bundle, fake
   harness, resume/initial-review, review-helper/command-construction,
   suppressions, subprocess/terminal-title, loop-outcome/budget/cancellation,
   and summary formatting clusters.
7. DONE in remediation: ``RunState`` now has semantic terminal transitions
   (``mark_outcome``/``mark_clear``/``mark_failed``/``mark_findings``/
   ``mark_unknown``), ``_execute_stop`` uses them, and ``to_dict()`` now returns
   a fresh summary projection instead of the live source of truth.

**Wave C1 + C2 status (2026-05-24).** C1a, C1b, C2a (both parts) and the
TD-004 half of C2b have landed.
* `cli/args.py` is the canonical home for every `parse_*_args` parser and the
  three argparse choice tuples (`REASONING_EFFORT_CHOICES`,
  `PROGRESS_STYLE_CHOICES`, `COMMIT_ON_HOOK_FAILURE_CHOICES`). `cli/__init__.py`
  re-exports each.
* `cli/config_builder.py` is the canonical home for `LoopConfig` assembly +
  argument-resolution helpers (`build_loop_config`, `profile_from_loop_config`,
  `should_prompt_for_new_profile`, `new_profile_from_args`,
  `default_artifact_dir`, `ensure_default_artifact_ignore`,
  `resolve_timeout_seconds`, `resolve_max_iterations`,
  `parse_harness_bin_overrides`, `resolve_profile_timeout_seconds`,
  `profile_or_default`, `pick`) + `DEFAULT_TIMEOUT_SECONDS`. The names
  `LoopConfig`, `lexical_git_repo_root`, `git_info_exclude_path`,
  `resolve_initial_review_file` still live in the parent package and are
  reached through a `_cli_module()` accessor inside `config_builder` to break
  the import cycle (`LoopConfig` is defined later in `cli/__init__.py` than
  the import of `config_builder`); the same accessor is used for
  `profile_or_default` and `default_artifact_dir` so existing
  `monkeypatch.setattr(MODULE, …)` test sites keep taking effect until C3b
  retires them.
* `_run_loop` no longer inlines the routing-payload assembly: TD-004 is now
  the standalone, unit-testable `_build_routing_payload(...)` in
  `cli/__init__.py`. TD-002 (`acc.iteration` → loop variable) is deferred
  past C2b because it would change the signature of `decide()` and touch ~54
  sites in `tests/test_engine_decide.py`; the deferral is recorded in
  `docs/05-planning/tech-debt.md`.

`main()` dispatches through `_build_subcommand_registry()` — the `if/elif`
ladder is gone. Tests: `tests/test_cli_dispatch.py` pins the registry
mapping; `tests/test_cli_commands_outcome_gate.py` is a grep-gate that fails
any bare `return <int>` literal reintroduced under `cli/commands/`.

**Status of the original C1a status block below.** Both have landed.
`src/code_review_loop/cli.py` is now the package `src/code_review_loop/cli/`,
with the legacy God-object body living in `cli/__init__.py` (≈4,528 lines after
extraction, down from 4,801) and per-subcommand entry points in
`cli/commands/{bundle,config,doctor,history,policy,replay,resume,suppress,triage}.py`.
Each command module returns through the `CommandOutcome` ADT in
`cli/outcome.py` (`CommandOk` / `CommandFailed`); the legacy `*_main` symbols
in `cli/__init__.py` are now two-line delegators preserved for back-compat.
`main()` dispatches through `_build_subcommand_registry()` — the `if/elif`
ladder is gone. Tests: `tests/test_cli_dispatch.py` pins the registry
mapping; `tests/test_cli_commands_outcome_gate.py` is a grep-gate that fails
any bare `return <int>` literal reintroduced under `cli/commands/`. Helpers
listed for C2 relocation (`_suppression_*_for_scope`,
`resume_precondition_issues`, `resume_run`, `latest_resume_review_path`,
`policy_lint`, `policy_review`, `triage_explain`, `profile_or_default`,
`profile_routed_harnesses`, `_suppression_doctor_issues`,
`_format_profile_list_item`, `edit_profile_config`, `new_profile_from_args`,
`_doctor_artifact_dir`) are still in `cli/__init__.py` and looked up lazily
from the command modules to preserve existing `monkeypatch.setattr(MODULE, …)`
test patches.

**Tech-debt items to address in Wave C** (see `docs/05-planning/tech-debt.md`):
- TD-001 — 16 functions with `ctx: RunContext | None = None` (eliminated in C3
  once phases move into adapters and ctx becomes required at all call sites).
- TD-002 — `acc.iteration` redundant in `LoopAccumulator`; derivable from the
  loop counter. **RESOLVED (2026-05-25).**
- TD-003 — `_execute_stop` 4-branch copy-paste (lines 1770–1815); extract
  shared tail in C3. **RESOLVED (2026-05-25).**
- TD-004 — ~130-line routing-payload assembly block in `_run_loop` (lines
  2129–2265); extract as `_build_routing_payload(...)` in C2.
  **RESOLVED (2026-05-24).**
- TD-005 — `OutcomeFailed.reason` dispatched as raw strings in
  `outcome_to_exit_code` (core/outcome.py:69–74); type as
  `Literal[...]` in C3. **RESOLVED (2026-05-25).**

### Wave C — Collapse the Front-End & Retire Scaffolding

**C1. Command registry + slim `main()`** — **two PRs**

*Intent:* replace the if/elif ladder with a lookup table; extract each
subcommand to its own module; introduce `CommandOutcome`.

- **C1a — `CommandOutcome` ADT and subcommand extraction.**
  1. Create `code_review_loop/cli/` subpackage with `__init__.py` (empty for
     now).
  2. Add `code_review_loop/cli/outcome.py` with `CommandOutcome` as a sum type:
     ```python
     @dataclass(frozen=True)
     class CommandOk:
         exit_code: int = 0
     @dataclass(frozen=True)
     class CommandFailed:
         exit_code: int = 1
         message: str = ""
     CommandOutcome = CommandOk | CommandFailed
     ```
     Each variant has its own total `exit_code: int` field (no method needed).
     This keeps the pattern consistent with `RunOutcome` (C5) while remaining
     simple for Haiku to implement correctly.
  3. Create one module per subcommand under `cli/commands/`: `suppress.py`,
     `config.py`, `bundle.py`, `replay.py`, `doctor.py`, `resume.py`,
     `history.py`, `policy.py`, `triage.py`. Each receives the body of its
     `*_main` function from `cli.py`, with its `parse_*_args` helper included
     or imported from `cli/args.py` (created in C2; if C2 hasn't run yet,
     include the parser inline and note the todo).
  4. Each `*_main` function body moves to its module. Bare `return <int>`
     literals become `return CommandOk().exit_code` or
     `return CommandFailed(exit_code=N).exit_code`. (Doctor's code 6:
     `return CommandFailed(exit_code=6).exit_code`.) The old function in
     `cli.py` becomes a one-line re-export calling the new location.
  5. `resume_main` (lines 4103–4136) is the **special case**: it calls
     `run_loop` and reads the result, so it is also the consumer of the 11
     `_resume_*` deserialisers (lines 4382–4524). Move these into
     `cli/commands/resume.py` alongside `resume_main`. Do **not** fold them
     into `RunState.from_dict()` yet — that requires core changes and belongs
     in Wave E. Move them as-is; C1a's job is only relocation.
  - *Tests:* each command's existing tests stay green; a new
    `tests/test_cli_dispatch.py` drives `main()` with a fake first argv element
    and asserts the correct submodule is reached (monkeypatching its entry
    point, not `run_loop`).
  - *Burn-down line in PR body:* symbols retired / 18 remaining; call-sites
    remaining / 58.

- **C1b — Registry dispatch in `main()`.**
  1. Replace the if/elif ladder (lines 3641–3662) with a registry dict:
     ```python
     _SUBCOMMANDS: dict[str, Callable[[list[str]], int]] = {
         "suppress":          lambda a: commands.suppress.main(a),
         "bundle-bug-report": lambda a: commands.bundle.main(a),
         "replay":            lambda a: commands.replay.main(a),
         "resume":            lambda a: commands.resume.main(a),
         "doctor":            lambda a: commands.doctor.main(a),
         "preflight":         lambda a: commands.doctor.main(a),
         "config":            lambda a: commands.config.main(a),
         "history":           lambda a: commands.history.main(a),
         "policy":            lambda a: commands.policy.main(a),
         "triage":            lambda a: commands.triage.main(a),
         "ui":                lambda a: tui.main(a),
     }
     ```
     `main()` becomes: look up `raw_argv[0]` in the registry; if found, call
     and return; otherwise fall through to the loop path.
  2. Add a grep-gate CI check that asserts no bare `return <int>` integer
     literals survive in `cli/commands/*.py` (use `grep -rn 'return [0-9]\b'
     cli/commands/` and fail if non-empty).
  - *Tests:* `test_cli_dispatch.py` from C1a exercises the registry table.
  - *Exit:* adding a subcommand requires only: new `cli/commands/X.py` + one
    entry in `_SUBCOMMANDS`.
  - *Risk:* low — purely mechanical if C1a ran first.

**C2. Config-assembly + arg-parsing + `_run_loop` cleanup** — **two PRs**

*Intent:* isolate the remaining front-end logic; clean up `_run_loop` using
the tech-debt items identified during the simplify pass.

- **C2a — Extract config-assembly and arg-parsing.**
  1. Create `cli/args.py`. Move these functions from `cli.py` verbatim:
     `parse_args` (line 2795), `parse_suppress_args` (3733),
     `parse_config_args` (3123), `parse_history_args` (3192),
     `parse_doctor_args` (3206), `parse_bundle_bug_report_args` (3226),
     `parse_resume_args` (3239), `parse_policy_args` (4611),
     `parse_replay_args` (3961), `parse_triage_args` (4716). Leave
     one-line re-exports in `cli.py` so existing imports don't break.
  2. Create `cli/config_builder.py`. Move from `cli.py` verbatim:
     `build_loop_config` (3417), `profile_from_loop_config` (3555),
     `should_prompt_for_new_profile` (3287), `new_profile_from_args` (3293),
     `default_artifact_dir` (3299), `ensure_default_artifact_ignore` (3306),
     `resolve_timeout_seconds` (3363), `resolve_max_iterations` (3371),
     `parse_harness_bin_overrides` (3377), `resolve_profile_timeout_seconds`
     (3392), `profile_or_default` (3398), `pick` (3409). Leave re-exports.
  3. Move helper functions used exclusively by subcommands into their
     respective `cli/commands/` modules:
     - `_profile_config_owner_path`, `_editor_command`,
       `edit_profile_config` → `cli/commands/config.py`
     - `git_info_exclude_path`, `lexical_git_repo_root`,
       `_suppression_path_for_scope`, `_suppression_audit_path_for_scope`
       → `cli/commands/suppress.py` (or a shared `cli/git.py` if two commands
       share them)
     - `format_terminal_summary` (2717) → `cli/commands/` or a shared
       `cli/formatting.py`
  - *Tests:* config-assembly tests pass from new import paths; one explicit
    `from cli.config_builder import build_loop_config` import test.
  - *Exit:* `cli.py` contains only re-exports and the loop/phase code.

- **C2b — Clean up `_run_loop` (tech-debt TD-002 and TD-004).**
  1. **TD-004:** Extract the routing-payload assembly block at lines 2129–2265.
     Create a private function in `cli.py`:
     ```python
     def _build_routing_payload(
         resolved_route,
         triage_payload: dict[str, Any],
         run_id: str,
         iteration: int,
         remediation_input: str,
         config: LoopConfig,
     ) -> dict[str, Any]:
         ...
     ```
     Move the ~130-line inline block into it. The call site in `_run_loop`
     becomes: `routing_payload = _build_routing_payload(...)`.
  2. **TD-002:** Remove `iteration` from `LoopAccumulator` (defined in
     `core/engine.py:53`). Everywhere `acc.iteration` is read in `_run_loop`,
     replace with the loop variable `iteration`. Update the `replace(acc, …)`
     calls to remove `iteration=iteration`. Run `tests/test_engine_decide.py`
     to confirm no regressions.
  - *Tests:* A2 golden snapshots unchanged; `test_engine_decide.py` green.
  - *Exit:* `_run_loop` is shorter; `acc.iteration` no longer exists.
  - *Risk:* low — purely local changes with snapshot coverage.

**C3. Complete phase migrations + delete façade + split test monolith**
(C1 sunset, C2 zero) — **three PRs**

This is the highest-risk wave. The adapters currently delegate back to cli.py
via lazy imports ("until C3"). The primary job is completing that migration.
Run all PRs with the golden-master suite after each.

- **C3a — Move phase implementations into adapters.**
  The pattern is: copy the implementation from cli.py into the adapter class;
  delete the lazy `from code_review_loop.cli import run_X` line; the adapter
  now owns the code directly.

  Do one phase per commit. Suggested order (easiest → hardest):

  1. **`run_checks` → `adapters/checks.py`** (line 1229, ~46 lines). The
     `ChecksAdapter.execute` method currently calls `cli.run_checks`. Replace
     its body with the content of `run_checks`, adapting `(config, runner,
     iteration, ctx)` signature to `(self, request: ChecksRequest, ctx:
     RunContext)` using `self._config`, `ctx.runner`, `request.iteration`. Move
     helpers used only by `run_checks` (`adaptive_check_skip_reason`,
     `normalize_adaptive_check_result`, `is_pytest_command`,
     `has_non_python_project_surface`, `has_python_test_surface`,
     `iter_project_files`, `_format_check_failures`) into `adapters/checks.py`.
     Delete `cli.run_checks`; add re-export for any test that patches it.

  2. **`run_commit` → `adapters/commit.py`** (line 1443). Same pattern. Move
     `git_add_command_for_commit`, `git_worktree_status_command_for_commit`,
     `format_commit_hook_failure_for_remediation` alongside it.

  3. **`run_remediation` → `adapters/remediation.py`** (line 1079, ~48 lines).
     Move `build_remediation_command` (line 753) in.

  4. **`run_triage` → `adapters/triage.py`** (line 1128, ~100 lines). Move
     `build_triage_command` (line 787) in.

  5. **`run_codex_review` → `adapters/review.py`** (line 917, ~63 lines). Move
     `build_review_command` (line 740), `review_base_preflight_error` (981),
     `review_base_hint` (1015), `review_failed_to_run` (1059) alongside it.
     Move `run_git_preflight` (1033) to `adapters/git.py` (new file) since it
     is used by both review and resume.

  After all five: delete all lazy back-import lines from adapters. The circular
  import problem that required lazy imports is now gone — adapters no longer
  reach into cli.py.

  **TD-001 cleanup** (from tech-debt register): once phase implementations have
  moved, all 16 functions that carry `ctx: RunContext | None = None` can be
  updated to `ctx: RunContext` (required). Start with the adapters, then
  propagate inward. The `| None` defaults were transitional scaffolding; their
  removal is the signal that the migration is complete.

  - *Burn-down:* all five phase symbols (`run_codex_review`, `run_remediation`,
    `run_triage`, `run_checks`, `run_commit`) retired from the C2 symbol table.
  - *Tests:* `tests/test_harness_adapters.py` (exists) must pass; A2 golden
    masters must be byte-identical before and after each commit.

- **C3b — Migrate monkeypatch sites and delete run_loop facade.**
  This PR is the most work-intensive item in the entire programme.

  **Current counts (verify before starting):**
  - 47 `monkeypatch.setattr(MODULE, …)` sites in `tests/test_cli.py`
  - 6 in `tests/test_resume.py`
  - 5 in other test files
  - Total: 58 sites

  **Strategy per symbol class (from C2 table):**
  - `run_loop` (26 sites): these patch `MODULE.run_loop`. After this wave
    `run_loop` still lives in `cli.py` as the public entry point (the facade).
    Migrate each site to one of two patterns:
    a. **Preferred**: Build a `RunContext` with `FakeRunner` from
       `tests/support/fakes.py` and call `run_loop(config, runner=fake)` for
       real — no patch at all.
    b. **Fallback** (for complex integration tests where full execution is
       impractical): patch `core.engine.decide` or inject a fake adapter via
       `RunContext`. Do **not** patch `cli.run_loop` (the facade you are about
       to delete).
  - `write_summary`, `default_artifact_dir` (patched at the driver boundary):
    move tests to use real outputs or inject fakes via `RunContext`.
  - Terminal symbols (`refresh_terminal_title`, `terminal_columns`,
    `write_terminal_control_to_tty`): now in `adapters/terminal.py`; patch
    there or build tests that assert semantic progress events instead.
  - `run_git_preflight`, `lexical_git_repo_root`: now in `adapters/git.py`
    (C3a); patch there or replace with a fake `GitGateway`.
  - `TERMINAL_TITLE_REFRESH_SECONDS`, `_LAST_CANCELLATION_SIGNAL_AT`,
    `_RICH_UNAVAILABLE_WARNED`: become config fields on their adapter or are
    eliminated; tests that set them become adapter-construction tests.

  Once all 58 sites are migrated, delete `run_loop` and `_run_loop` from
  `cli.py`. `main()` calls `_run_loop` body inline (or extracts it as a private
  `_main_loop()`). The terminal context management (`terminal_recovery_context`,
  `terminal_title_context`, `progress_warning_context`, `rich_live_progress`)
  stays in the CLI driver — it is edge code, not core.

  - *Tests:* ratchet (`tests/test_monkeypatch_ratchet.py`) at 0. A2 golden
    masters unchanged.
  - *Risk:* **high** — this is the largest single commit in the programme.
    Do in its own dedicated PR. Use the approach: migrate 5–10 sites at a time,
    run the full suite after each batch, commit when green.

- **C3c — Tech-debt cleanup + split `tests/test_cli.py`.**
  1. **TD-003** (`_execute_stop` copy-paste, lines 1770–1815): extract the
     shared tail. Three returning branches (`OutcomeClear`, `OutcomeFindings`,
     `OutcomeUnknown`) share: `state.set_stopped_reason`, optional
     `set_pending_check_failures`, optional `set_latest_review_excerpt`,
     `write_summary`, `return summary`. Extract:
     ```python
     def _apply_stop_tail(state, outcome, excerpt, summary, config, clock, ctx):
         state.set_stopped_reason(outcome.reason)
         if getattr(outcome, 'check_failures', False):
             state.set_pending_check_failures(True)
         if excerpt:
             state.set_latest_review_excerpt(excerpt)
         write_summary(config, summary, clock=clock, ctx=ctx)
     ```
     Each returning branch calls `_apply_stop_tail` then returns. `OutcomeFailed`
     calls it then raises.
  2. **TD-005** (`OutcomeFailed.reason` stringly-typed, `core/outcome.py:69`):
     change `reason: str` to
     `reason: Literal["budget_ceiling_hit", "setup_failed", "cancelled", "loop_error"]`
     (add all values that appear at construction sites — grep
     `OutcomeFailed(reason=` to enumerate them). `outcome_to_exit_code` then
     gets static exhaustiveness from mypy if you add an
     `assert_never(outcome.reason)` fallthrough.
  3. **Split `tests/test_cli.py`** into modules mirroring the new layout:
     - `tests/test_cli_integration.py` — the golden-`main()` paths that must
       keep working end-to-end.
     - `tests/test_engine_loop.py` — loop-level tests that were previously
       reaching into `_run_loop` internals; rewrite to use `core.engine.decide`
       + fakes.
     - `tests/test_phase_review.py`, `test_phase_remediation.py`, etc. — phase
       adapter tests (move from `test_harness_adapters.py` or rewrite without
       monkeypatching).
     - `tests/test_<subcommand>.py` — one per subcommand, covering its
       `cli/commands/` module.
     Delete `tests/test_cli.py` once all its tests have been relocated and
     confirmed green.
  4. Promote import-linter + ratchet + grep-gate from advisory to required CI
     checks (add to `.github/workflows/ci.yml` if not already enforced).
  - *Exit:* no facade re-exports; ratchet at 0; `test_cli.py` deleted;
    `cli.py` contains only the thin driver (`main()`, entry-point shim, and
    any truly shared terminal utilities that adapters haven't absorbed yet).
  - *Risk:* medium — mostly additive; the C3b migration is the hard part.

### Wave D — Prove Leverage

**D1. Demonstrate the library/driver split**

*Intent:* prove the thesis with executable tests, not assertions. The engine
must demonstrably be drivable by a non-CLI caller.

*As-built state entering D1:* `core/` has no `argparse`, no terminal, no CLI
import (import-linter enforces this). `adapters/` are real implementations.
`cli.py` is the thin driver. Monkeypatch count is 0.

- **Changes:**
  1. Add `tests/support/headless.py`: a helper that builds a `RunContext` with
     `FakeClock`, `FakeRunIdentity`, `FakeRunner` (from `tests/support/fakes.py`),
     and fake adapters for all five phases, then calls
     `core.engine.run(state, ctx)` directly without `argparse`. This is the
     SDK-style driver that proves the engine is available to non-CLI callers.
  2. Add `tests/test_integration_headless.py`: uses `headless.py` to drive a
     full loop (review → triage → remediation → checks → commit) end-to-end
     with fakes, asserting the correct `RunOutcome` is returned. No `argparse`,
     no real subprocess, no terminal.
  3. Add `tests/test_leverage_subcommand.py`: add a no-op subcommand
     (`revrem noop`) by creating `cli/commands/noop.py` and one entry in
     `_SUBCOMMANDS`; test that `main(["noop"])` returns 0 and that the only
     files touched were `noop.py` + the registry.
  4. Add `tests/test_leverage_heuristic.py`: construct a `RunContext` with a
     fake `ReviewHarness` that returns `ReviewOutcome(status="findings", …)`;
     run the engine; assert the loop terminates with `OutcomeFindings`. This
     proves swapping a heuristic/harness requires no change to the core.

- *Tests:* (a)–(d) above; import-linter contract passes on `core/`;
  all A2 golden masters still hold.
- *Exit:* all ten Phase Exit Criteria demonstrably met (see below).
- *Risk:* low — mostly verification of work done in Waves A–C.

### Wave E — Sequel (named, not in this task's exit criteria)

**E1+. Events as the source of truth.** Make `RunState`/summary, the resume
payload, and run-history **projections (folds)** over `events.jsonl`,
deleting the parallel bookkeeping. Designed-for by A3/B3 (typed state, event
emission already on the stream) but staged so the core refactor is not
blocked. Carries its own spec when scheduled.

The 11 `_resume_*` helpers moved to `cli/commands/resume.py` in C1a are the
primary target: once `RunState.from_dict(summary)` can reconstruct all loop
state from the summary artifact, the bespoke deserialisers are deleted. The
symmetry between `RunState.to_dict()` (A3) and `RunState.from_dict()`
(E1) is the design goal.

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
