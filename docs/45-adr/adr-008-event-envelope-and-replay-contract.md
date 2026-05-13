---
document_id: REVREM-ADR-008
type: ADR
title: Event Envelope And Replay Contract
status: Draft
version: '0.1'
last_updated: '2026-05-12'
owner: __TBD__
docops_version: '2.0'
area: architecture
description: Decision record for RevRem event envelopes, JSONL persistence, and
  offline replay.
keywords:
- events
- replay
- artifacts
- tui
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
- REVREM-PLAN-002
---

# ADR: Event Envelope And Replay Contract

## Context

PLAN-003 and TASK-002 require a replayable event stream so future TUI, report,
CI, archive, and dataset surfaces consume structured execution facts rather
than scraping terminal output or model transcripts.

The first F8 slice establishes the event contract before migrating every loop
phase. This lets downstream code validate envelopes, read truncated JSONL
safely, and render compact replay output without invoking a model or runner.

## Content

## Decision

RevRem events use a v1 JSON envelope:

- `schema_version`;
- `run_id`;
- gap-free per-run `seq`;
- UTC timestamp `ts`;
- `kind`;
- optional `phase`;
- optional `iteration`;
- object `payload`.

Events are persisted to `events.jsonl`, one JSON object per LF-terminated line.
Ordering is by `seq`, not timestamp. Readers reject sequence gaps because they
indicate corruption or accidental file concatenation. Readers tolerate a
truncated final line by returning all valid prior events and appending a
synthetic `failure` event with `payload.reason = "truncated_events_jsonl"`.

The initial event kinds are:

`phase_start`, `phase_output`, `phase_result`, `status_classification`,
`check_result`, `artifact_write`, `warning`, `failure`, `summary`,
`suppressed`, `cancellation`, `cost_charge`, and `cost_ceiling_hit`.

`revrem replay <run-dir>` reads `events.jsonl` and renders compact output
offline. Replay does not call a harness, runner, or model.

Event producers write through the `EventSink` protocol. The initial
implementations are:

- `InMemorySink` for tests and deterministic assertions;
- `JsonlSink` for durable run artifacts;
- `RendererSink` for asynchronous live renderer callbacks.

`RendererSink` intentionally decouples event production from terminal rendering:
it assigns the same gap-free sequence numbers as other sinks, queues events for
a renderer worker, drops queued renderer work rather than blocking the loop when
the renderer is saturated, and records renderer errors as sink diagnostics
instead of failing the model/check execution path. Durable replay remains backed
by `JsonlSink`; renderer drops are therefore an operator-display degradation,
not artifact loss.

TUI state derives run-monitor details from `events.jsonl` when the artifact is
available. It reads through the same tolerant replay reader, surfaces truncated
tails explicitly, and reports invalid event sequences as monitor diagnostics.
This keeps the optional TUI on the replay/event substrate rather than adding a
second transcript parser.

## Consequences

- Event schema compatibility becomes a public artifact contract.
- The TUI remains deferred until replay fixtures are green, preserving the
  single execution engine boundary from PLAN-002.
- Compact replay is deterministic because it renders from `seq` and payload,
  not wall-clock time.
- Live loop runs write `events.jsonl` through the same envelope used by replay
  fixtures, so complete runs are directly replayable.
