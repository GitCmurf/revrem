# revrem

[![CI](https://github.com/GitCmurf/revrem/actions/workflows/ci.yml/badge.svg)](https://github.com/GitCmurf/revrem/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/GitCmurf/revrem)](https://github.com/GitCmurf/revrem/releases)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python: 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776ab.svg)](pyproject.toml)

RevRem runs an automated review -> fix -> verify loop on your local branch before you open a pull request.

It asks Codex to review a branch against a base, applies valid actionable
findings through a bounded remediation pass, reruns your verification commands,
and leaves an artifact trail you can inspect before committing or merging.

The repository and Python package use the public name `revrem`. The legacy
`code-review-loop` command remains available as a compatibility alias for
existing local scripts.

## Demo

```text
$ revrem --base main --max-iterations 2 --check "pytest -q"
12:08:23|rev|1   |start: codex review --base main
12:10:14|rev|1   |[P1] Preserve failure artifacts when review startup fails
12:10:15|rem|1   |start: codex exec --full-auto --sandbox workspace-write ...
12:13:41|rem|1   |done
12:13:42|chk|1.1 |start: pytest -q
12:14:18|chk|1.1 |passed
12:14:19|rev|2   |clear

Review-remediation loop: clear (review_clear)
Artifacts: .revrem/runs/20260509T120823Z
JSON summary: .revrem/runs/20260509T120823Z/summary.json
```

## Install

RevRem is not published on PyPI yet. Install it from a checkout:

```bash
git clone https://github.com/GitCmurf/revrem.git
cd revrem
./scripts/install-dev
./.venv/bin/revrem --version
```

For a stable `revrem` command that is available from other local repositories:

```bash
./scripts/promote-stable
revrem --version
```

`./scripts/promote-stable` runs the local verification gate, copies the current
source snapshot under `~/.local/share/revrem/releases/`, builds an isolated
stable virtualenv under `~/.local/share/revrem/`, and updates these launchers:

```text
~/.local/bin/revrem
~/.local/bin/code-review-loop
```

Use `./.venv/bin/revrem` while developing this repository. Use the promoted
`revrem` command when reviewing other repositories.

## Quick Start

From the repository you want to review:

```bash
revrem --base main --max-iterations 2 --check "pytest -q"
```

Add checks that match the target repository:

```bash
revrem \
  --base main \
  --max-iterations 2 \
  --check "pytest -q" \
  --check "git diff --check"
```

Expected behavior:

- exit `0` when the final loop status is clear;
- exit `2` when findings or check failures remain after the bounded loop;
- write artifacts to `.revrem/runs/<timestamp>/`;
- append run metadata to `~/.local/share/revrem/runs.jsonl` unless
  `--no-run-history` is used.

Use repository-native checks. Python repositories can use `pytest`; TypeScript
repositories should usually use commands such as `pnpm test`,
`pnpm run typecheck`, and `pnpm run lint`.

Before a live model-backed loop, run local setup diagnostics:

```bash
revrem doctor --base main --check "pytest -q"
```

`revrem doctor` validates the local Git base, writable artifact path, Codex
executable, and configured check executables without invoking a model. Use
`--format json` for automation.

## How It Works

RevRem is intentionally local, watched, and bounded:

1. Runs `codex review` against a chosen base branch.
2. Detects whether the review is clear or has findings.
3. Runs a bounded Codex remediation pass for valid actionable findings.
4. Runs your configured verification commands.
5. Repeats until the review is clear or `--max-iterations` is reached.
6. Writes review, remediation, check, and summary artifacts for inspection.

Optional features include finding triage, JSON summaries, automatic remediation
commits after passing checks, Rich progress rendering, and a dependency-gated
Textual TUI.

## Profiles

Profiles keep long commands repeatable:

```bash
revrem config new final-pr --description "Full PR readiness check"
revrem config edit final-pr
revrem config show final-pr
revrem --profile final-pr
```

Project-local profiles can be saved without running the loop:

```bash
revrem --base main --max-iterations 2 --check "git diff --check" --save-profile final-pr
```

`--save-profile` writes `.revrem.toml` at the repository root and refuses to
overwrite an existing project profile unless `--save-profile-force` is
supplied.

## Safety Model

RevRem is a pre-merge confidence tool, not a substitute for review or tests.
Its safety posture is built around local operator control:

- iteration count is bounded by default;
- generated run artifacts are kept out of normal commits;
- auto-commit requires a clean worktree before the loop starts;
- remediation commits are made only after configured checks pass;
- machine-readable output is opt-in with `--summary-format json` or
  `--summary-format both`;
- local run history can be disabled with `--no-run-history`;
- no hosted service or telemetry is part of RevRem itself.

Use `--commit-after-remediation` only when each verified remediation pass should
become a git commit. RevRem stages with `git add -A` after checks pass, excludes
the configured artifact directory, skips empty commits, and runs `git commit`
itself.

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

## Limitations

- Codex must be installed and authenticated locally.
- The current directory must be the repository under review.
- The selected `--base` branch must share history with the current branch.
- Review/remediation quality depends on the model and the checks you provide.
- Human review, security review, and release approval still matter.
- Avoid dirty worktrees unless the local edits are intentional and understood.
- Do not use unbounded iteration counts for unattended automation.

## Development

```bash
./scripts/install-dev
pre-commit install
./scripts/dev-check
pre-commit run --all-files
```

The development extra installs `ruff`, `mypy`, `pytest`, Rich, Textual, build
tooling, `pre-commit`, `detect-secrets`, and license-review helpers. Ruff,
mypy, pytest, DocOps checks, and `git diff --check` are required local and CI
gates.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution expectations, governed
documentation, and release process details.

## License

This project is licensed under the Apache License 2.0; see [LICENSE](LICENSE)
for details. [NOTICE](NOTICE) contains project attribution and must be preserved
where Apache-2.0 notice requirements apply.
