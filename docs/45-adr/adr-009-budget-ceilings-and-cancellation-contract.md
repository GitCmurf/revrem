---
document_id: REVREM-ADR-009
type: ADR
title: Budget Ceilings And Cancellation Contract
status: Draft
version: '0.1'
last_updated: '2026-05-13'
owner: __TBD__
docops_version: '2.0'
area: architecture
description: Decision record for RevRem budget ceilings, cost accounting
  placeholders, cancellation, and resume semantics.
keywords:
- budgets
- cancellation
- resume
- events
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
- REVREM-ADR-008
---

# ADR: Budget Ceilings And Cancellation Contract

## Context

PLAN-003 and TASK-002 require RevRem to be safe for hands-off use in hooks,
CI, and long local runs. Bounded model invocations are the core operational
guarantee: the loop must stop before starting additional model work when a
declared ceiling has already been reached, and it must preserve enough
structured artifacts for replay and diagnostics.

## Content

## Decision

RevRem represents budgets as explicit nullable ceilings:

- `max_wall_seconds`: total run wall-clock ceiling, distinct from per-phase
  subprocess timeouts;
- `max_tokens`: future cost-aware harness ceiling;
- `max_usd`: future cost-aware harness ceiling, serialized as a JSON string
  when set;
- `soft_warn_fraction`: warning threshold for configured ceilings.

The first F9 slice enforces wall-clock ceilings before model-invoking phases
and emits a structured `warning` event when the configured wall ceiling reaches
the soft warning fraction. If the ceiling is already hit before the next model
call, RevRem emits `cost_ceiling_hit`, writes `summary.json`, writes
`events.jsonl`, appends public `artifact_write` events, and exits through the
stable budget exit path.

Token and USD usage are represented as `null` until a harness reports them, and
then accumulated from `cost_charge` events. They are never silently treated as
`0` before the first reported charge, because unsupported accounting and zero
usage have different operational meanings. When accumulated token or USD usage
reaches a configured ceiling, RevRem emits `cost_ceiling_hit`, writes summary
and event artifacts, and stops before the next model call.

Cancellation is a controlled stop path. SIGINT/SIGTERM restore terminal state
and raise into the loop, where RevRem emits `cancellation`, writes
`summary.json`, writes `events.jsonl`, records public artifact paths, and exits
with code 5. A repeated SIGINT/SIGTERM within five seconds is marked as forced
cancellation, but it keeps the same best-effort artifact and exit-code path.
The subprocess wrapper already kills the active child process group when
unwinding from an interrupt, so cancellation does not leave the model/check
process running under normal local execution.

Resume remains part of this ADR's contract but is not complete in the first
implementation slices. The intended semantics remain:

- every new summary records `git_state` with `HEAD`, configured base ref,
  resolved base commit, merge base, and an availability flag;
- a second interrupt within the hard-stop window performs best-effort artifact
  flushing and exits with the same stable code;
- `revrem resume <run-dir>` may continue only from event/artifact states that
  prove completed phases do not need to be re-run.
- resume validates those preconditions and exits with code 4 for unsafe
  resumes; when checks pass, it rebuilds the loop config from `resume_config`,
  restores any persisted wall budget usage, starts from the latest review
  artifact as `review-initial.txt`, and does not re-run completed review
  phases.

## Consequences

- Budget checks happen at model boundaries, not during verification checks.
- Missing cost data is explicit in summaries and event payloads.
- Future harnesses must report token/USD charges as `cost_charge` events before
  token or USD ceilings can be enforced.
- Resume depends on the event stream contract from REVREM-ADR-008; it must not
  introduce a second execution engine or transcript parser.
