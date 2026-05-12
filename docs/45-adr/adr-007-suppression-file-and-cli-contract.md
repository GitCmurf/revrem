---
document_id: REVREM-ADR-007
type: ADR
title: Suppression File And CLI Contract
status: Draft
version: '0.1'
last_updated: '2026-05-12'
owner: __TBD__
docops_version: '2.0'
area: architecture
description: Decision record for RevRem finding suppressions, audit logging, and
  structured-triage integration.
keywords:
- suppressions
- triage
- audit
- cli
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
- REVREM-ADR-003
- REVREM-ADR-006
---

# ADR: Suppression File And CLI Contract

## Context

TASK-002 F7 requires RevRem to support explicit, auditable dismissal of known
findings so repeated runs do not keep asking an operator to remediate a finding
they have already accepted. This matters most for structured triage because
triage entries already carry stable fingerprints and severity metadata.

Suppressions are powerful enough to hide remediation work, so the design must
avoid becoming an unreviewed bypass around real defects. The first production
slice therefore targets a narrow, inspectable contract:

- suppression entries are local files, not telemetry or a hosted service;
- repo-local suppressions are shareable and take precedence over user-local
  suppressions for the same fingerprint;
- every mutation writes an audit record;
- critical suppressions require an explicit override and short expiry;
- suppressed findings remain visible in structured artifacts.

## Content

## Decision

RevRem uses TOML for suppression files:

- repo scope: `.revrem/suppressions.toml`;
- user scope: `~/.config/revrem/suppressions.toml`.

Each entry records:

- `fingerprint`;
- `summary`;
- `rationale`;
- `created_at`;
- `created_by`;
- `scope`;
- `severity_at_suppression`;
- optional `expires_at`;
- `critical_override`.

Repo entries override user entries for the same fingerprint. Expired entries
are ignored by matching. The CLI exposes `revrem suppress add|list|remove|expire|check`.
`check` exits `0` when a fingerprint is currently suppressed and `2` when it
is not, making it usable from scripts and orchestrators.

Critical suppressions require `critical_override = true` and an expiry no more
than 30 days after creation. This keeps high-risk deferrals explicit and
time-bounded.

Every add, remove, and expiry operation appends JSONL to the matching audit
path:

- repo scope: `.revrem/suppressions.audit.jsonl`;
- user scope: `~/.config/revrem/suppressions.audit.jsonl`.

The audit record includes before/after state and the acting user. Raw audit
logs are local artifacts and may contain rationale text or user identifiers.
Bug-report bundles include only a count-by-action audit summary by default.
Raw audit logs require the same raw-transcript opt-in used for review
transcripts.

`revrem doctor` warns on expired entries and unsupported fingerprint versions
so stale suppressions do not fail silently. This is intentionally a warning,
not a blocking setup error, because suppressions should never be required for
normal loop execution.

Structured triage integration is deliberately conservative. When a structured
triage `confirmed_findings` entry matches an active suppression, RevRem moves
it to `suppressed_findings`, removes the fingerprint from
`implementation_order`, writes the updated `triage-N.json`, and skips
remediation if no unsuppressed findings remain and no `needs_more_info`
entries are left to resolve. The original review artifact still exists, and
the structured triage artifact keeps the suppressed finding visible with
suppression metadata.

## Consequences

- Repeated runs become less noisy without deleting evidence.
- Suppression safety is reviewable in normal code review when repo-local
  suppressions are committed.
- The CLI and file format are usable before the F8 event stream exists; F8 can
  later emit `suppressed` events from the same contract.
- Comment-preserving TOML editing is not guaranteed in the first slice. This
  is documented debt; the suppression file is machine-managed and audit-backed.
- Free-text review output is not suppressed in this slice because it lacks a
  reliable fingerprint contract. Operators should enable structured triage for
  suppression-aware runs.
