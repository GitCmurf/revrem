---
document_id: REVREM-TEST-001
type: TEST
title: Utility verification strategy
status: Draft
version: '0.1'
last_updated: '2026-04-30'
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
> **Version:** 0.1
> **Last Updated:** 2026-04-30
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
- Bounded loop behavior, including final review behavior and exit status.
- Check-command failure handling and prompt forwarding into the next
  remediation pass.
- Artifact naming for review, remediation, last-message, check, and compact
  terminal summary outputs.
- Timeout propagation to review, remediation, and check subprocesses.
- Status detection using only actionable review output, not noisy tool
  transcripts in captured stderr.
- Optional status-detection diagnostic artifacts.
- Progress-log formatting and quiet mode.
- Local-time progress prefixes and optional Rich progress fallback behavior.
- Terminal-title progress updates and stdout-safety.
- Profile selection, CLI-over-profile overrides, and `revrem config` command
  behavior.
- Run-history write/opt-out behavior and `revrem history list` output.

`tests/test_profiles.py` covers TOML profile parsing, validation, precedence,
user-profile writes/deletes/imports, and reserved future harness handling.
`tests/test_run_history.py` covers shared JSONL history paths, record shape, and
newest-first reads.
`tests/test_progress.py` covers optional Rich renderer safety, including literal
handling for review text that contains Rich markup syntax.
`tests/test_packaging.py` covers console entry points and local distribution
scripts.

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

- editable package installation with dev extras,
- `pytest -q`,
- `ruff check .`,
- `mypy src`,
- `meminit check --format json`.

### Release gate

A release candidate should not be tagged unless:

- tests pass locally and in CI,
- `meminit check --format json` is green,
- `REVREM-DEVEX-001` reflects current CLI flags and exit codes,
- `REVREM-ADR-001` remains accurate for distribution and skill guidance,
- a dry run from a separate repository produces the expected artifact layout.
