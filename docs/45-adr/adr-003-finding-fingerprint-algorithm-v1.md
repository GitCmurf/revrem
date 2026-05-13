---
document_id: REVREM-ADR-003
type: ADR
title: Finding fingerprint algorithm v1
status: Accepted
version: '0.1'
last_updated: '2026-05-10'
owner: __TBD__
docops_version: '2.0'
area: architecture
description: Stable v1 fingerprint algorithm for finding-shaped diagnostics, triage, suppressions, bug bundles, and event payloads
keywords:
- revrem
- fingerprints
- diagnostics
- triage
- suppressions
- schema
---

# ADR: Finding fingerprint algorithm v1

## Context

RevRem needs a stable identifier for the same finding across diagnostics,
triage, suppressions, bug bundles, reports, replay fixtures, and future event
streams. Ad hoc identifiers would make suppressions unreliable and would force
downstream consumers to parse model transcripts or file paths differently.

The algorithm must be deterministic across Linux and macOS. It must therefore
avoid filesystem-dependent case folding or path normalization beyond the
repository-relative POSIX spelling used by Git.

## Content

Status: Accepted.

RevRem uses `src/code_review_loop/fingerprints.py` as the single source of
truth for finding fingerprints. Version 1 emits values with an `f1:` prefix and
the first 16 hexadecimal characters of a SHA-256 hash.

The canonical tuple is:

1. normalized rule id, or `<none>`;
2. normalized repository-relative POSIX path;
3. normalized message stem: NFC-normalized, whitespace-collapsed, lower-case,
   first 160 characters;
4. normalized severity bucket: `info`, `low`, `medium`, `high`, or `critical`.

The tuple is joined with ASCII unit separator (`\x1f`) and hashed as UTF-8.

Consequences:

- Path spelling is intentionally part of the hash. A moved or renamed file
  produces a new fingerprint, and stale suppressions should expire naturally.
- Path case is preserved. RevRem does not lowercase paths on case-insensitive
  filesystems, because doing so would make fingerprints platform-dependent.
- Severity is part of the hash. An escalated issue does not inherit a
  lower-severity suppression.
- Future incompatible changes must use a new prefix such as `f2:` and document
  migration behavior for existing suppressions and fixtures.

Golden vectors in `tests/test_fingerprints.py` protect the contract.
