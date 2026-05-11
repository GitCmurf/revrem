---
document_id: REVREM-TEST-001
type: TEST
title: Utility verification strategy
status: Draft
version: '1.3'
last_updated: '2026-05-10'
owner: GitCmurf
docops_version: '2.0'
area: testing
description: Test and release gates for code-review-loop
keywords:
- pytest
- cli
- docops
---

> **Document ID:** REVREM-TEST-001
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 1.3
> **Last Updated:** 2026-05-10
> **Type:** TEST
> **Area:** testing
> **Description:** Test and release gates for code-review-loop

# TEST: Utility verification strategy

## Context

`code-review-loop` delegates review and remediation to subprocesses, so most
behavior can be tested deterministically with fake runners. The tests must
prove command construction, status detection, artifact routing, timeout
handling, and loop stop conditions without invoking real Codex sessions.

## Content

### Unit and behavior tests

The main test module is `tests/test_cli.py`. It covers:

- Codex review status detection for explicit statuses, finding markers, common
  clear-review prose, and ambiguous output.
- Review and remediation command construction, including model and reasoning
  flags.
- Optional read-only triage command construction and review -> triage ->
  remediation prompt handoff.
- Optional commit-after-remediation behavior, including post-check gating,
  deterministic git commit execution, read-only commit-message drafting, skipped
  commits when no staged diff exists, and failure-summary recording when git
  commit fails.
- Commit-message normalization to Conventional Commit syntax with the RevRem
  suffix, plus the explicit prompt-override path that disables that default
  subject policy.
- Phase-specific reasoning-effort CLI overrides for review, triage,
  remediation, and commit-message drafting.
- Positive and negative CLI boolean overrides for profile-controlled runtime
  and output flags.
- Default artifact-directory namespace under `.revrem/runs/`, including the
  local `.git/info/exclude` guardrail and non-Git `.revrem/.gitignore`
  fallback.
- Timeout diagnostics that preserve command, cwd, timeout, and partial child
  output.
- Timeout cleanup for subprocesses that spawn pipe-holding descendants, proving
  timeout handling kills the child process group instead of blocking forever
  while collecting stdout/stderr.
- Review-base preflight behavior for invalid Git topology, including a local
  `main` that has no merge base with the current branch while `origin/main`
  remains usable.
- `revrem doctor` CLI diagnostics for local setup failures before the first
  model invocation.
- No-op remediation close-down: when commit mode finds no staged changes after
  passing checks, the loop stops instead of spending another review iteration.
- Bounded loop behavior, including final review behavior and exit status.
- Check-command failure handling and prompt forwarding into the next
  remediation pass.
- Adaptive pytest handling for non-Python repositories: pytest commands are
  skipped or normalized only when Node/TypeScript project markers are present
  and no Python test surface is detected.
- Artifact naming for review, remediation, last-message, check, and compact
  terminal summary outputs.
- Timeout propagation to review, remediation, and check subprocesses.
- Status detection using only actionable review output, not noisy tool
  transcripts in captured stderr.
- Optional status-detection diagnostic artifacts.
- Unexpected-behavior summary warnings and bug-report artifacts for remaining
  unknown review classifications.
- Progress-log formatting and quiet mode.
- Local-time progress prefixes and optional Rich progress fallback behavior.
- Terminal-title progress updates, stdout-safety, Rich-mode `/dev/tty` routing
  so title refreshes do not pollute the live panel stream, and terminal cursor
  restoration on normal and interrupted exits.
- Profile selection, CLI-over-profile overrides, and `revrem config` command
  behavior, including interactive `config new` prompts and the explicit
  `--no-interactive` automation path. The default auto-detection path is
  covered for both TTY and non-TTY invocations.
- Run-history write/opt-out behavior and `revrem history list` output.
- Package version reporting through `revrem --version`.

`tests/test_profiles.py` covers TOML profile parsing, validation, precedence,
commit-message model defaults, user-profile writes/deletes/imports, and
reserved future harness handling.
`tests/test_run_history.py` covers shared JSONL history paths, record shape, and
newest-first reads.
`tests/test_harnesses.py` covers the reusable harness command-planning boundary:
Codex command construction is executable, while reserved future harnesses remain
valid profile syntax but not runnable adapters.
`tests/test_diagnostics.py` covers deterministic local setup diagnostics for
Git topology, commit-mode cleanliness, Codex executable discovery, artifact
directory writability, and configured check executables.
`tests/test_fingerprints.py` covers the shared finding fingerprint contract
with golden vectors and normalization invariants.
`tests/test_artifacts.py` covers canonical JSON serialization, Decimal money
encoding, NFC string normalization, atomic artifact writes, and run-directory
path-safety checks.
`tests/test_artifact_schema.py` validates JSON Schema draft 2020-12 schema
files and checks concrete diagnostics and generated run-summary payloads
against `diagnostics-v1.schema.json` and `summary-v1.schema.json`.
`tests/test_redaction.py` covers the built-in redaction defaults used by future
bug-report bundles, including poisoned fixtures for API keys, authorization
headers, private keys, local paths, usernames, and idempotence.
`tests/test_bug_bundle.py` covers deterministic redacted bug-report bundles,
manifest schema validation, default transcript exclusion, and raw-transcript
opt-in behavior.
`tests/test_progress.py` covers optional Rich renderer safety, including literal
handling for review text that contains Rich markup syntax and styling of the
phase/action and status columns, plus in-place Live panel updates.
`tests/test_packaging.py` covers console entry points and local distribution
scripts, including optional extras metadata.
`tests/test_tui.py` covers the dependency-gated `revrem ui` entry point without
requiring Textual in the default development environment, plus fake-Textual
launch smoke tests for the operator shell, dry-run launch action, and
CLI-backed profile lifecycle actions.
`tests/test_tui_state.py` covers dependency-free TUI view models for profile
discovery, run-history loading, harness metadata, pipeline phase summaries, and
profile command previews, launch plans, profile lifecycle command plans,
run-monitor artifact links, and the composed shell model used by the
interactive entry point.
`tests/test_fixtures.py` covers long-lived fixture infrastructure, including
the reference repository used by the post-launch foundation phase.

### Reference fixture repository

`tests/fixtures/reference-repo/` is the stable deliberately-flawed project used
by `REVREM-TASK-002` foundation work and future profile benchmarks. It is not
sample application code. It exists to give diagnostics, triage, suppression,
event, and expert-profile work a shared target.

The fixture currently seeds:

- a SQL injection in `src/reference_app/auth.py`,
- an unused import in `src/reference_app/auth.py`,
- broad exception handling in `src/reference_app/auth.py` and
  `src/reference_app/billing.py`,
- duplicated email-normalization helpers in `src/reference_app/billing.py`,
- nested-loop report generation in `src/reference_app/reporting.py`,
- missing public-function documentation and type annotations in
  `src/reference_app/docs.py`.

`tests/fixtures/reference-repo/EXPECTED_FINDINGS.md` is the source of truth for
the seeded findings. Any change to the fixture code must update that ledger and
the fixture-presence tests in the same PR. Fixture files may contain
deliberately poor code and can use file-level linter exclusions; production code
must not copy those exclusions.

### Local verification

Run:

```bash
python -m pytest -q
python -m code_review_loop --help
python -m code_review_loop --dry-run --quiet-progress --summary-format json
meminit doctor --format json
meminit check --format json
```

When optional dev tools are installed, also run:

```bash
ruff check .
mypy src
```

The convenience wrapper is:

```bash
./scripts/dev-check
```

### CI verification

The GitHub Actions workflow runs:

- editable package installation with dev extras, including Rich and Textual so
  optional progress/TUI paths are importable in CI,
- `pytest -q`,
- `ruff check .`,
- `mypy src`,
- `meminit check --format json`.

### Release gate

A release candidate should not be tagged unless:

- tests pass locally and in CI,
- `meminit check --format json` is green,
- `revrem --version` reports the intended package version,
- `REVREM-DEVEX-001` reflects current CLI flags and exit codes,
- `REVREM-ADR-001` remains accurate for distribution and skill guidance,
- `CHANGELOG.md` contains an `[Unreleased]` entry for user-visible changes,
- a dry run from a separate repository produces the expected artifact layout.
