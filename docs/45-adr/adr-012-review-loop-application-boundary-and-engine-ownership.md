---
document_id: REVREM-ADR-012
type: ADR
title: Review loop application boundary and engine ownership
status: Approved
version: '0.3'
last_updated: '2026-05-28'
owner: GitCmurf
docops_version: '2.0'
---

# ADR: Review loop application boundary and engine ownership

## Context

REVREM-TASK-003 split the original CLI God object into command modules,
phase adapters, core decision types, and a runner module. The implementation is
gate-clean, but a public architecture review should see a clear boundary
between command parsing and the executable review-loop application.

The current direction is:

- CLI and TUI code translate operator intent into typed configuration.
- `code_review_loop.application` is the public non-CLI application API.
- The application exposes a typed execution result and hides the private
  runner implementation from programmatic callers.
- `code_review_loop.core.engine` remains dependency-free and owns transition
  decisions through injected execution.
- Adapter modules own subprocess-facing phase behavior and terminal-state
  control.

No backward compatibility is required for old Python import seams created
during Wave C migration. CLI behavior and persisted artifact schemas remain
stable unless changed by a documented contract update.

## Content

Adopt `code_review_loop.application` as the only supported programmatic entry
point for executing and resuming review loops:

- `run_review_loop(config, process_runner=..., clock=..., identity=..., budget_state=..., phase_harnesses=..., terminal_ui=...)`
  executes one bounded loop and returns `ReviewLoopResult`.
- `resume_review_loop(run_dir, cwd=..., process_runner=..., clock=..., identity=..., phase_harnesses=..., terminal_ui=...)`
  resumes from an existing run directory and returns `ReviewLoopResult`.
- `ReviewLoopResult.outcome` is the typed terminal `RunOutcome`; string labels
  in summaries and exit codes are projections from that outcome.
- `ReviewLoopResult.to_dict()` is the explicit summary projection for command
  output, run history, and JSON serialization.
- CLI command modules must call the application API rather than reaching into
  the runner.

The runner is private application infrastructure, not a public API. The
side-effectful iteration executor lives in `code_review_loop.runner_shell`,
while subprocess execution lives in `code_review_loop.adapters.subprocess_runner`.
`code_review_loop.runner_setup` owns setup/context wiring and first-review
loading. `code_review_loop.routing_artifacts` owns v2 route resolution plus
routing-decision artifact validation and emission. `code_review_loop.runner`
owns the bounded session shell: preflight, cancellation, summary finalization,
and command-facing integration. Terminal title/control behavior lives in
`code_review_loop.adapters.terminal`; runner code must not own terminal escape
constants, `/dev/tty` writes, or production subprocess default selection.

The core engine remains dependency-free. It exposes state-machine events,
actions, a pure `decide()` transition function, and a reusable `run()` loop for
non-CLI executors. It must not import CLI, adapter, terminal, profile,
subprocess, or filesystem orchestration modules. The production runner drives
the loop through `core.engine.run()` with a runner-local executor; it must not
call `decide()` directly and must not simulate engine execution with one-step
capture bridges.

Architecture ratchets should enforce this story:

- production source must not retain Wave C migration language such as legacy
  shim or old monkeypatch-surface comments;
- CLI loop execution must route through `code_review_loop.application`;
- production loop execution must route through `core.engine.run()`;
- `code_review_loop.application` must not re-export the private runner alias;
- `code_review_loop.runner_shell` must not import `code_review_loop.runner`;
- `code_review_loop.runner` must not own terminal-control constants or
  `/dev/tty` access;
- `code_review_loop.runner` must not define subprocess runner or resume Git
  snapshot helpers;
- `code_review_loop.runner` must require injected process runners and must not
  import or lazily load `code_review_loop.adapters.subprocess_runner`;
- tests may reach only the runner-owned private surface through
  `runner_mod`; phase, diagnostic, terminal, subprocess, and summary helpers
  must be imported from their canonical modules;
- import-linter must continue proving core and adapter layer boundaries;
- tests that need phase internals should import canonical adapter homes, not
  runner compatibility surfaces.

## Wave D Appendix: leverage proof

Wave D proves the boundary with executable acceptance tests rather than a demo
command. The dependency shape at exit is:

```text
cli/main.py
  -> application.py
       -> runner.py
            -> runner_setup.py
            -> runner_shell.py
            -> routing_artifacts.py
                 -> core/engine.py

adapters/* implement ProcessRunner, terminal/progress, Git/resume snapshots,
and the five phase harness ports consumed through RunContext.
```

Legend: `->` marks injected collaborators or private implementation calls.
Typed terminal results flow back as `RunOutcome`; summaries and event artifacts
are projections written at the shell boundary, not engine inputs.

### As-Built State at Wave D Exit

Measurements below are command-backed so reviewers can refresh them:

- `wc -l src/code_review_loop/cli/main.py src/code_review_loop/runner.py src/code_review_loop/runner_setup.py src/code_review_loop/runner_shell.py src/code_review_loop/routing_artifacts.py src/code_review_loop/core/engine.py`
  reports `100`, `533`, `174`, `396`, `291`, and `349` lines respectively.
- `rg -n '^\[\[tool\.importlinter\.contracts\]\]' pyproject.toml` reports
  9 import-linter contracts.
- `rg -n 'def test_' tests/test_application_headless_integration.py tests/test_engine_run.py tests/test_runner_shell_acceptance.py tests/test_wave_d_architecture.py tests/test_outcome_exit_code.py tests/test_runner_engine_gate.py`
  reports 40 Wave D acceptance, outcome, and ratchet tests.
- `rg -n 'monkeypatch\.setattr\(MODULE,' tests` reports no production test
  call-sites; the only matches are the ratchet's own explanatory strings.

### How to verify the leverage claims

| Exit Criterion | Executable proof |
| --- | --- |
| #1 Core dependency-free | Import-linter contracts `Core must not import edge or adapter modules` and `Wave D engine acceptance tests stay core-only`; the latter also forbids common domain leaf modules. |
| #2 Engine drivable without CLI | `tests/test_engine_run.py` drives `core.engine.run()` with a recording executor and no CLI, runner, shell, adapter, TUI, or domain-leaf imports. |
| #3 Application drivable by non-CLI caller | `tests/test_application_headless_integration.py` runs clear, findings, unknown, setup-failure, budget, cancellation, and resume scenarios through `application.run_review_loop()` / `resume_review_loop()` with injected fakes. |
| #4 Add command / swap behavior through extension seams | `tests/test_wave_d_architecture.py` proves `cli/main.py` is closed to concrete subcommand names; headless tests inject alternate phase harnesses without editing CLI, runner, runner shell, or engine code; `tests/test_runner_engine_gate.py` prevents tests from using `runner` as a barrel for foreign helper owners. |
| #5 Monkeypatch facade gone | `tests/test_monkeypatch_ratchet.py` keeps `monkeypatch.setattr(MODULE, ...)` at zero production call-sites. |
| #6 Exits exhaustive | `tests/test_outcome_exit_code.py` reaches every `RunOutcome` variant and every `OutcomeFailed.reason`; CLI success/cancellation paths map from typed outcomes. |
| #7 No nondeterminism in core | `tests/test_determinism_gate.py` prevents raw time, random, subprocess, filesystem, and environment access in core modules. |
| #8 Dependency graph acyclic | `tests/test_import_contracts.py` runs all 9 import-linter contracts, including core, adapter, runner-shell, CLI/application, and Wave D headless isolation rules. |
| #9 Test monolith decomposed | `tests/test_cli.py` is a smoke-level compatibility shell; behavior now lives in focused command, runner, adapter, engine, and application modules. |
| #10 Machine contract unchanged or ledgered | `docs/05-planning/behaviour-ledger-task-003.md` records summary/status transitions, including setup failure as `final_status == "error"` with `stopped_reason == "setup_failed"`. |
