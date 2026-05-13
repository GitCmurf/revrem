---
document_id: REVREM-ADR-010
type: ADR
title: Harness Capability Contract
status: Draft
version: '0.1'
last_updated: '2026-05-13'
owner: __TBD__
docops_version: '2.0'
area: architecture
description: Decision record for RevRem harness capability metadata and the
  fake-harness execution gate.
keywords:
- harnesses
- capabilities
- fake-harness
- adapters
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
---

# ADR: Harness Capability Contract

## Context

TASK-002 F10 requires an executable contract before RevRem adds real non-Codex
adapters. Without a formal capability surface, profile parsing, CLI diagnostics,
budget accounting, cancellation support, and future replay fixtures would each
need to infer backend behavior from names or terminal output.

## Content

## Decision

RevRem defines `HarnessCapabilities` as the v1 capability surface for model
backends. The schema is published as
`docs/52-api/schemas/harness-capabilities-v1.schema.json` and includes:

- review, remediation, triage, and commit-message support flags;
- non-interactive support;
- supported sandbox modes;
- timeout and cancellation support;
- structured-output support;
- cost reporting mode: `tokens`, `usd`, or `none`;
- supported model identifiers;
- `contract_version`.

Codex advertises the implemented local behavior today. It supports every loop
phase, timeout/cancellation via RevRem's subprocess wrapper, and no token/USD
cost reporting.

The `fake` harness is reserved for the F10 contract runner and is hidden unless
`REVREM_ALLOW_FAKE_HARNESS=1` is set. When enabled, its capabilities can be
validated and inspected, but command execution still raises until the scripted
fixture runner lands. Real secondary backends such as Claude, Gemini, opencode,
Kilo, OpenRouter, and HTTP remain reserved and non-executable.

## Consequences

- Future adapters must declare capabilities before they can execute.
- Budget enforcement can distinguish unsupported cost reporting from zero
  usage.
- Tests can validate the capability payload independently from live model
  availability.
- The fake harness gate prevents accidental production use while leaving a
  clear path for deterministic F10 fixtures.
