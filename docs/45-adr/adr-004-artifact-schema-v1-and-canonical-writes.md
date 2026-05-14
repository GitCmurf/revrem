---
document_id: REVREM-ADR-004
type: ADR
title: Artifact schema v1 and canonical writes
status: Approved
version: '0.1'
last_updated: '2026-05-11'
owner: __TBD__
docops_version: '2.0'
area: architecture
description: Decision record for RevRem artifact schema v1, canonical JSON, atomic
  writes, and schema stability
keywords:
- schema
- artifacts
- json
- api
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
---

# ADR: Artifact schema v1 and canonical writes

## Context

RevRem's early artifacts were useful to operators but not contractual. The CLI
wrote text transcripts and an ad hoc `summary.json`, while diagnostics, future
triage output, event streams, bug bundles, reports, CI comments, and the TUI
all needed stable machine-readable data.

`REVREM-PLAN-003` and `REVREM-TASK-002` make artifact stability a foundation
dependency. Later autonomy work must consume shared schemas instead of parsing
raw Codex transcripts or duplicating JSON conventions.

## Content

Status: Accepted.

RevRem establishes `docs/52-api/` as the API reference namespace for
machine-readable artifact contracts. JSON Schema files live under
`docs/52-api/schemas/` and use JSON Schema draft 2020-12.

The first v1 schema set is:

- `diagnostics-v1.schema.json`;
- `summary-v1.schema.json`;
- `triage-v1.schema.json`;
- `events-v1.schema.json`;
- `bug-bundle-v1.schema.json`;
- `harness-capabilities-v1.schema.json`;
- `suppressions-v1.schema.json`.

`diagnostics-v1` and `summary-v1` are concrete contracts validated against
generated payloads. The other v1 files reserve names and envelope shape until
their owning implementation tasks finalize the fields.

The first v1 schema set is copied into `docs/52-api/schemas/_history/`.
Compatibility tests assert that each current v1 schema has a matching baseline.
Future breaking schema edits must replace that baseline through a major-version
schema and changelog entry instead of silently changing v1.

RevRem uses `src/code_review_loop/artifacts.py` for public JSON artifact
writes. The helper owns:

- `schema_version` stamping;
- UTF-8 JSON with `ensure_ascii=False`, `sort_keys=True`, two-space
  indentation, LF line endings, and a final newline;
- NFC string normalization;
- `Decimal` serialization as JSON strings;
- atomic write via temporary file and `os.replace`;
- run-directory path safety, including traversal and symlink-escape
  rejection, with final artifact targets opened without following symlinks.

Schema compatibility rules:

- Additive optional fields are compatible within v1.
- Removed, renamed, or semantically changed fields require a new major schema
  and migration notes.
- Tests must validate representative payloads against the current schemas.
- Raw model transcripts remain text artifacts; public JSON artifacts may
  reference transcript paths or bounded excerpts but must not inline unbounded
  transcript content.

Consequences:

- Downstream consumers can build on schema-versioned artifacts rather than
  terminal output.
- JSON writing becomes stricter than the legacy `Path.write_text` path, so new
  public artifacts should use the shared helper from the start.
- `docs/52-api/` is excluded from Meminit document-placement enforcement
  because it contains machine-readable API artifacts as well as reference
  prose.
