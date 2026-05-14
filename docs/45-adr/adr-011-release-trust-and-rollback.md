---
document_id: REVREM-ADR-011
type: ADR
title: Release Trust And Rollback
status: Draft
version: '0.1'
last_updated: '2026-05-13'
owner: GitCmurf
docops_version: '2.0'
area: release
description: Decision record for RevRem Trusted Publishing, release provenance, dry-run
  publishing, and rollback policy.
keywords:
- release
- pypi
- provenance
- rollback
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
---

# ADR: Release Trust And Rollback

## Context

RevRem is moving from local source installs toward public package
distribution. A bad release can waste operator time, damage trust, or leave
users pinned to an unsafe version. The release path therefore needs the same
properties as the runtime loop: bounded automation, explicit artifacts,
machine-checkable evidence, and a clear recovery path.

`REVREM-TASK-002` requires public install smoke tests, TestPyPI release
validation, PyPI publishing without long-lived credentials, provenance
artifacts, and a rollback runbook. The repository already builds wheels in CI;
this ADR records the trust and rollback contract for publishing those artifacts.

## Content

## Decision

RevRem releases use GitHub Actions, PyPI Trusted Publishing, provenance
attestation, and an explicit rollback runbook.

The release workflow has two operating modes:

- `workflow_dispatch` dry-run mode builds, tests, validates, checksums,
  attests, signs, and uploads release artifacts for inspection without
  publishing to PyPI or creating a GitHub Release.
- tag mode publishes. `vX.Y.Z-rcN` tags publish to TestPyPI. `vX.Y.Z` tags
  publish to PyPI and create a GitHub Release.

Publishing uses PyPI Trusted Publishing via GitHub OIDC (`id-token: write`) and
the PyPA publish action. The project must not require long-lived PyPI API tokens
for the normal release path. If a temporary token fallback is ever used, it must
be documented as an incident-level exception with removal criteria.

Before any publish step, the workflow verifies that the pushed tag matches
`src/code_review_loop/__init__.py::__version__`. Final releases use exact
`vX.Y.Z` tags. Release candidates may use the human-readable `vX.Y.Z-rcN` tag
for the PEP 440 `X.Y.ZrcN` package version. A mismatch fails before upload.

Every release artifact set includes:

- sdist and wheel;
- `twine check` validation output from the workflow log;
- `SHA256SUMS`;
- CycloneDX SBOM;
- GitHub build-provenance attestations;
- Sigstore signatures/certificates from the workflow identity;
- a GitHub Release attachment for the same files on final tags.

Rollback is operational, not automatic. Maintainers decide whether to yank,
document a workaround, or cut a hotfix using `REVREM-RUNBOOK-001`.

## Rationale

- Trusted Publishing removes static package-index secrets from repository
  settings and aligns release authority with the GitHub workflow identity.
- TestPyPI release candidates exercise the same build and upload path before a
  public PyPI publish.
- Dry-run workflow dispatch lets maintainers inspect artifacts and provenance
  before creating a release tag.
- Tag/version validation prevents accidental releases where package metadata
  and Git history disagree.
- Checksums, attestations, signatures, and SBOMs give downstream users evidence
  to inspect without trusting README prose.
- Rollback steps belong in a runbook because yanking, superseding, and hotfixing
  involve human judgment about user impact.

## Consequences

- Repository maintainers must configure Trusted Publisher entries for the
  `Release` workflow in PyPI and TestPyPI before first publication.
- Release workflow changes must keep dry-run mode non-publishing by default.
- README install guidance may advertise PyPI installation only after the
  workflow has successfully published the project.
- Long-lived PyPI tokens are not part of the baseline architecture.
- The release runbook is part of the release contract and must be updated when
  workflow behavior changes.

## Validation

- `tests/test_packaging.py` asserts release workflow dry-run support, RC tag
  routing, PyPI/TestPyPI publish routing, tag/version validation, checksums,
  provenance attestation, and Sigstore signing.
- CI package smoke tests build sdist and wheel, run `twine check`, install the
  built wheel into a clean virtual environment, and exercise `revrem --version`,
  `revrem --help`, and `code-review-loop --version`.
- `REVREM-RUNBOOK-001` documents the manual Trusted Publisher setup and
  rollback commands.

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-05-13 | GitCmurf | Initial release trust and rollback decision |
