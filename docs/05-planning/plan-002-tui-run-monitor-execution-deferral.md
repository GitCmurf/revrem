---
document_id: REVREM-PLAN-002
type: PLAN
title: TUI run monitor execution deferral
status: Draft
version: '0.2'
last_updated: '2026-05-06'
owner: GitCmurf
docops_version: '2.0'
area: product
description: Technical debt register entry for deferring in-TUI RevRem loop execution
  to a later PR
keywords:
- tui
- technical-debt
- revrem
related_ids:
- REVREM-PRD-001
---

# PLAN: TUI run monitor execution deferral

## Context

`REVREM-PRD-001` originally identified two possible designs for a full Textual
Run Monitor:

- keep the TUI as a control panel that shells out to the normal `revrem` CLI;
- let the TUI execute the full review/remediation loop itself and stream events
  into live widgets.

The current `0.3.0` PR deliberately implements the safer control-panel model:
the TUI shows profiles, pipeline shape, recent run artifacts, and profile
lifecycle actions, while the existing CLI remains the only owner of loop
execution, subprocess management, artifacts, summaries, history writes,
terminal recovery, and exit-code policy.

That deferral is intentional technical debt, not an accidental omission. It
keeps the current PR small enough to review and preserves the known-good CLI
contracts while still leaving a clear path to richer in-TUI execution later.

## Content

### Debt Item

| Field | Value |
|---|---|
| Debt ID | `REVREM-DEBT-TUI-001` |
| Status | Deferred |
| Owner | GitCmurf |
| Area | product |
| Related PRD | `REVREM-PRD-001` |
| Current release boundary | `0.3.0` |

### Deferred Capability

Build a full Textual Run Monitor that can start a real RevRem run, receive
structured phase events, update live widgets, and surface final summary,
artifacts, warnings, and failure diagnostics without leaving the TUI.

### Why It Is Deferred

- The CLI already owns the critical operational contracts: bounded nested
  execution, artifact layout, summary writing, history append, adaptive checks,
  commit-after-remediation, terminal-title behavior, signal handling, and exit
  codes.
- Moving loop execution into Textual introduces a second runtime surface for
  subprocess lifecycle, cancellation, stdout/stderr routing, and terminal
  recovery.
- The current TUI is still useful without this feature because it makes profile
  discovery, command previews, recent-run artifact inspection, and profile
  lifecycle actions visible without weakening the CLI.
- Deferring this work keeps the current PR reviewable and reduces the risk of a
  UI feature regressing the watched-terminal automation path.

### Preferred Future Direction

Prefer an event-stream adapter over duplicating the loop:

1. Keep `run_loop()` as the single execution engine.
2. Add a typed progress/event interface that can feed both existing terminal
   progress renderers and Textual widgets.
3. Extract the Textual app class to module scope, preserving lazy optional
   imports, so future Textual Pilot tests and subclassing do not depend on the
   current function-local class.
4. Run the loop in an isolated worker context so the Textual app remains
   responsive and can cancel cleanly.
5. Preserve CLI artifact, summary, history, and exit-code semantics exactly.
6. Add Textual Pilot coverage for launch, cancellation, artifact-link
   navigation, failure summaries, and unknown-status warnings.

### Non-Goals For The Future Slice

- Reimplementing review/remediation logic inside widgets.
- Creating a daemon, web server, or persistent background process.
- Changing artifact paths, summary schema, or run-history schema solely for the
  TUI.
- Letting the TUI bypass CLI/profile validation.

### Acceptance Criteria

- A real TUI-launched run produces the same `summary.json`, artifact set,
  history record, and terminal status semantics as the equivalent CLI run.
- Cancellation is explicit, tested, and restores the terminal cursor/title.
- Review clear, findings, unknown, timeout, check-failure, triage-failure,
  remediation-failure, and commit-failure states are visible in the Run Monitor.
- Textual Pilot tests cover happy path and at least three failure/cancellation
  paths.
- `./scripts/dev-check`, `meminit check --format json`, and `git diff --check`
  pass.

### Revisit Trigger

Revisit this debt after the `0.3.0` PR has landed and the profile/TUI control
panel has been dogfooded from at least two non-`code-review-loop` repositories.
