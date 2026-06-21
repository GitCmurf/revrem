# revrem

[![CI](https://github.com/GitCmurf/revrem/actions/workflows/ci.yml/badge.svg)](https://github.com/GitCmurf/revrem/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/revrem)](https://pypi.org/project/revrem/)
[![Python](https://img.shields.io/pypi/pyversions/revrem)](https://pypi.org/project/revrem/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/GitCmurf/revrem/blob/main/LICENSE)

**Run a bounded AI review → fix → verify loop on your local branch — before you push.**

RevRem asks Codex to review your branch against a base, applies valid actionable
findings through a bounded remediation pass, reruns your own verification
commands, and leaves an inspectable artifact trail — all locally, before you open
a pull request.

<p align="center">
  <img src="https://raw.githubusercontent.com/GitCmurf/revrem/main/docs/assets/revrem-demo.gif" width="900"
    alt="revrem running a review then fix then verify loop: a P1 finding is remediated, pytest passes, and the re-review comes back clear." />
</p>

<details>
<summary>Text version of the demo</summary>

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

</details>

> The demo above is a scripted reconstruction of RevRem's real output format,
> not a live model-backed capture. Source: [`docs/assets/`](https://github.com/GitCmurf/revrem/tree/main/docs/assets).

## Why revrem

- **Entirely local.** No hosted service, no telemetry — RevRem runs on your
  machine against your checkout.
- **Bounded and watched.** Iterations are capped by default, and the run exits
  with a clear pass/fail status code you can gate CI or hooks on.
- **Inspectable.** Every run writes review, remediation, check, and summary
  artifacts you can read before committing or merging.
- **Works at any stage.** Use it pre-commit, pre-merge, or post-merge — wherever
  a fast, automated review-and-fix pass adds confidence.

## Install

Install from PyPI with `pipx` (recommended):

```bash
pipx install revrem
revrem --version
```

If you do not use `pipx`, install into a managed virtual environment:

```bash
python -m pip install revrem
revrem --version
```

To work on RevRem itself, see [Development](#development).

> The repository and Python package use the public name `revrem`. The legacy
> `code-review-loop` command remains available as a compatibility alias.

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
repositories usually use commands such as `pnpm test`, `pnpm run typecheck`, and
`pnpm run lint`.

Before a live, model-backed loop, run setup diagnostics (no model is invoked):

```bash
revrem doctor --base main --check "pytest -q"
```

`revrem doctor` validates the Git base, a writable artifact path, the Codex
executable, routed remediation harnesses, and configured checks. Use
`--format json` for automation. See the
[operator guide](https://github.com/GitCmurf/revrem/blob/main/docs/70-devex/devex-001-using-code-review-loop.md)
for the full diagnostics contract.

## How It Works

RevRem is intentionally local, watched, and bounded:

1. Runs `codex review` against a chosen base branch.
2. Detects whether the review is clear or has findings.
3. Runs a bounded Codex remediation pass for valid actionable findings.
4. Runs your configured verification commands.
5. Repeats until the review is clear or `--max-iterations` is reached.
6. Writes review, remediation, check, and summary artifacts for inspection.

## Key Features

- **Profiles** keep long commands repeatable, with per-phase model, effort, and
  timeout control.
- **Interactive wizard** builds a run command in a plain terminal and previews
  the exact provider calls before anything runs.
- **Finding triage and routing** (optional) turn review prose into ordered,
  schema-validated actions and route them to the right harness/model.
- **Auto-commit** (optional) commits each verified remediation pass after your
  checks pass.
- **Bug-report bundles** package a failed run into a redacted, shareable archive.
- **Static HTML reports** render a finished run into a single, self-contained,
  redacted-by-default HTML file (or a machine-readable JSON index) — no model
  re-run, no network, safe to upload as a CI artifact (`revrem report`).
- **Git hooks** install bounded pre-push/pre-commit example hooks into a target
  repo.
- **Rich progress and an optional Textual TUI** for richer watched-terminal runs.

Each of these is documented in depth in the
[operator guide](https://github.com/GitCmurf/revrem/blob/main/docs/70-devex/devex-001-using-code-review-loop.md). Machine-readable
artifact contracts live under [`docs/52-api/`](https://github.com/GitCmurf/revrem/tree/main/docs/52-api).

## Profiles and the Wizard

Profiles keep long commands repeatable:

```bash
revrem config new final-pr --description "Full PR readiness check"
revrem config edit final-pr
revrem --profile final-pr
```

In an interactive terminal, bare `revrem` (or `revrem --wizard`) opens a guided
setup. It offers your last compatible settings or the recommended defaults,
then shows a run-shape preview listing the **exact** provider CLI commands for
each phase before any model is called. Model, reasoning effort, and timeout are
selectable per phase (review, triage, remediation, commit-message drafting).

Project-local profiles can be saved to `.revrem.toml` without running the loop:

```bash
revrem --base main --max-iterations 2 --check "git diff --check" --save-profile final-pr
```

For triage, routing, multi-harness setups, and the full wizard reference, see
the [operator guide](https://github.com/GitCmurf/revrem/blob/main/docs/70-devex/devex-001-using-code-review-loop.md#interactive-wizard).

## Safety Model

RevRem is a pre-merge confidence tool, not a substitute for review or tests. Its
safety posture is built around local operator control:

- iteration count is bounded by default;
- generated run artifacts are kept out of normal commits;
- auto-commit requires a clean worktree before the loop starts, and commits only
  after configured checks pass;
- machine-readable output is opt-in (`--summary-format json`);
- local run history can be disabled with `--no-run-history`;
- no hosted service or telemetry is part of RevRem itself.

Use `--commit-after-remediation` only when each verified remediation pass should
become a git commit. Commit-hook failure handling, `--no-redact` bundle risks,
and the full auto-commit contract are documented in the
[operator guide](https://github.com/GitCmurf/revrem/blob/main/docs/70-devex/devex-001-using-code-review-loop.md#profile-based-usage).

## Optional Progress and TUI

Optional extras must be installed into the **same environment** as `revrem`, so
`revrem` can import them at launch. If you installed with `pipx`, add the extra
with `pipx` too (use `pip install "revrem[...]"` only for a plain `pip` install).

For richer watched-terminal output:

```bash
pipx install --force "revrem[progress]"
revrem --profile final-pr --progress-style rich
```

The optional TUI is dependency-gated so the default CLI stays lightweight:

```bash
pipx install --force "revrem[tui]"
revrem ui --profile final-pr
```

The TUI renders Home, Profiles, Pipeline, Run Monitor, and Controls views, and
shells through the same CLI command plans as normal terminal usage.

## Status

**Alpha.** RevRem is used daily in its own development and runs end to end
today. The core review → fix → verify loop is stable; some CLI flags and
artifact formats may still change ahead of a 1.0 release — pin a version if you
depend on exact output.

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
git clone https://github.com/GitCmurf/revrem.git
cd revrem
./scripts/install-dev
./.venv/bin/revrem --version
```

Run the local gates:

```bash
pre-commit install
./scripts/dev-check
pre-commit run --all-files
```

Ruff, mypy, pytest, DocOps checks, and `git diff --check` are required local and
CI gates. For a stable `revrem` command usable from other repositories, promote
a snapshot with `./scripts/promote-stable` — see the
[operator guide](https://github.com/GitCmurf/revrem/blob/main/docs/70-devex/devex-001-using-code-review-loop.md#promote-a-stable-local-version).

See [CONTRIBUTING.md](https://github.com/GitCmurf/revrem/blob/main/CONTRIBUTING.md) for contribution expectations, governed
documentation, and release process details.

## License

This project is licensed under the Apache License 2.0; see [LICENSE](https://github.com/GitCmurf/revrem/blob/main/LICENSE)
for details. [NOTICE](https://github.com/GitCmurf/revrem/blob/main/NOTICE) contains project attribution and must be preserved
where Apache-2.0 notice requirements apply.
