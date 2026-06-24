---
document_id: REVREM-PLAN-007
type: PLAN
title: v0.6.0 TUI live runs
status: Draft
version: '0.7'
last_updated: '2026-06-24'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Implementation plan for the deferred PLAN-005 T12 slice: let the Textual
  TUI launch, live-monitor, and cancel a real review loop and prove its artifacts are
  equivalent to a CLI run. Closes the final M5 execution surface from PLAN-003 and the
  open deferral in PLAN-002.'
keywords:
- tui
- v0.6.0
- live-runs
- t12
- cancellation
- textual-pilot
- m5
related_ids:
- REVREM-PLAN-005
- REVREM-PLAN-003
- REVREM-PLAN-002
- REVREM-PRD-001
- REVREM-DEVEX-001
- REVREM-TEST-001
- REVREM-ADR-008
- REVREM-ADR-009
- REVREM-ADR-012
---

> **Document ID:** REVREM-PLAN-007
> **Owner:** GitCmurf
> **Status:** Draft; implementation slice landed on `feat/tui-live-runs`
> **Type:** PLAN
> **Area:** planning
> **Description:** Implementation plan for the deferred PLAN-005 T12 slice — TUI
> live-run launch, monitoring, cancellation, and CLI-equivalent artifacts.

# PLAN: v0.6.0 TUI live runs

## Implementation Status

This plan has been implemented as the experimental v0.6.0 live-run slice:

- S0: `RevRemApp` is module-scope and the Textual Pilot smoke harness boots it.
- S1: `tui_run_controller.LiveRunController` starts a managed `revrem`
  subprocess with child-safe output flags and explicit artifact dirs.
- S2: the live Run Monitor reads child `events.jsonl` and uses the same
  `RunEventView` conversion path as replay/history.
- S3: `k` cancels an active child through process-group `SIGINT`, with
  escalation only for forced cleanup.
- S4: `tests/test_tui_cli_equivalence.py` proves direct CLI and
  TUI-controller-launched runs have equivalent stable artifacts for clear,
  findings, unknown, review-failure, setup-failure, check-failure, and
  cost-ceiling outcomes.
- Design polish: the first live-run UI now presents an operator console with a
  persistent status bar, profile/pipeline and monitor columns, contextual
  controls, inactive-cancel feedback, and a help panel.

## How To Read This Document

This is an engineering handover written so that an agentic coding orchestrator
(or a human assigning work) can execute the slice with little additional
context. Read in this order:

1. **Context** and **Where We Are** — the state of the TUI today and exactly
   why this is the next slice.
2. **Goals / Non-Goals** — what ships and what is explicitly out.
3. **Architecture Decisions (D-1, D-2)** — *read these before any code.* The
   deferred T12 sketch pre-committed to an in-process design; D-1 weighs that
   against a subprocess design (both can cancel cleanly) and settles the
   execution/event/cancel model, while D-2 settles the Pilot prerequisite. Every
   slice depends on these.
4. **Shared Contracts** — cross-cutting rules every slice must obey.
5. **Reference Facts For Implementers** — the real signatures and file paths
   this slice touches, verified against the v0.5.0 tree.
6. **Dependency Graph** and **Slices S0–S4** — ordered work packages with file
   paths, steps, acceptance criteria, tests, and docs.
7. **Traceability**, **Risks**, and **Release Gate** — how this ladders up and
   how we know it is done.

If a slice and the Shared Contracts disagree, **the contracts win**. If a slice
and an Architecture Decision disagree, **the decision wins**.

## Context

`REVREM-PLAN-005` shipped v0.5.0 as a full Tier 2 release on 2026-06-24. The
only intentionally deferred PLAN-005 task is **T12: TUI real runs**. This plan
turns that deferred slice into the v0.6.0 focus, closes the final M5 execution
surface from `REVREM-PLAN-003`, and resolves the long-standing deferral tracked
as `REVREM-DEBT-TUI-001` in `REVREM-PLAN-002`.

The current TUI is a profile/config shell. It renders Home, Profiles, Pipeline,
Run Monitor, and Controls views; it can launch **dry-runs** and config commands
by shelling out through a blocking `subprocess.run` (`tui.run_launch_plan`). The
Run Monitor today only **replays finished runs from history** — it does not yet
start, stream, or cancel a live run. v0.6.0 closes that gap.

## Where We Are (Baseline, 2026-06-24)

Verified against the v0.5.0 source tree:

- **Execution owner.** `code_review_loop.application.run_review_loop()` is the
  supported boundary; it delegates to `runner.run_loop()` and the
  dependency-free `core.engine` (`REVREM-ADR-012`). The TUI must not import or
  reimplement any of these.
- **The TUI already knows how to spawn a real run.**
  `tui_state.launch_plan(profile, dry_run=False)` returns a `LaunchPlan` whose
  `argv`/`shell_command` is the *real-run* command (mode `"run"`, no
  `--dry-run`). Today only the `dry_run=True` variant is wired to a button.
- **Event stream is the replay/stream substrate** (`REVREM-ADR-008`).
  `events.JsonlSink` writes `events.jsonl` append-only; `FLUSH_KINDS` flushes at
  `phase_result`, `failure`, `summary`, `cancellation`, and `cost_ceiling_hit`,
  so a *tailing* reader sees every phase boundary as it happens.
- **The monitor renderer already exists.** `tui_state.run_event_view(event)`
  converts `events.Event` → `RunEventView` (`seq, kind, phase, iteration,
  detail`). `run_event_views(record)` is the replay/history wrapper that resolves
  a finished-run record's `events.jsonl`, reads it, and applies that converter.
  The live monitor will reuse the same converter, either directly or through a
  small extracted event-list helper shared with replay.
- **Cancellation needs a `KeyboardInterrupt` on the run loop's own thread**
  (`REVREM-ADR-009`). `runner.run_loop` catches `KeyboardInterrupt` and calls
  `runner_finish.finish_cancelled`, which emits a `cancellation` event, writes
  the summary, and yields outcome `cancelled` → exit code **5**
  (`core.outcome.outcome_to_exit_code`). In the CLI that exception is manufactured
  by the `adapters/terminal.py` `SIGINT`/`SIGTERM` handler; the fake harness
  proves the *same* outcome from a plain `raise KeyboardInterrupt()` with no
  signal (`harnesses.py:584`). Critically, those signal handlers are installed by
  `terminal_recovery_context()` **only when `terminal_ui=True`**
  (`runner.py:67-76`); with `terminal_ui=False`, `run_loop` calls `_run_session`
  directly and never touches `signal.signal()` (which is main-thread-only). So a
  headless/worker-thread caller is *not* blocked by signal mechanics — it simply
  has to arrange for the interrupt to arise on the run thread by other means.
- **No Pilot harness exists.** Current TUI tests are `tests/test_tui.py` and
  `tests/test_tui_state.py`; neither uses Textual `Pilot`. The Textual app class
  `RevRemApp` is **function-local** (defined inside `tui.run_textual_app`), so it
  cannot be instantiated by a Pilot test yet. This is the prerequisite
  `REVREM-PLAN-002` flagged (item 3, "extract the app class to module scope")
  and never completed.

## Goals

- Let the TUI start a **real** run from the selected profile behind an explicit
  experimental action — reusing `launch_plan(profile, dry_run=False)`.
- Stream run progress into the Run Monitor **while the run is active**, reusing
  the existing `RunEventView` renderer.
- Support **cancellation** through the existing, tested signal-driven path so the
  run writes artifacts, emits `cancellation`, and exits `5`.
- Prove TUI-launched runs produce the **same** summary/artifact contract as CLI
  runs on fake-harness fixtures.

## Non-Goals

- **No second execution engine, runner fork, or TUI-local remediation logic.**
  The TUI drives a `revrem` *process*; it never imports `code_review_loop.cli`,
  `runner`, `core.engine`, or `application`, and never reimplements loop,
  artifact, or cancellation semantics. (Reaffirms the PLAN-005 /
  `REVREM-TASK-002` no-second-engine rule.)
- **No in-process worker-thread execution in v0.6.0.** In-process execution is
  *achievable* without any engine change (see **D-1**); it is deferred for
  isolation, coupling, and risk reasons appropriate to an experimental surface,
  not because it is impossible. Revisit per the Follow-On.
- **No application-boundary or schema change.** Because the chosen architecture
  consumes only the existing CLI surface and `events.jsonl`, this slice adds
  **zero** code under `core/`, `runner.py`, `runner_shell.py`,
  `runner_setup.py`, `runner_finish.py`, peer runner modules, or
  `application.py`. If a slice finds it "needs" to touch those, stop and re-open
  D-1.
- **No archive/export/watch daemon work** — that remains M9, after M5 closes.
- **No silent provider calls from the default TUI screen.** A live run is an
  explicit, confirmed operator action; the default Run Monitor stays replay-only.

## Architecture Decisions

### D-1 — Execution, event, and cancellation model

**Decision: drive a managed `revrem` run subprocess; stream the Run Monitor by
tailing `events.jsonl`; cancel by sending `SIGINT` to the run's process group.**

**Context.** The deferred T12 sketch assumed an *in-process* model: run
`application.run_review_loop(terminal_ui=False)` on a Textual worker thread and
feed widgets via an injected `events.RendererSink`. `REVREM-PLAN-002` (Approved)
nudges the same way ("through `application.run_review_loop()` or an equivalent
non-CLI application boundary"). **Both models are viable**; this decision chooses
the subprocess model for v0.6.0 and records exactly why.

**Both models can cancel cleanly — that is *not* the discriminator.**
Cancellation requires a `KeyboardInterrupt` raised on the run loop's own thread;
`run_loop` catches it → `finish_cancelled` → `cancellation` event + summary +
exit 5. In the CLI that exception is manufactured by the `terminal.py` signal
handler, but the fake harness produces the identical outcome from a plain
`raise KeyboardInterrupt()` with no signal at all (`harnesses.py:584`). So an
in-process worker *can* cancel without any engine change: inject a custom
`ProcessRunner` (the existing `run_review_loop(process_runner=...)` seam) whose
`cancel()` kills its active child, lets `communicate()` return, and then `raise`s
`KeyboardInterrupt` in its own `run()` — caught by `run_loop` on the worker
thread. No cross-thread exception injection (correctly impossible) is involved;
the thread raises in its own flow. And because `run_loop` installs signal
handlers *only* under `terminal_ui=True` (`runner.py:67-76`), the
`terminal_ui=False` worker path never calls main-thread-only `signal.signal()`,
so signal mechanics do not block it either. An earlier draft of this decision
claimed in-process cancellation was impossible without an engine change; that was
wrong and is corrected here.

**Why the subprocess model wins for v0.6.0.** Since both can cancel, the choice
turns on isolation, coupling, and risk for an *experimental* first slice:
1. **Cancellation reuses the tested path once the run loop is active.** The
   spawned child is an ordinary `revrem` run: the CLI calls
   `application.run_review_loop(config)` without overriding `terminal_ui`
   (`cli/main.py:89`), so it runs `terminal_ui=True` and installs the `terminal.py`
   `SIGINT` handler even with piped stdio. `killpg(SIGINT)` therefore exercises
   the same cancellation chain as terminal Ctrl-C → handler →
   `finish_cancelled` → exit 5. Crucially,
   correctness does **not** hinge on that handler: the
   `except KeyboardInterrupt → finish_cancelled` lives in `_run_session`
   (`runner.py:146,183`), which `run_loop` calls on *both* the `terminal_ui` True
   (`:86`) and False (`:68`) branches, and `SIGINT` raises `KeyboardInterrupt`
   under Python's default handler too. The controller still treats artifacts, not
   the numeric exit code alone, as proof of clean cancellation: a very early
   `SIGINT` before `_run_session` has created `events.jsonl`/`summary.json` can
   return exit 5 through the CLI's outer `KeyboardInterrupt` mapping without a
   cancellation summary. (This is also why SIGTERM/SIGKILL belong only in forced
   cleanup: RevRem's terminal handler may translate SIGTERM to
   `KeyboardInterrupt` while active, but under Python's default handler SIGTERM
   terminates instead. Either way, only child-written artifacts prove a clean
   RevRem cancellation.) There is no custom `ProcessRunner` and no
   `raise`-on-cancel logic to get right.
2. **Terminal/stdio isolation by construction.** The run is a separate process
   with captured pipes (as the dry-run launcher already does), so harness child
   stdout/stderr/`/dev/tty` writes cannot corrupt the TUI. In-process, every
   harness child's stdio would have to be captured, *and* the run would still
   share the Textual main thread's terminal.
3. **Smallest, boundary-clean change.** The TUI stays a pure process driver and
   never imports `application`/`runner`/`engine`; `import-linter` stays green with
   no new edges and no relaxed contract. In-process would pull `LoopConfig`
   construction, a custom `ProcessRunner`, and an `application` import into the
   TUI worker, and would require marshaling every `RendererSink` callback (which
   fires on the sink's daemon drain thread) onto the Textual thread via
   `app.call_from_thread()`.
4. **Live == replay.** `events.jsonl` is append-only and flushed at every phase
   boundary (`FLUSH_KINDS`); tailing it and passing parsed `Event` objects through
   `tui_state.run_event_view(event)` (or a shared event-list helper extracted
   from `run_event_views(record)`) is the *same* event-row render path the
   history monitor already uses — exactly the property the S4 equivalence gate
   asserts.
5. **In-process's latency edge is smaller than it looks.** A cooperative
   in-process cancel only takes effect at the next child-call boundary anyway,
   and the monitor is phase/iteration-grained either way (`RunEventView`'s
   shape), so the subprocess tail's phase-flush latency is comparable.

**Trade-off named explicitly.** This chooses the **CLI-subprocess boundary** over
`REVREM-PLAN-002`'s nudge toward the in-process `application.run_review_loop()`
boundary. The subprocess *is* `revrem` calling `application.run_review_loop`, so
the no-second-engine spirit holds — we are choosing *where the process boundary
sits*, trading marginally lower event latency for stdio isolation and a far
smaller, lower-risk change suited to an experimental surface. The in-process
boundary remains the better long-term home (see Follow-On). Should a future plan
adopt it, the seam is known: widen `RunSetup.event_sink` from `events.JsonlSink`
to the `EventSink` Protocol, add a fan-out sink (JsonlSink + RendererSink), and
thread an optional `event_sink`/`process_runner` through
`run_review_loop`→`run_loop`→`prepare_run`.

**Consequence — accepted limitation.** Live monitor granularity is
phase/iteration level (the granularity `RunEventView` already models), not
token-streaming. This matches the existing monitor and is sufficient for the
showcase. Document it as expected behavior, not a defect.

### D-2 — Pilot harness and module-scope app (prerequisite)

**Decision: extract `RevRemApp` to module scope and stand up a Textual `Pilot`
harness as Slice 0, before any live-run feature work.**

The later live-run slices' acceptance criteria require a Pilot test, and the app
class is currently function-local (`tui.run_textual_app`'s inner
`RevRemApp`), so it cannot be instantiated by `app.run_test()`. This is the
prerequisite `REVREM-PLAN-002` named and never delivered. Treating it as a
foundational slice (S0) — rather than folding it into S1 — keeps the refactor
reviewable in isolation and gives every later slice a working test substrate.
Textual `>=0.80` is already declared in the `tui` extra, so `Pilot` is available
with no new dependency.

## Shared Contracts

Every slice must obey these.

1. **Atomic unit of work.** Each slice is one PR carrying code + tests + docs +
   pasted local verification evidence. A slice is not "done" until
   `./scripts/dev-check`, `pre-commit run --all-files`, `meminit check --format
   json`, `git diff --check`, and `lint-imports` all pass.
2. **TUI stays a subprocess driver (architecture boundary).** New feature code
   lives under the TUI layer (`tui.py`, `tui_state.py`, a new
   `tui_run_controller.py`). The one acceptable non-TUI extraction is a tiny
   dependency-free run-directory path factory shared with CLI, if that is cleaner
   than local duplication. The TUI must not import `code_review_loop.cli`,
   `code_review_loop.runner`, `runner_shell`, `core.engine`, or `application`.
   `lint-imports` enforces the runner/core side today; add a TUI→CLI guard if
   needed so this boundary stays machine-checked. (`pyproject.toml`
   `[tool.importlinter]` already forbids `core` → `tui` and isolates the runner;
   this slice must not require relaxing any contract.)
3. **No second engine, ever.** The run is `revrem` invoked as a child process
   via the argv from `tui_state.launch_plan(profile, dry_run=False)`. The TUI
   never reconstructs loop, artifact, summary, history, or cancellation
   semantics.
4. **Resolve the run directory before launch.** Live streaming cannot wait until
   `summary.json` exists to discover artifacts. The controller computes the run
   directory *before* launch as `profile.output.artifact_dir` if the selected
   profile sets one, else a unique default-shaped directory, then passes that
   same lexical value as `--artifact-dir <dir>` and tails the corresponding path
   resolved relative to the child cwd. It computes but does **not** pre-create or
   write into that directory (Contract 8); the child creates and owns it. Note
   that passing `--artifact-dir` makes the child's `artifact_dir_is_default`
   `False` (`config_builder.py:736`), which shifts the pending-review
   `search_root` (`:427`) — harmless here because Contract 5 forces
   `--pending-review ignore`. After exit, reconcile the child's top-level
   `summary.artifact_dir` with the prelaunch value using the same relative-to-cwd
   resolution rule as `tui_state.resolve_record_path(...)`, and treat a mismatch
   as a failed setup/controller bug.
5. **Machine-friendly child invocation.** Live runs add `--no-tty` (force
   headless, no ANSI) and `--pending-review ignore` (explicitly suppress
   compatible-pending-review prompts). Do not rely on `--no-tty` for pending-review
   behavior: the CLI default is chosen from `stdin/stdout.isatty()`
   (`cli/main.py:129-135`), while `--no-tty` controls output rendering. Add
   `--summary-format json` as a stdout *diagnostics* nicety only: the controller
   derives all state from the on-disk `events.jsonl` and `summary.json`, never by
   parsing child stdout, so the stdout format is never a dependency. The
   controller drains stdout/stderr concurrently to bounded in-memory buffers (or
   controller diagnostics outside the child run directory) so a verbose child
   cannot block on a full pipe.
6. **Reuse the existing cancellation path.** Cancellation first sends `SIGINT`
   to the run process group (D-1). The TUI must not synthesize a `cancellation`
   event and must not write a summary itself. If a child ignores SIGINT past a
   bounded grace period, the controller may perform cleanup of the process group,
   but the UX must report that as forced cleanup rather than a clean RevRem
   cancellation unless the child's artifacts contain the real `cancellation`
   event and exit-code-5 summary.
7. **Stable exit codes (do not change).** Global CLI meanings stay fixed: `0`
   clear · `1` utility · `2` findings/unknown · `3` budget ceiling · `4`
   setup/resume precondition · `5` cancelled · `6` `doctor --strict` warnings.
   A live review-loop child is expected to produce only the run-loop codes
   `0`-`5`; `6` means the wrong subcommand path was launched, and `130` can only
   occur if the process is interrupted before the application exit wrapper owns a
   `RunOutcome`. The controller maps the child's exit code plus artifacts to UI
   state; it never redefines a code (`core.outcome.outcome_to_exit_code` and the
   subcommand outcomes are the sources of truth).
8. **Read-from-artifacts, never re-run.** The monitor derives run progress from
   the child's `events.jsonl` and final run state from `summary.json`. It never
   invokes a model, never touches the network, and never re-renders by
   recomputing run state. The TUI writes no files into the child run directory.
9. **Determinism in tests.** Pilot and equivalence tests must be hermetic:
   `REVREM_ALLOW_FAKE_HARNESS=1`, no real provider, no network. The equivalence
   comparator masks expected nondeterministic fields (timestamps, run ids,
   absolute paths, durations) before diffing.
10. **Docs move with code.** Update `REVREM-DEVEX-001` (experimental live-run
   workflow + cancel behavior + "replay/history is the stable default"), the
   v0.6.0 `CHANGELOG.md` entry, and note the closure in `REVREM-PLAN-002`.

## Reference Facts For Implementers

Concrete anchors, verified against the v0.5.0 tree, so no rediscovery is needed.
Every flag and symbol below was grep-confirmed in source (the child flags in
`cli/args.py`, the artifact-dir precedence in `cli/config_builder.py`,
`archive_existing_events` in `runner_setup.py`, the cancellation path in
`runner.py`/`adapters/terminal.py`); treat line numbers as v0.5.0 references that
may drift.

- **TUI modules:** `src/code_review_loop/tui.py` (Textual app; gated behind the
  `tui` extra, lazy optional imports), `src/code_review_loop/tui_state.py` (pure
  view/state builders — no Textual import). Views: Home, Profiles, Pipeline, Run
  Monitor, Controls.
- **Real-run argv (already built):**
  `tui_state.launch_plan(profile, dry_run=False) -> LaunchPlan` with fields
  `profile_name, mode("run"), argv, shell_command`. The existing blocking
  launcher is `tui.run_launch_plan(plan, *, cwd, capture_output=True)` and the
  entrypoint resolver is `tui.current_entrypoint_argv(argv)` — reuse the resolver,
  but replace the blocking `subprocess.run` with a managed non-blocking `Popen`
  for live runs.
- **Event model (`src/code_review_loop/events.py`):**
  `EVENTS_FILENAME = "events.jsonl"`; `read_events(path) -> (list[Event], bool)`
  (second tuple element = `truncated`); `Event` is a frozen dataclass
  (`run_id, seq, kind, phase, iteration, payload, ts, schema_version`);
  `FLUSH_KINDS = {phase_result, failure, summary, cancellation, cost_ceiling_hit}`;
  `compact_detail(event) -> str`.
- **Monitor renderer (`tui_state.py`):**
  `run_event_view(event) -> RunEventView`; `run_event_views(record) ->
  (tuple[RunEventView, ...], truncated, error)` resolves `record` to an
  `events.jsonl` path and applies `run_event_view` to each parsed event;
  `run_monitor_view(record) -> RunMonitorView`. `RunMonitorView.events` is a
  `tuple[RunEventView, ...]`.
- **Cancellation / exit codes:** the `except KeyboardInterrupt → finish_cancelled`
  is in `runner._run_session` (`runner.py:146,183`), which `run_loop` calls on
  **both** the `terminal_ui=True` (`:86`) and `terminal_ui=False` (`:68`)
  branches. `adapters/terminal.py`'s `terminal_recovery_context()` adds the
  `SIGINT`/`SIGTERM` handler only under `terminal_ui=True`; the CLI invokes
  `application.run_review_loop(config)` without overriding `terminal_ui`
  (`cli/main.py:89`), so a spawned `revrem` child runs `terminal_ui=True` and has
  it. `finish_cancelled` emits `cancellation`, writes the summary, and yields
  outcome `cancelled`; `core.outcome.outcome_to_exit_code` maps `cancelled` → `5`.
  `SIGINT` raises `KeyboardInterrupt` under Python's default handler too, so the
  catch fires even absent the custom handler. `SIGTERM` is different: the RevRem
  terminal handler also translates it to `KeyboardInterrupt` while installed, but
  Python's default handler terminates. That makes SIGTERM suitable only as
  escalation, with clean cancellation judged from artifacts rather than signal
  choice alone.
- **Artifact dir control + precedence:** the child resolves its run directory as
  `args.artifact_dir or profile.output.artifact_dir or default_artifact_dir()`
  (`cli/config_builder.py:425-426`), where `default_artifact_dir()` builds the
  normal `.revrem/runs/<timestamp>-<id>` path. So a controller-supplied
  `--artifact-dir` *overrides* a profile's `output.artifact_dir` — which is why
  the controller must resolve the profile value first (Contract 4) and pass that
  exact lexical value, not blindly generate a fresh one. If the value is
  relative, the controller tails `cwd / value`; reconcile the child's top-level
  `summary.artifact_dir` after applying the same `Path` normalization and
  relative-to-cwd resolution, not by raw string equality. The live controller must
  not import the CLI helper (Contract 2); either move that tiny path factory to a
  neutral module or duplicate the path shape locally with focused tests.
  Supplying `--artifact-dir` also sets `artifact_dir_is_default=False`
  (`:736`), changing the pending-review `search_root` (`:427`) — neutralized by
  `--pending-review ignore` (Contract 5). A completed run's `summary.json` carries
  the authoritative top-level `artifact_dir` (written by `core/state.py`); pass
  the directory for streaming, then reconcile it against that field after exit.
  *(Cross-reference the `artifact_dir` two-locations note: use the top-level
  field, not the nested `artifact_paths.artifact_dir`.)*
- **Fake harness for tests:** `REVREM_ALLOW_FAKE_HARNESS=1` enables scripted
  scenarios; `harnesses.py` includes a `cancellation` scenario that raises
  `KeyboardInterrupt`, and golden scenarios (`clear`, `findings`, `unknown`,
  `setup-failure`, `check-failure`, `cost-ceiling`) already used by PLAN-005
  fixtures under `tests/`. It does **not** currently provide a controllable
  long-running scenario suitable for TUI cancel-in-flight tests; S3 must add one
  or provide an equivalent subprocess fixture.
- **Event-file startup behavior:** `runner_setup.archive_existing_events`
  rotates a prior `events.jsonl` only when `events.first_run_id(path)` can read a
  run id. `events.JsonlSink` then opens the live file with `O_TRUNC | O_CREAT`
  (`events.py:_open_fresh_artifact`). Therefore stale events cannot contaminate
  the child's new stream after the sink opens, but a TUI tailer can still render
  an old explicit-artifact-dir file during the startup window before
  `prepare_run`. S2's prelaunch file identity/run-id guard exists for that window.
- **Textual `Pilot`:** available via `app.run_test()` once `RevRemApp` is at
  module scope (S0). `textual>=0.80` is declared in the `tui` extra.

## Dependency Graph

```text
S0 (app→module scope + Pilot harness)         [hard prerequisite]
 └─> S1 (managed run launcher + run controller/state machine)
       └─> S2 (live Run Monitor via events.jsonl tail)
             └─> S3 (cancellation via process-group SIGINT)
                   └─> S4 (CLI/TUI equivalence gate)
```

Slices are serial: S2 needs the running process and controller from S1; S3 needs
a live run to cancel; S4 compares a completed TUI run against a CLI run. S0
unblocks all of them. The release task (version bump, CHANGELOG, PLAN-002
closure) depends on S0–S4.

---

## Slice S0 — App to module scope + Pilot harness

**Goal.** Make the Textual app testable, with zero behavior change.

**Why first.** Every later slice's acceptance criteria require a Pilot test, and
the app class is currently function-local so `Pilot` cannot reach it (D-2).

**Files.**
- Edit: `src/code_review_loop/tui.py` — lift the inner `RevRemApp` to a
  module-scope class; keep `run_textual_app(...)` as the thin entrypoint that
  instantiates and runs it; preserve the lazy optional `textual` import guard so
  importing `tui` without the extra still fails gracefully.
- New: `tests/support/tui_pilot.py` — a helper exposing an
  `async def pilot_app(*, profile_name=None, fake_harness=True)` context manager
  that constructs `RevRemApp` and yields `(app, pilot)` via `app.run_test()`,
  with `REVREM_ALLOW_FAKE_HARNESS=1` set hermetically.
- New: `tests/test_tui_pilot_smoke.py`.

**Implementation steps.**
1. Move `class RevRemApp(app_base)` to module scope. Where it currently closes
   over `run_textual_app` locals (e.g. `selected_profile_name`, `model`), pass
   those in via `__init__` parameters / instance attributes instead of closure
   capture.
2. Keep all existing bindings and actions identical. This slice changes *no*
   user-visible behavior; it is a pure testability refactor.
3. Add the Pilot helper and a smoke test that boots the app, asserts the Home
   screen renders, and quits — establishing the harness.

**Acceptance.**
- `RevRemApp` is importable at module scope; `run_textual_app` still works
  unchanged for the real entrypoint.
- `tests/test_tui_pilot_smoke.py` boots the app via `app.run_test()` and asserts
  the Home view is present.
- `lint-imports` green; `tui_state` still imports no Textual.
- No change to existing `test_tui.py` / `test_tui_state.py` outcomes.

**Tests.** Pilot smoke test (boot → assert Home → quit).

**Docs.** None user-facing; note the refactor in the PR body.

**Cheap-model suitability:** High. Mechanical refactor with an obvious test.

---

## Slice S1 — Managed run launcher + run controller

**Goal.** Start a real run from the selected profile behind an explicit
experimental action, modeled by a small dependency-light state machine.

**Files.**
- New: `src/code_review_loop/tui_run_controller.py` — a Textual-free controller
  modeling run state: `idle → starting → running → {completed | cancelled |
  failed}`. It owns a managed `Popen` handle, the resolved run directory, and the
  child's final exit code → UI status mapping. **Must not import Textual** (so it
  is unit-testable without a UI) **and must not import the engine** (Contract 2).
- New: a managed launcher (in `tui.py` or the controller) that spawns the
  real-run argv with `subprocess.Popen(..., stdout=PIPE, stderr=PIPE, text=True,
  start_new_session=True)` so the run has its own process group (required for the
  S3 group-`SIGINT` cancel). Reuse `tui.current_entrypoint_argv`; never invoke
  through `shell=True`.
- Edit: `src/code_review_loop/tui.py` — add an explicit, confirmed
  `action_launch_run` (binding distinct from the existing `d` dry-run) that calls
  `launch_plan(profile, dry_run=False)`, hands the argv to the controller, and
  transitions the Run Monitor into the live state. Keep the dry-run action
  unchanged.

**Implementation steps.**
1. Define the state enum/dataclass and transitions in `tui_run_controller.py`,
   with a pure `classify_exit(code, artifacts) -> status` mapping aligned to
   Contract 7 (`0`→completed-clear, `2`→completed-findings/unknown,
   `3`→budget, `4`→setup-failed, `5`→cancelled only when artifacts prove the
   clean cancellation path, `6`→controller/setup error because live runs should
   not invoke `doctor`, `130`→interrupted-before-run-initialized when there is no
   summary, other→failed). Do **not** hard-code integers in the UI; keep them in
   one mapping table.
2. The launch action requires an explicit confirm (a modal or a two-key
   action) so a live provider run is never one stray keypress away — Non-Goals.
   Gate it behind an "experimental" label.
3. Resolve the run directory before launch (Contract 4). If the selected profile
   has an explicit `output.artifact_dir`, use that value; otherwise generate a
   unique default-shaped `.revrem/runs/<timestamp>-<id>` path without
   importing `code_review_loop.cli` (move the tiny factory to a neutral module if
   reuse is worth it). Append `--artifact-dir <dir>` to the argv so child and
   controller agree exactly. Preserve relative values in the child argv, but tail
   them relative to the child cwd. Compute the path only — do not pre-create or
   write into it; the child creates and owns the directory.
4. The child owns `events.jsonl`, `summary.json`, run history, and
   review/check/remediation artifacts. The TUI writes no files inside the child
   run directory; if full stdout/stderr capture is needed, put it in a separate
   controller diagnostics location and link to it from UI state only.
5. Add `--no-tty` and `--pending-review ignore` to the child argv for the
   experimental live-run path so the child runs headless and cannot block on a
   pending-review prompt (Contract 5; this prompt control is explicit because it
   is independent of `--no-tty`). Add `--summary-format json` only as a stdout
   diagnostics nicety. The on-disk `events.jsonl` (live) and `summary.json`
   (final) are the authoritative payloads; never parse child stdout.
6. Drain stdout and stderr concurrently while the child runs. Keep bounded
   in-memory excerpts for the UI and, if full streams are persisted, write them
   outside the child run directory.
7. After the child exits, read the top-level `artifact_dir` from `summary.json`
   when present and assert it resolves to the same path as the prelaunch value.
   If the child
   exits before writing a summary, surface the bounded stdout/stderr excerpts as
   setup failure context.
8. A setup failure (bad profile, missing base ref, non-zero exit before any
   artifacts) must land in the `failed` state with a user-facing message — never
   a raw Python traceback in the TUI.

**Acceptance.**
- Controller state-transition unit tests pass **without importing Textual**.
- `lint-imports` green; the controller imports neither `runner`/`engine` nor
  Textual.
- Triggering the launch action starts a child process, records a deterministic
  run directory, and moves the UI to `starting`/`running`; the existing dry-run
  path is unchanged.
- The launched argv includes `--artifact-dir`, `--summary-format json`,
  `--no-tty`, and `--pending-review ignore`, and stdout/stderr are drained
  without deadlocking.
- A unit test covers explicit profile `output.artifact_dir` precedence, default
  generated run-dir shape, and no import edge from the TUI controller to
  `code_review_loop.cli`.
- A failed setup yields a `failed` UI state with a readable message.

**Tests.** Controller state-machine units; a Pilot test that triggers the
confirmed launch with the fake harness and observes the `running` state.

**Docs.** Draft the "experimental live run" note for `REVREM-DEVEX-001` (finalize
in S3 once cancel lands).

**Cheap-model suitability:** Medium-High. The state machine is self-contained;
the subtlety is process-group setup, which S3 depends on.

---

## Slice S2 — Live Run Monitor via `events.jsonl` tail

**Goal.** Update the Run Monitor with live phase/iteration/status/artifact-dir
/checks/reviews/detail while the run is active, reusing the replay renderer.

**Files.**
- Edit: `src/code_review_loop/tui.py` — add a Textual interval/worker that, while
  a run is `running`, polls the child's `events.jsonl`, rebuilds the monitor by
  applying the same event-row renderer replay uses, and refreshes the Run Monitor
  widget.
- Edit: `src/code_review_loop/tui_state.py` — extract a thin
  `event_views_from_events(events) -> tuple[RunEventView, ...]` helper and have
  both live mode and existing `run_event_views(record)` use it. Do not duplicate
  event-detail formatting in `tui.py`.

**Implementation steps.**
1. Before launch, record whether `run_dir / events.EVENTS_FILENAME` already
   exists. If it does, record its stat identity (`st_ino` when available,
   `st_size`, `st_mtime_ns`) and `events.first_run_id(path)`. A default-generated
   run dir is brand-new and cannot contain stale events, so this guard applies
   **only** to the explicit-`output.artifact_dir` case. The child will rotate
   known-run event files and open the new sink with `O_TRUNC`, but until it reaches
   `prepare_run` the TUI must not render the old file's events as if they were
   this run's.
2. On each tick, call `events.read_events(prelaunch_run_dir /
   events.EVENTS_FILENAME)` only after the file has disappeared/reappeared, its
   stat identity has changed, or its first readable `run_id` differs from the
   prelaunch `run_id` (with launch-time `mtime` as a fallback signal, never the
   only proof). Then convert parsed events with `run_event_view(event)` or the
   extracted shared event-list helper. If the file does not exist yet, or still
   matches the prelaunch file identity/run id, render the controller's
   `starting`/`running` state and keep polling. Full re-read on a short interval
   is acceptable (events files are small). Note an optional incremental
   `seq`-based tail as a future optimization, not a requirement.
3. Render compact event detail with the existing `RunEventView` path. If the UI
   needs first-class current-phase, latest-review, latest-check, or elapsed-time
   fields beyond the event rows, add a narrow live view model in `tui_state.py`
   with tests instead of overloading `RunMonitorView` implicitly.
4. Because the child flushes at `FLUSH_KINDS`, the monitor advances at each phase
   boundary. When a `summary` (or `failure`/`cancellation`) event appears, stop
   tailing and transition the controller to its terminal state.
5. **Preserve replay-from-history behavior**: the live tail is an additional mode
   layered onto the existing monitor; selecting a historical run still renders
   from history exactly as before.

**Acceptance.**
- Existing replay-from-history monitor behavior is unchanged.
- Unit tests prove `RunEventView` rendering for `phase_start`/`phase_result`,
  `check_result`, `warning`, `cost_ceiling_hit`, `failure`, `cancellation`, and
  `summary` events through the shared converter/helper (most reuse existing
  `run_event_view` coverage; add any missing kinds).
- A stale pre-existing `events.jsonl` in an explicit artifact dir is not rendered
  during the new run's `starting` state, including the case where the stale file
  is malformed and has no readable first `run_id`.
- A Pilot test runs a fake live run and asserts the **visible** monitor updates
  across at least two event rows before cancellation.

**Tests.** Renderer units per event kind; Pilot live-update test.

**Docs.** Add a Run Monitor "live vs replay" subsection to `REVREM-DEVEX-001`.

**Cheap-model suitability:** Medium. Polling + reuse of an existing renderer; the
care is in stopping cleanly on the terminal event.

---

## Slice S3 — Cancellation via process-group SIGINT

**Goal.** Expose a Cancel action only while a live run is active, routed through
the existing signal-driven cancellation path (D-1, Contract 6).

**Files.**
- Edit: `src/code_review_loop/tui.py` / `tui_run_controller.py` — add a
  `cancel()` that sends `signal.SIGINT` to the run's process **group**
  (`os.killpg(os.getpgid(child.pid), signal.SIGINT)` on POSIX; guard for
  platforms without `killpg`). Expose the Cancel action/binding only in the
  `running` state.
- Edit: `src/code_review_loop/harnesses.py` or test support — add a deterministic
  cancel-in-flight fixture. The existing fake `cancellation` scenario raises
  immediately inside the adapter and is useful for runner semantics, but it does
  not leave a live subprocess for the TUI controller to cancel.

**Implementation steps.**
1. Because S1 started the child with `start_new_session=True`,
   `killpg(..., SIGINT)` reaches the run process, which should follow the CLI
   path (`terminal.py` handler → `finish_cancelled` → exit 5). Do **not** assume
   this reaches every nested harness child: `adapters/subprocess_runner.py`
   currently starts harness subprocesses with `start_new_session=True`, so a
   descendant may be in its own process group. Add tests that cover both "run
   process exits cleanly after SIGINT" and "no long-lived child remains after the
   bounded cleanup path."
2. Add a deterministic long-running fake run that emits at least one early event
   and then blocks until cancelled (for example a test-only fake harness scenario
   or a local helper process wired through `--harness-bin`). Do not rely on the
   current fake `cancellation` scenario alone; it does not exercise the TUI
   process-signal path.
3. After signaling, the controller waits for the child to exit, then reads the
   written `summary.json`/`cancellation` event and transitions to `cancelled`.
   The TUI never writes the summary or synthesizes the event itself.
4. If the process has not exited after a short, documented grace period, the
   controller escalates cleanup (`SIGTERM`/`SIGKILL` as needed) and reports
   `failed-forced-cleanup` unless the child's own summary/events prove a clean
   RevRem cancellation. SIGTERM may still be translated by RevRem's terminal
   handler while active, but escalation is operational hygiene, not a substitute
   for the exit-5 cancellation contract.
5. Cancel must restore terminal/cursor state and must not corrupt existing run
   history (the child owns history writes).

**Acceptance.**
- A Pilot test starts a fake long-running run, cancels it, and observes the
  `cancelled` UI state **plus** a written `summary.json` with the `cancellation`
  event and a `5` exit mapping.
- That Pilot test uses a fixture that actually leaves the child process running
  until the controller sends `SIGINT`; immediate fake `KeyboardInterrupt`
  scenarios are additional coverage, not a substitute.
- No orphan harness process remains in the subprocess-provider test harness,
  including the case where a nested child has its own session.
- Cancellation does not corrupt run history; replay of the cancelled run renders.

**Tests.** Pilot cancel test (start → cancel → assert cancelled state + artifacts
and no orphan); a unit test on the `killpg` signaling helper.

**Docs.** Finalize the `REVREM-DEVEX-001` live-run + cancel section, stating that
cancel uses the same Ctrl-C path as the CLI and yields exit 5.

**Cheap-model suitability:** Medium. The signaling is small; the orphan-reaping
assertion and process-group detail are the real care points.

---

## Slice S4 — CLI/TUI equivalence gate

**Goal.** Prove a TUI-launched run produces artifacts equivalent to the CLI path
on fake-harness fixtures.

**Files.**
- New: `tests/test_tui_cli_equivalence.py`.
- New: `tests/support/run_artifact_compare.py` — a small comparator that loads
  two run directories, masks nondeterministic fields, and asserts equality.

**Implementation steps.**
1. For each scenario (`clear`, `findings`, `unknown`, `review-failure`,
   `setup-failure`, `check-failure`, `cost-ceiling`), run the loop **once via a direct `revrem`
   subprocess** (the reference path — a plain CLI run, *not* an in-process
   `application.run_review_loop` call) and **once via the TUI controller path**
   against the same fake-harness inputs and the same profile. Give the two runs
   separate artifact directories with the same path shape (for example sibling
   `cli/<scenario>` and `tui/<scenario>` dirs) and invoke **both sides with the
   same flag set** (`--artifact-dir`, `--no-tty`, `--pending-review ignore`,
   `--summary-format json`). Do not reuse one artifact directory for both runs:
   the second run would archive/overwrite `events.jsonl` and poison the file-set
   comparison. Matching the flag set keeps the only meaningful difference under
   test to *who launches the process* — otherwise
   `artifact_dir_is_default`/`search_root` divergence (Reference Facts) makes the
   comparison apples-to-oranges.
2. Compare the **stable** fields of `summary.json` and the **file set** of the
   run directory (`summary.json`, `events.jsonl`, review artifacts, checks, final
   status). Mask expected nondeterministic fields per Contract 9 (timestamps, run
   ids, absolute paths, wall-clock durations) before diffing.
3. Assert final status and exit-code mapping match across both paths for every
   scenario.

**Acceptance.**
- Equivalence holds for all seven scenarios: compatible `summary.json`,
  `events.jsonl`, review/check artifacts, and final status.
- Pilot coverage includes clear, findings, unknown, setup failure, check
  failure, and cost-ceiling states.

**Tests.** The parametrized equivalence test above.

**Docs.** Record the equivalence gate in `REVREM-TEST-001`.

**Cheap-model suitability:** Medium. Mechanical once the comparator and fixtures
exist; reuses PLAN-005's fixture catalogue.

---

## Traceability

| Slice | PLAN-002 / PLAN-003 item | Theme | Property proven |
|---|---|---|---|
| S0 | PLAN-002 "extract app to module scope" | Craft | App is Pilot-testable |
| S1 | PLAN-003 M5 (TUI runs) | Autonomy | TUI starts a real run via the CLI surface |
| S2 | PLAN-003 M5; PLAN-002 "stream events into live widgets" | Autonomy, Craft | Live monitor reuses the replay renderer |
| S3 | PLAN-002 "explicit, tested cancellation" / `REVREM-ADR-009` | Trust | Cancel = existing exit-5 path, no orphans |
| S4 | PLAN-005 T12 metric "TUI-launched run == CLI run artifacts" | Trust, Craft | Artifact equivalence |

Completing S0–S4 closes `REVREM-DEBT-TUI-001` (PLAN-002) and the final M5
execution slice (PLAN-003).

## Risks & Mitigations

- **Harness child not in the run's process group.** If
  `subprocess_runner` opens a new session, group-`SIGINT` may miss it →
  potential orphan. *Mitigation:* S3 step 1 treats this as the current baseline,
  adds an explicit "no orphan" test, and requires bounded forced cleanup to be
  reported separately from clean exit-5 cancellation.
- **Live tail has no path before `summary.json`.** End-of-run summary discovery
  is too late for streaming. *Mitigation:* S1 resolves the run directory before
  launch and passes it with `--artifact-dir`; the summary is used only to
  reconcile the child's reported path after exit.
- **Explicit artifact dirs may contain stale events.** A profile-level
  `output.artifact_dir` can point at a directory from a previous run. *Mitigation:*
  S2 records prelaunch `events.jsonl` state and renders only the new/replaced
  event stream for the live run.
- **Child stdout/stderr deadlock.** A long run with captured pipes can block if
  nobody drains them. *Mitigation:* S1 drains both streams concurrently to
  bounded buffers or controller diagnostics outside the child run directory and
  tests a verbose fake child.
- **Controller artifacts contaminate equivalence.** TUI-owned stream captures in
  the child run directory would make S4 fail for the wrong reason. *Mitigation:*
  the TUI writes no files into the child run directory; any controller diagnostics
  live outside it or remain bounded in memory.
- **Fake cancellation does not prove TUI cancellation.** The current fake
  `cancellation` scenario raises immediately inside the harness adapter.
  *Mitigation:* S3 adds a deterministic cancel-in-flight subprocess fixture and
  uses immediate fake cancellation only as supplemental runner-semantics coverage.
- **Tail latency perceived as a hang.** Phase-granular updates mean quiet gaps
  during long phases. *Mitigation:* show an active-phase spinner/elapsed timer in
  `running` state; document phase-level granularity as expected (D-1 consequence).
- **Pilot flakiness around process timing.** *Mitigation:* use the fake harness
  with deterministic scripted scenarios; assert on artifacts/state, not wall-clock
  timing; bound waits.
- **Windows.** `os.killpg`/`start_new_session` are POSIX. *Mitigation:* guard the
  signaling helper and mark live-run cancel as POSIX-supported in v0.6.0; the TUI
  extra is already a Unix-first surface.

## Documentation

- `REVREM-DEVEX-001`: experimental live-run workflow, the Cancel behavior (same
  path as CLI Ctrl-C → exit 5), and the rule that replay/history remains the
  stable default.
- `REVREM-PLAN-002`: record that `REVREM-DEBT-TUI-001` is resolved by this plan.
- `CHANGELOG.md`: a v0.6.0 entry describing live TUI runs as **experimental**.
- `REVREM-TEST-001`: the new Pilot suite and the CLI/TUI equivalence gate.

## Release Gate

v0.6.0 is releasable when:
- `./scripts/dev-check`, `pre-commit run --all-files`, `meminit check --format
  json`, `git diff --check`, and `lint-imports` pass.
- The TUI live-run Pilot suite passes when the `tui` extra is installed.
- CLI/TUI equivalence (S4) passes against the fake-harness fixtures for all seven
  scenarios, including exact child exit-code agreement before artifact
  comparison.
- Cancellation (S3), cost-ceiling, and at least three failure states have
  automated coverage. The cancellation path must not block the Textual event
  loop, and quitting during an active run must cancel the managed child before
  exit.
- No new code was added under `core/`, `runner.py`, `runner_shell.py`,
  `runner_setup.py`, `runner_finish.py`, peer runner modules, or
  `application.py` (D-1 invariant), and no `import-linter` contract was relaxed.

## Follow-On After v0.6.0

- **In-process streaming (the PLAN-002 boundary, deferred from D-1):** an
  in-process worker + injected `ProcessRunner` + `RendererSink` (no engine change
  required — see D-1) can replace the subprocess tail behind the same controller
  API for lower-latency, token-level updates. Adopt it once the terminal-capture
  and thread-marshaling cost is justified by demand; the live-run UX is unchanged.
- **M9:** a separate governed plan for archive schema, privacy scrubber, dataset
  export, and only then the `revrem watch` daemon.
