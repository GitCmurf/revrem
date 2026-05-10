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

### Changed

- README rewritten as the public project entry point.
- Local development gate expanded to include `git diff --check`.

### Security

- Added detect-secrets baseline enforcement, gitleaks launch-scan guidance, and
  GitHub security reporting instructions.
