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

For normal use, install RevRem from PyPI:

```bash
pipx install revrem
revrem --version
```

If you do not use `pipx`, install into a managed virtual environment:

```bash
python -m pip install revrem
revrem --version
```

For source development, install it from a checkout:

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

Machine-readable artifact contracts are documented under
[`docs/52-api/`](docs/52-api/).

Before a live model-backed loop, run local setup diagnostics:

```bash
revrem doctor --base main --check "pytest -q"
```

`revrem doctor` validates the local Git base, writable artifact path, Codex
executable, routed remediation harness executables, and configured check
executables without invoking a model. The internal `fake` harness used by local
tests is exempt from PATH checks because it is handled by RevRem itself rather
than launched as a standalone binary. Relative
`--artifact-dir` values are resolved against the doctor `cwd`, not the process
working directory. It warns when profile timeouts explicitly disable a phase
timeout and when the current locale is not UTF-8 capable. Use `--format json`
for automation.

To discover likely verification commands without running them:

```bash
revrem checks suggest --format json
revrem doctor checks --format json
```

To install bounded example Git hooks into the target repo:

```bash
revrem install-hooks
revrem install-hooks --uninstall
```

`revrem install-hooks` writes into the repository's configured `core.hooksPath`
when one is set, otherwise it falls back to Git's default hooks directory.

To share a failed run safely, create a redacted bundle:

```bash
revrem bundle-bug-report .revrem/runs/<run-id> --output revrem-bug.tar.gz
```

If `--output` is omitted, RevRem writes `revrem-bug-<safe-run-id>.tar.gz` in
the current working directory, using a basename-derived component from the run
metadata and falling back to the run directory name when needed.

The bundle command ignores symlinked artifacts so the archive cannot follow
links out of the run directory. It includes `summary.json`, `invocation.json`,
diagnostics/event JSON, status diagnostics, check output, and sanitized
profile/preflight snapshots when those files are present in the run directory.

Raw review/remediation transcripts are excluded by default. Use
`--include-raw-transcripts` only when the extra context is necessary; contents
are still redacted unless `--no-redact --i-understand-the-risks` is explicitly
passed.

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

When triage output is structured JSON, RevRem validates it against the selected
triage schema, writes `triage-N.json` with the payload's own `schema_version`,
and forwards the structured handoff plus the original review context to
remediation. Invalid structured triage writes `diagnostics-N.json` and fails
safe by continuing with the original review context. Resumed runs restore the
saved `--trusted-repo` setting so repo-local prompt fragments keep working when
the original run relied on them. The bug-report bundle includes both
`diagnostics.json` and numbered `diagnostics-N.json` artifacts so triage
failures stay diagnosable.
Structured triage also supports explicit suppressions via `revrem suppress`:
matching confirmed findings are moved to
`suppressed_findings`, remain visible in `triage-N.json`, and do not trigger
remediation when no unsuppressed findings remain.

## Profiles

Profiles keep long commands repeatable:

```bash
revrem config new final-pr --description "Full PR readiness check"
revrem config edit final-pr
revrem config show final-pr
revrem --profile final-pr
```

For a plain-terminal guided setup, use the CLI wizard:

```bash
revrem
revrem --wizard
```

In an interactive terminal, bare `revrem` opens the wizard. `revrem --wizard`
opens the wizard even when combined with other top-level options. In scripts
and other non-interactive contexts, bare `revrem` keeps the normal CLI
behavior. When local run history contains a compatible run for the current
repository, the wizard first offers those last settings as the starting point;
otherwise it starts from the recommended profile/defaults. It then opens on a
run-shape diagram before provider calls can start. The preview is built from
the same phase command builders used at runtime, lists the exact provider CLI
commands for review, triage, remediation, routed remediation, and
commit-message drafting, and shows each model-calling phase as
`harness:model(effort)`. The diagram separates the outer remediation pass limit
from the inner verify-failure retry limit, and shows commit-message drafting
only under the "if verify passes" commit branch.

If a provider command omits `--model`, the wizard resolves a trusted local
provider default when RevRem knows how. Codex defaults are read from
`$CODEX_HOME/config.toml` or `~/.codex/config.toml`. If the model still cannot
be resolved, the diagram marks it as `model unresolved` and the wizard only
allows printing or cancellation until you choose an explicit model.

The normal wizard path keeps the profile values unless you choose an edit
screen. Verification checks can be kept from the profile or selected from
detected repo presets such as `./scripts/dev-check`, Python test/static checks,
Meminit DocOps checks, and `git diff --check`; raw shell commands remain
available under the custom option.

The model settings screen is phase-specific: review, triage, remediation, and
commit-message drafting each expose their own harness, model, and reasoning
effort. When you change one phase, the generated command uses the matching
phase flag such as `--review-reasoning-effort` or
`--remediation-reasoning-effort`; it does not silently apply one shared model
choice to every provider call. Disabled triage is shown as a setup action, and
selecting it walks through enabling triage before routing choices. Harnesses
are selected from known RevRem harnesses so mistyped names are caught inside
the wizard, and suspicious model names such as bare numbers require
confirmation. Timeouts have their own main-menu editor for the existing shared
`--timeout-seconds` flag; setting it to `0` disables review, remediation,
commit-message drafting, and shell-check subprocess timeouts for that run.

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
itself. If commit hooks fail, the default policy is to preserve the staged
changes, write the hook output to the commit artifact, and feed that output into
the next bounded remediation pass. Use `--commit-on-hook-failure stop` to fail
gracefully instead, or `--commit-on-hook-failure no-verify` only when bypassing
hooks is an intentional operator decision.

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
- Do not paste raw model transcripts or local run artifacts into public issues;
  use the redacted bug-report workflow instead.

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

Optional runtime extras stay narrow: `.[progress]` installs Rich, `.[tui]`
installs Textual and Rich, and `.[redaction]` installs optional
`detect-secrets` support for workflows that want an additional scanner alongside
RevRem's built-in redaction regexes.

The repository also carries tiny local compatibility shims for `tomli_w` and
`jsonschema` so the test suite can collect in minimal environments. The
published dependency declarations remain the supported install path.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution expectations, governed
documentation, and release process details.

## License

This project is licensed under the Apache License 2.0; see [LICENSE](LICENSE)
for details. [NOTICE](NOTICE) contains project attribution and must be preserved
where Apache-2.0 notice requirements apply.
