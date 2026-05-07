# code-review-loop

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python: 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776ab.svg)](pyproject.toml)

`code-review-loop` packages the review-remediation loop that experienced
operators run before a pull request is ready for serious review. It asks Codex
to review a branch against a base, applies valid actionable findings through a
bounded remediation pass, reruns your verification commands, and leaves a
structured artifact trail you can inspect instead of trusting a transient chat.

The command is intentionally local, watched, and bounded. It does not run a
hosted service, collect telemetry, or claim that AI review proves correctness.
It is a practical pre-merge confidence tool for teams that already use agentic
coding and want the loop to be repeatable.

## What It Does

- Runs `codex review` against a chosen base branch.
- Optionally triages review findings before remediation.
- Runs bounded Codex remediation iterations with explicit `--max-iterations`.
- Executes project-specific checks such as `pytest`, `mypy`, `pnpm test`, or
  `git diff --check`.
- Writes per-run artifacts under `.revrem/runs/<timestamp>/`.
- Records compact local run history in `~/.local/share/revrem/runs.jsonl`.
- Supports reusable profiles in user and project config files.
- Provides an optional Rich progress renderer and Textual TUI.

## When To Use This

Use RevRem when you have a local branch that already builds, you want a
bounded adversarial review/remediation pass before opening or updating a pull
request, and you are prepared to inspect the diff and artifacts afterwards.

It is a good fit for:

- final PR readiness checks;
- repeated cleanup after AI-generated implementation work;
- local automation where a human operator is watching progress;
- repositories with clear verification commands.

## When Not To Use This

Do not use RevRem as a substitute for human review, security review, release
approval, or tests. Avoid it on dirty worktrees unless the local edits are
intentional and you understand what the remediation pass may change. Do not use
unbounded iteration counts for unattended automation.

## Install

For development from a checkout:

```bash
git clone https://github.com/GitCmurf/code-review-loop.git
cd code-review-loop
./scripts/install-dev
```

For a stable local command available from other repositories:

```bash
./scripts/promote-stable
revrem --version
```

The stable promotion script updates:

```text
~/.local/bin/revrem
~/.local/bin/code-review-loop
```

`revrem` and `code-review-loop` are equivalent entry points. Use `revrem` for
human-facing usage and keep `code-review-loop` for scripts that prefer the
package name.

## Quick Start

From the repository you want to review:

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

Expected behavior:

- exit `0` when the final loop status is clear;
- exit `2` when findings or check failures remain after the bounded loop;
- write artifacts to `.revrem/runs/<timestamp>/`;
- append run metadata to `~/.local/share/revrem/runs.jsonl` unless
  `--no-run-history` is used.

Use checks that match the target repository. Python repositories can use
`--check "pytest -q"`; TypeScript repositories should usually use native
checks such as `--check "pnpm test"` and `--check "pnpm run typecheck"`.

## Profiles

Profiles keep long commands repeatable:

```bash
revrem config new final-pr --description "Full PR readiness check"
revrem config edit final-pr
revrem config show final-pr
revrem config clone final-pr final-pr-copy
revrem --profile final-pr
```

Project-local profiles can be saved without running the loop:

```bash
revrem --base main --max-iterations 2 --check "git diff --check" --save-profile final-pr
```

`--save-profile` writes `.revrem.toml` at the repository root and refuses to
overwrite an existing project profile unless `--save-profile-force` is
supplied.

## Artifacts And Safety Model

RevRem is designed for visible local automation:

- iteration count is bounded by default;
- generated run artifacts are kept out of normal commits;
- auto-commit requires a clean worktree before the loop starts;
- remediation commits are made only after configured checks pass;
- machine-readable output is opt-in with `--summary-format json` or
  `--summary-format both`;
- local run history can be disabled with `--no-run-history`.

Use `--commit-after-remediation` only when each verified remediation pass
should become a git commit. RevRem stages with `git add -A` after checks pass,
excludes the configured artifact directory, skips empty commits, and runs
`git commit` itself.

## Optional Progress And TUI

For richer watched-terminal output:

```bash
./.venv/bin/pip install -e ".[progress]"
revrem --profile final-pr --progress-style rich
```

The optional TUI is dependency-gated so the default CLI remains lightweight:

```bash
./.venv/bin/pip install -e ".[tui]"
./.venv/bin/revrem ui
./.venv/bin/revrem ui --profile final-pr
```

The TUI renders Home, Profiles, Pipeline, Run Monitor, and Controls views. It
shells through the same CLI command plans as normal terminal usage.

## Development

```bash
./scripts/install-dev
pre-commit install
./scripts/dev-check
pre-commit run --all-files
```

The development extra installs `ruff`, `mypy`, `pytest`, Rich, Textual, build
tooling, `pre-commit`, `detect-secrets`, and license-review helpers. Ruff,
mypy, pytest, Meminit compliance, and `git diff --check` are required local and
CI gates.

Meminit is this repository's governed documentation system. Design rationale,
operator guidance, and testing strategy live in `docs/` as governed documents
validated by:

```bash
meminit doctor --format json
meminit check --format json
```

Useful governed docs:

- `REVREM-ADR-001`: packaging decision for the Python CLI and companion skill.
- `REVREM-DEVEX-001`: operator usage guide.
- `REVREM-TEST-001`: utility verification strategy.
- `REVREM-TASK-001`: public GitHub launch readiness plan.

## Release Checklist

For the next release:

```bash
# 1. Bump pyproject.toml and src/code_review_loop/__init__.py.
./scripts/dev-check
pre-commit run --all-files
git diff --check
git add pyproject.toml src/code_review_loop/__init__.py CHANGELOG.md
git commit -m "chore: bump version to <version>"
git tag v<version>
./scripts/promote-stable
revrem --version
```

Public release artifacts should be built by GitHub Actions so provenance
attestations and the SBOM are attached to the release.

## License

This project is licensed under the Apache License 2.0; see the repository
LICENSE file for details. The NOTICE file contains project attribution and
must be preserved where Apache-2.0 notice requirements apply.
