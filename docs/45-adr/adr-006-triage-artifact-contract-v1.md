---
document_id: REVREM-ADR-006
type: ADR
title: Triage artifact contract v1
status: Accepted
version: '0.1'
last_updated: '2026-05-12'
owner: __TBD__
docops_version: '2.0'
area: architecture
description: Decision record for structured triage artifacts, invalid-output policy,
  and remediation handoff behavior
keywords:
- triage
- schema
- remediation
- artifacts
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
- REVREM-ADR-004
---

# ADR: Triage artifact contract v1

## Context

RevRem already supported an optional read-only triage phase, but the output was
plain text. That made it useful for human-readable handoff while leaving later
features such as suppressions, reports, replay, and benchmark fixtures without a
stable contract.

`REVREM-PLAN-003` makes triage a foundation for safe higher-autonomy workflows.
The triage step must improve remediation guidance without becoming a way to
hide review findings or discard original context.

## Content

Status: Accepted.

Structured triage output uses the packaged schema resource
`src/code_review_loop/schemas/triage-v1.schema.json` at runtime and keeps the
authoritative reference copy in `docs/52-api/schemas/triage-v1.schema.json`.
When a triage subprocess emits JSON, RevRem validates it, stamps envelope
fields, writes `triage-N.json`, and forwards a structured handoff to the
remediation phase.

The v1 artifact includes:

- `schema_version`;
- `run_id`;
- `source_review_artifact`;
- `prompt_version`;
- `confirmed_findings`;
- `rejected_findings`;
- `needs_more_info`;
- `implementation_order`;
- `verification_commands`;
- `parsing_warnings`.

The versioned prompt lives at
`src/code_review_loop/prompts/triage_v1.txt` and is packaged with the
distribution.

Invalid structured triage output fails safe:

- RevRem writes `diagnostics.json` with
  `revrem.triage.invalid_output`;
- the original review/check context remains available;
- default behavior is `triage.on_invalid = "continue"`, which ignores the
  invalid triage guidance and proceeds with the original review context;
- `triage.on_invalid = "stop"` is available for workflows that require strict
  structured triage before remediation.

Plain-text triage remains supported for compatibility and human-oriented
handoffs. It does not produce `triage-N.json`.

Consequences:

- Downstream features can consume structured triage artifacts without parsing
  raw model text.
- Invalid triage cannot silently suppress or hide original review findings.
- Suppression work can depend on the shared fingerprint field, but suppression
  enforcement remains out of this ADR.
