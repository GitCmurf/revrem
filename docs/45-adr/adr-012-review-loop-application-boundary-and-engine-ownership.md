---
document_id: REVREM-ADR-012
type: ADR
title: Review loop application boundary and engine ownership
status: Draft
version: '0.1'
last_updated: '2026-05-26'
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
- `ReviewLoopResult.to_dict()` is the explicit projection for command output,
  run history, and JSON serialization.
- CLI command modules must call the application API rather than reaching into
  the runner.

The runner is private application infrastructure, not a public API. The
side-effectful iteration executor lives in `code_review_loop.runner_shell`,
while subprocess execution lives in `code_review_loop.adapters.subprocess_runner`.
`code_review_loop.runner` owns run setup, preflight, cancellation, summary
finalization, and command-facing integration. Terminal title/control behavior
lives in `code_review_loop.adapters.terminal`; runner code must not own
terminal escape constants or `/dev/tty` writes.

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
            -> runner_shell.py
                 -> core/engine.py

adapters/* implement ProcessRunner, terminal/progress, Git/resume snapshots,
and the five phase harness ports consumed through RunContext.
```

### As-Built State at Wave D Exit

Measurements below are command-backed so reviewers can refresh them:

- `wc -l src/code_review_loop/cli/main.py src/code_review_loop/runner.py src/code_review_loop/runner_shell.py src/code_review_loop/core/engine.py`
  reports `98`, `775`, `594`, and `349` lines respectively.
- `rg -n '^\[\[tool\.importlinter\.contracts\]\]' pyproject.toml` reports
  9 import-linter contracts.
- `rg -n 'def test_' tests/test_application_headless_integration.py tests/test_engine_run.py tests/test_runner_shell_acceptance.py tests/test_wave_d_architecture.py`
  reports 16 Wave D acceptance/ratchet tests.
- `rg -n 'monkeypatch\.setattr\(MODULE,' tests` reports no production test
  call-sites; the only matches are the ratchet's own explanatory strings.

### How to verify the leverage claims

- **Application API:** `tests/test_application_headless_integration.py` runs
  clear, remediation, check-failure, setup-failure, budget, cancellation, and
  resume scenarios through `application.run_review_loop()` /
  `resume_review_loop()` without CLI parsing.
- **Engine purity:** `tests/test_engine_run.py` drives `core.engine.run()` with
  a recording executor and is guarded by the `Wave D engine acceptance tests
  stay core-only` import-linter contract.
- **Runner-shell ownership:** `tests/test_runner_shell_acceptance.py` calls
  `runner_shell.run_iterations()` directly; `tests/test_runner_engine_gate.py`
  and the `Runner shell must not import CLI or private runner` contract guard
  the production direction.
- **Command extensibility:** `src/code_review_loop/cli/commands/registry.py`
  owns concrete subcommand names; `tests/test_wave_d_architecture.py` fails if
  those names return to `cli/main.py`.
- **DocOps/gates:** `tests/test_import_contracts.py` runs import-linter inside
  pytest; `uv run --locked meminit check --format json` validates governed
  documents.
