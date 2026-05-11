# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning once public releases begin.

## [Unreleased]

### Added

- Public GitHub launch materials: README, contribution guidance, security
  policy, support policy, issue templates, pull request template, CODEOWNERS,
  NOTICE, CI hardening, Scorecard workflow, and release provenance/SBOM
  workflow.
- Reference fixture repository for the post-launch foundation phase, with
  expected seeded findings and regression coverage to keep future profile,
  diagnostics, triage, and event work aligned.
- `revrem doctor` setup diagnostics for validating Git base refs, artifact
  writability, Codex availability, and check executables before the first model
  call.
- Shared finding fingerprint module and ADR-backed v1 algorithm for future
  diagnostics, triage, suppressions, bug bundles, and event schemas.
- Artifact helper for canonical JSON serialization, atomic writes, and
  run-directory path-safety checks.
- Initial `docs/52-api/schemas/` JSON Schema namespace with concrete
  diagnostics validation and reserved v1 skeletons for summary, triage, events,
  and bug bundles.
- `summary.json` now carries the v1 artifact envelope fields and is validated
  against `summary-v1.schema.json`.
- Added `REVREM-ADR-004` for artifact schema v1, canonical JSON, atomic writes,
  and schema compatibility policy.
- Built-in redaction helpers for future bug-report bundles, covering common API
  keys, authorization headers, private keys, sensitive environment assignments,
  home paths, and usernames.

### Changed

- README rewritten as the public project entry point.
- Package metadata now uses `revrem` as the public distribution identity while
  retaining `code-review-loop` as a compatibility console command.
- CI now builds the `revrem` wheel, validates package metadata, and smoke-tests
  the installed wheel on Linux and macOS.
- Local development gate expanded to include `git diff --check`.

### Security

- Added detect-secrets baseline enforcement, gitleaks launch-scan guidance, and
  GitHub security reporting instructions.
