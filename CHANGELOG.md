# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning once public releases begin.

## [Unreleased]

### Added

- Public GitHub launch materials: README, contribution guidance, security
  policy, support policy, issue templates, pull request template, CODEOWNERS,
  NOTICE, CI hardening, Scorecard workflow, and release provenance/SBOM
  workflow.
- Release workflow dry-run controls, TestPyPI/PyPI Trusted Publishing routing,
  tag/version validation, SHA-256 checksum generation, Sigstore signing, and
  `REVREM-RUNBOOK-001` rollback guidance.
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
- Added golden artifact scenario fixtures for clear, findings, setup-failure,
  timeout, check-failure, and unknown-review runs.
- Added `REVREM-ADR-004` for artifact schema v1, canonical JSON, atomic writes,
  and schema compatibility policy.
- Built-in redaction helpers for bug-report bundles, covering common API keys,
  authorization headers, private keys, sensitive environment assignments, home
  paths, and usernames.
- `revrem bundle-bug-report` creates deterministic redacted support bundles
  with manifest schema validation and raw-transcript opt-in.
- Added `REVREM-ADR-005` for redaction defaults and bug-report bundle privacy
  policy.
- Structured triage v1 support: JSON triage output is schema-validated, written
  to `triage-N.json`, and forwarded to remediation with original review context;
  invalid structured triage writes diagnostics and fails safe.
- Added `REVREM-ADR-006` for structured triage artifacts and invalid-output
  remediation policy.
- Commit hook failures in `--commit-after-remediation` mode now default to a
  bounded remediation retry, with configurable `stop` and explicit `no-verify`
  policies.
- `revrem suppress add|list|remove|expire|check` manages explicit finding
  suppressions, with audit logs, critical-finding guardrails, and
  structured-triage integration.
- Added `REVREM-ADR-007` for the suppression file and CLI contract.
- Suppression files are schema-tested, `revrem doctor` now warns about stale
  suppression entries, and bug-report bundles include redacted suppression
  audit summaries by default.
- Added the event envelope model, JSONL event sink/reader, compact offline
  `revrem replay`, and `REVREM-ADR-008` for the event/replay contract.
- Loop verification checks now emit explicit `check_result` events with
  command, status, return code, and artifact metadata.
- Replay fixtures now cover clear and fully suppressed runs, and warning
  progress statuses map to first-class `warning` events.
- Loop failure paths now emit structured `failure` events with stable reason
  payloads before writing the final summary.
- Added an asynchronous `RendererSink` event adapter so live renderers can
  consume sequenced events without blocking model/check execution.
- Run-monitor TUI state now derives event summaries from `events.jsonl`,
  including truncated and invalid stream diagnostics.
- Run summaries now emit `artifact_write` events for public artifact paths so
  replay/report consumers can discover artifacts from the event stream.
- Added initial budget ceilings: `--max-wall-seconds`, `--max-tokens`,
  `--max-usd`, `--soft-warn-fraction`, profile `[budgets]` defaults,
  wall-clock soft warnings, and exit code `3` for pre-model-call ceiling hits.
- Ctrl-C/SIGTERM cancellation now emits `cancellation`, writes run artifacts,
  restores terminal display state, and exits with stable code `5`.
- Added the v1 harness capability contract, JSON Schema, Codex capability
  metadata, and an explicit `REVREM_ALLOW_FAKE_HARNESS=1` gate for the future
  deterministic fake harness.
- Added the gated fake harness runner and fixtures for clear review,
  findings/remediation, and structured triage contract tests without Codex.
- Added a fake-vs-Codex summary structural-equivalence regression for the
  clear-review fixture path.
- Fake harness fixtures now cover timeout, cancellation, and unsupported
  negative paths.
- Summaries now record resume-safety Git state: `HEAD`, base ref, base commit,
  merge base, and availability.
- Added `revrem resume <run-dir>` precondition validation with stable exit code
  `4` for unsafe resumes.
- `revrem resume` now continues from the latest review artifact after passing
  safety checks, rebuilding the loop from recorded `resume_config`.
- Harness-reported token and USD charges now emit `cost_charge`, accumulate in
  summary budgets, and enforce `--max-tokens` / `--max-usd` ceilings before the
  next model call.
- Replay fixture coverage now spans clear, remediated, rejected-finding,
  timeout, check-failure, cancellation, cost-ceiling, and suppressed scenarios.
- The fake harness now exposes deterministic token-charge fixtures so budget
  ceilings can be tested through the same `CommandResult` accounting path used
  by model harnesses.
- Doctor diagnostics now include stable `f1:` fingerprints derived from the
  shared fingerprint algorithm without embedding absolute worktree paths.
- Live CLI runs now execute the doctor diagnostics path before the first model
  call and fail with setup exit code `4` plus `diagnostics.json` when blocking
  preflight issues are found.
- Doctor diagnostics now warn on explicitly disabled profile timeouts and
  non-UTF-8 locales, and `scripts/dev-render-diagnostics` renders the
  source-derived diagnostic code table for docs updates.
- The release build backend is pinned to `setuptools==80.9.0` for reproducible
  package builds.
- Fake harness fixtures now cover partial remediation output that fails while
  preserving the remediation artifact.
- Package smoke CI now covers Linux and macOS on Python 3.11 and 3.12, and the
  packaging metadata exposes the optional `redaction` extra.
- Package smoke CI now selects a single built wheel and uses the workspace path
  for installed CLI checks instead of relying on directory depth.
- Schema v1 reference files now have `_history` baselines guarded by artifact
  schema tests.
- V1 artifact schemas now validate timestamp formats, summary collection item
  shapes, suppression timestamps, and suppressed-finding payload structure more
  tightly.
- Bug-report bundles now include sanitized profile/preflight snapshot artifacts
  when a run records them.
- Failed or timed-out structured triage commands now write
  `diagnostics-N.json` before the loop exits, keeping triage failures
  inspectable from machine-readable artifacts.
- Operator cancellation now writes `diagnostics.json` alongside `summary.json`
  and `events.jsonl`.
- Profiles now support `[suppressions] scope = "repo" | "user"` so teams can
  declare their expected suppression write policy alongside review settings.

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

## [0.3.2] - 2026-05-14

Release cut for the post-launch foundation work merged into `main`. This
release packages the public install smoke, diagnostics, artifact schemas,
fingerprints, suppressions, events, triage, budgets, and fake-harness
contracts that now back the stable foundation line.
