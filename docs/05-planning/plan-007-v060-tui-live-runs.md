---
document_id: REVREM-PLAN-007
type: PLAN
title: v0.6.0 TUI live runs
status: Draft
version: '0.1'
last_updated: '2026-06-24'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Implementation plan for deferred T12: Textual TUI live run launch, monitoring,
  cancellation, and CLI-equivalent artifacts.'
keywords:
- tui
- v0.6.0
- live-runs
- t12
related_ids:
- REVREM-PLAN-005
- REVREM-PLAN-003
---

# PLAN: v0.6.0 TUI live runs

## Context

`REVREM-PLAN-005` shipped v0.5.0 as a full Tier 2 release on 2026-06-24.
The only intentionally deferred PLAN-005 work is T12: Textual TUI live-run
launch, monitoring, cancellation, and CLI-equivalent artifacts. This plan turns
that deferred slice into the v0.6.0 focus and closes the remaining M5 execution
surface from `REVREM-PLAN-003`.

The current TUI is a profile/config shell. It renders Home, Profiles, Pipeline,
Run Monitor, and Controls views; it can launch dry-runs and config commands by
shelling out through `LaunchPlan`. It does not yet start real review loops. The
implementation must keep `application.run_review_loop` as the execution owner
and must not import or reimplement runner internals in the TUI.

## Content

## Goals

- Let the TUI start a real run from the selected profile behind an explicit
  experimental action.
- Stream run events into the Run Monitor view while the run is active.
- Support cancellation through the existing bounded cancellation path.
- Prove TUI-launched runs produce the same summary/artifact contract as CLI
  runs on fake-harness fixtures.

## Non-Goals

- No new execution engine, runner fork, or TUI-specific remediation logic.
- No archive/export/watch daemon work; that remains M9 after M5 is closed.
- No silent provider calls from the TUI default screen. Live runs must require
  an explicit operator action.

## Implementation Slices

### Slice 1 — TUI Run Controller

Add a small dependency-light controller module owned by the TUI layer that
models run state: idle, starting, running, completed, cancelled, and failed.
The controller builds the same `LoopConfig` path as the CLI for a selected
profile, then calls `application.run_review_loop` with `terminal_ui=False`.
Keep the existing dry-run subprocess action unchanged.

Acceptance:
- Unit tests cover state transitions without importing Textual.
- `lint-imports` remains green; the TUI layer still does not import runner or
  engine modules.
- A failed setup path produces a user-facing failed state rather than a Python
  traceback.

### Slice 2 — Event-Driven Run Monitor

Connect live events to the Run Monitor using `events.RendererSink` or a narrow
application callback adapter. Convert incoming events into the existing
`RunEventView` shape and update the active monitor with current phase,
iteration, status, artifact dir, latest checks/reviews, and compact detail.

Acceptance:
- Existing replay-from-history monitor behavior is preserved.
- Unit tests prove event rendering for phase start/result, checks, warnings,
  cost ceilings, failures, cancellations, and summary events.
- Textual Pilot test verifies a fake live run updates the visible monitor.

### Slice 3 — Cancellation

Expose a Cancel action only while a live run is active. Route cancellation
through the existing cancellation mechanism so the run writes artifacts, emits
`cancellation`, and maps to exit code `5`; do not terminate child processes
with TUI-local ad hoc logic.

Acceptance:
- Pilot test starts a fake long-running run, cancels it, and observes cancelled
  UI state plus a written summary.
- No orphan harness process remains in the fake-process test harness.
- Cancellation does not corrupt existing run history.

### Slice 4 — CLI/TUI Equivalence Gate

Create a fake-harness fixture that runs once via CLI/application path and once
via TUI controller path. Compare the stable summary fields and artifact file
set; ignore expected nondeterministic fields such as timestamps and run IDs.

Acceptance:
- Equivalence test proves both paths produce compatible `summary.json`,
  `events.jsonl`, review artifacts, checks, and final status.
- Pilot coverage includes clear, findings, unknown, setup failure, check
  failure, and cost-ceiling states.

## Documentation

- Update `REVREM-PLAN-002` to record that the TUI run deferral has landed.
- Update `REVREM-DEVEX-001` with the experimental live-run workflow, cancel
  behavior, and the rule that replay/history remains the stable default.
- Add a v0.6.0 changelog entry describing live TUI runs as experimental.

## Release Gate

v0.6.0 is releasable when:
- `./scripts/dev-check`, `pre-commit run --all-files`, `meminit check --format
  json`, `git diff --check`, and `lint-imports` pass.
- The TUI live-run Pilot suite passes when the `tui` extra is installed.
- CLI/TUI equivalence passes against the fake-harness fixture.
- Cancellation, cost ceiling, and at least three failure states have automated
  coverage.

## Follow-On After v0.6.0

After T12 lands, start a separate governed plan for M9: archive schema,
privacy scrubber, dataset export, and only then the `revrem watch` daemon.
