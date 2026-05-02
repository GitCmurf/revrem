---
document_id: REVREM-DEVEX-001
type: DEVEX
title: Using code-review-loop
status: Draft
version: '0.2'
last_updated: '2026-05-01'
owner: GitCmurf
docops_version: '2.0'
area: devex
description: Operator guide for the code-review-loop utility
keywords:
- code-review-loop
- codex
- devex
---

> **Document ID:** REVREM-DEVEX-001
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 0.2
> **Last Updated:** 2026-05-01
> **Type:** DEVEX
> **Area:** devex
> **Description:** Operator guide for the code-review-loop utility

# DEVEX: Using code-review-loop

## Context

`revrem` / `code-review-loop` is a local Linux CLI for running a bounded Codex review,
remediation, and re-review workflow against the current git checkout. It exists
because copying a repo-local script into every project creates drift, makes
tests harder to share, and hides operator guidance in the wrong repository.

The command assumes:

- `codex` is installed and authenticated for the operator.
- The current directory is the repository under review.
- The repository has a meaningful base branch, usually `main`.
- The operator has reviewed the worktree and is comfortable allowing `codex
  exec` to write within the workspace sandbox.
- Verification commands are safe to run repeatedly.

`revrem` and `code-review-loop` currently invoke the same CLI. Prefer `revrem`
for interactive human use and keep `code-review-loop` for existing scripts,
automation, and backwards-compatible documentation.

## Content

### Install for local development

From this repository:

```bash
./scripts/install-dev
```

This creates or updates `./.venv` as an editable install. Use it for changes in
this repository:

```bash
./.venv/bin/code-review-loop --dry-run --quiet-progress
./.venv/bin/revrem --dry-run --quiet-progress
```

### Promote a stable local version

Other repositories should use a promoted stable install, not the editable
development environment in this checkout:

```bash
./scripts/promote-stable
```

The promotion script runs `./scripts/dev-check` unless
`REVREM_SKIP_CHECKS=1` is set, copies a source snapshot under
`~/.local/share/revrem/releases/`, creates a stable interpreter at
`~/.local/share/revrem/stable-venv`, and updates:

```text
~/.local/bin/code-review-loop
~/.local/bin/revrem
```

Override paths only when needed:

```bash
REVREM_STABLE_HOME=~/tools/revrem \
REVREM_BIN_DIR=~/.local/bin \
./scripts/promote-stable
```

This creates a deliberate boundary: active edits are tested through
`./.venv/bin/...`; other repos consume only the last promoted version on
`PATH`.

### Recommended final PR command

Run from the target repository, not from the `code-review-loop` repository.
Use the promoted stable command for normal PR-readiness checks:

```bash
revrem \
  --base main \
  --max-iterations 2 \
  --review-model gpt-5.5 \
  --remediation-model gpt-5.4-mini \
  --reasoning-effort medium \
  --timeout-seconds 1800 \
  --summary-format text \
  --debug-status-detection \
  --terminal-title \
  --check "pytest -q" \
  --check "git diff --check"
```

Use `code-review-loop` with the same flags when preserving an existing script
or command history matters.

Use `--summary-format text` for watched terminal runs. Use `json` or `both`
only when the stdout JSON is being captured by another tool; `both` intentionally
prints the full JSON summary after the human-readable summary.

Use repository-specific checks. For Meminit-backed repositories, include:

```bash
--check "meminit check --format json"
```

For repositories that need a virtualenv-local checker, pass the concrete path:

```bash
--check "./.venv/bin/pytest -q"
--check "./.venv/bin/meminit check --format json"
```

### Continuation after findings

The loop writes artifacts under `tmp/code-review-loop/<timestamp>/` by default.
If a capped run ends with findings, continue from the final review artifact:

```bash
revrem \
  --base main \
  --max-iterations 2 \
  --initial-review-file tmp/code-review-loop/<timestamp>/review-final.txt \
  --check "pytest -q"
```

Use `--initial-review-file latest` only when the default artifact directory is
being used and the latest final review is definitely the artifact to continue.

### Profile-based usage

Profiles live in `~/.config/revrem/profiles.toml`. Project-local overrides live
in `.revrem.toml` in the target repository. A minimal final-PR profile:

```toml
[profiles.final-pr]
description = "Full PR readiness check"

[profiles.final-pr.pipeline]
base = "main"
max_iterations = 2
checks = ["pytest -q", "git diff --check"]

[profiles.final-pr.review]
model = "gpt-5.5"
reasoning_effort = "medium"
timeout_seconds = 1800

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"

[profiles.final-pr.output]
summary_format = "text"
debug_status_detection = true
terminal_title = true
```

Run it from the target repository:

```bash
revrem --profile final-pr
```

CLI flags override profile values, so this is valid:

```bash
revrem --profile final-pr --base release/1.2 --check "pytest -q tests/smoke"
```

Profile management commands:

```bash
revrem config list
revrem config show final-pr
revrem config new final-pr --description "Full PR readiness check"
revrem config export final-pr
revrem config import profiles.toml
revrem config doctor --profile final-pr --format json
```

Profiles reserve `review.harness`, `triage.harness`, and
`remediation.harness` for future headless adapters such as `claude`, `gemini`,
`opencode`, and `kilo`. The current executable loop supports only Codex; using
another harness in a resolved run fails before starting subprocesses. Triage is
also parsed and validated as profile syntax but is not executed yet.

### Current CLI boundary

Rich progress and `revrem ui` remain planned in `REVREM-PRD-001`; they are not
available in the current CLI.

### Exit codes

- `0`: the loop ended clear.
- `1`: the utility itself failed, for example invalid arguments or a failed
  subprocess invocation.
- `2`: the utility completed but the bounded loop still has findings or pending
  check failures.

### Operator guidance

- Prefer a watched terminal for long runs.
- Keep `--max-iterations` small. Two remediation passes is the default safe
  posture; raise it only when the scope and verification budget justify it.
- Use a bounded `--timeout-seconds` value for slow review models. `0` disables
  subprocess timeouts and should only be used when an operator is ready to
  interrupt manually.
- Keep checks deterministic and focused on PR readiness. Expensive full-suite
  checks are useful for a final pass, but narrow checks are better while the
  loop is still actively remediating.
- Inspect the working tree after each non-clear run before launching another
  remediation pass.
- Use `--debug-status-detection` when a run appears to keep remediating after
  the review text looks clear. The flag writes `*-status.json` files next to
  review artifacts and logs the compact reason for each clear/findings/unknown
  classification.
- Use `--terminal-title` in a watched terminal to update the window/tab title as
  the loop moves between review and remediation phases, for example
  `rev 1/2 RevRem` and `rem 1/2 RevRem`. The tool uses terminal title-stack
  escape sequences to restore the previous title on exit where the terminal
  supports them, and emits both common window-title escape forms for broader
  terminal compatibility. Terminals that ignore those sequences will still run
  normally.

### Development checks

Ruff is part of the required development gate. Install the project with dev
extras and run:

```bash
./scripts/dev-check
```

The wrapper runs tests, `ruff check .`, `mypy src`, and DocOps checks when
`meminit` is available.

### Related documents

- `REVREM-ADR-001` records why this is a Python CLI with companion skill
  guidance rather than a copied script or skill-only implementation.
- `REVREM-PRD-001` defines the profile, progress, and TUI milestones.
- `REVREM-TEST-001` defines the verification gates for this utility.

## Version History

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.3 | 2026-05-02 | Codex | Added profile-based usage, config commands, and current harness/triage boundary |
| 0.2 | 2026-05-01 | Codex | Updated usage guidance for stable `revrem` entry point, dev/stable install boundary, terminal title progress, and current CLI limitations |
| 0.1 | 2026-04-30 | GitCmurf | Initial draft |
