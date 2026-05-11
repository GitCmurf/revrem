---
document_id: REVREM-REF-001
type: REF
title: Artifact schema namespace
status: Draft
version: '0.1'
last_updated: '2026-05-11'
owner: __TBD__
docops_version: '2.0'
area: api
description: Machine-readable artifact schema namespace and stability guidance for
  RevRem JSON contracts
keywords:
- schema
- artifacts
- api
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
---

# REF: Artifact schema namespace

## Context

RevRem artifacts are becoming public contracts. The CLI, TUI, replay tools,
bug bundles, CI integrations, and external automation all need to read the same
JSON artifacts without scraping raw model transcripts.

This directory is the reference namespace for those machine-readable contracts.
Files in this directory are treated as API reference artifacts rather than
Meminit-governed project documents. JSON Schema files under
`docs/52-api/schemas/` are validated by tests rather than assigned Meminit
document IDs.

## Content

### Namespace

Schema files live under:

```text
docs/52-api/schemas/
```

Schema file names use:

```text
<artifact-name>-v<major>.schema.json
```

Stable `$id` values use:

```text
https://github.com/GitCmurf/revrem/schemas/<artifact-name>/v<major>
```

The URL is an identifier. It does not need to resolve over the network during
tests or local RevRem execution.

### Serialization Rules

Public JSON artifacts use the shared artifact helper in
`src/code_review_loop/artifacts.py`:

- UTF-8;
- LF endings with a final newline for pretty JSON files;
- `sort_keys=True`, `ensure_ascii=False`, and two-space indentation for
  human-readable artifacts;
- NFC-normalized strings;
- `Decimal` values serialized as JSON strings, especially for money;
- atomic write via temporary file plus `os.replace`;
- artifact paths constrained to the run directory.

### Stability Tiers

Schemas start as `Draft` until the owning task marks them as stable. After a
schema reaches v1:

- additive optional fields are minor-compatible;
- removed, renamed, or semantically changed fields require a new major schema;
- tests must validate fixture payloads against the current schema;
- migration notes belong in `CHANGELOG.md` and the owning ADR.

### Planned Schemas

The foundation phase introduces these contracts:

- `summary-v1.schema.json` for run summaries;
- `diagnostics-v1.schema.json` for doctor and failed-run diagnostics;
- `triage-v1.schema.json` for structured triage output;
- `events-v1.schema.json` for replayable event streams;
- `bug-bundle-v1.schema.json` for redacted issue-support bundles.
