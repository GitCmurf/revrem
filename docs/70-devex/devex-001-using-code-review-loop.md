---
document_id: REVREM-DEVEX-001
type: DEVEX
title: Using code-review-loop
status: Draft
version: '0.7'
last_updated: '2026-05-03'
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
> **Version:** 0.7
> **Last Updated:** 2026-05-03
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

This creates or updates `./.venv` as an editable install. If the active
interpreter is older than Python 3.11, it fails fast before writing fallback
launchers, and it recreates a stale `./.venv` when needed. Use it for changes in
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
`~/.local/share/revrem/stable-venv`, recreating an older or missing stable
venv before updating:

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

### Release and promote the next version

Use this sequence when the current development snapshot is ready to become the
stable local version:

```bash
# Edit pyproject.toml and src/code_review_loop/__init__.py to the next version.
./scripts/dev-check
git diff --check
git add pyproject.toml src/code_review_loop/__init__.py
git commit -m "chore: bump version to <version>"
git tag v<version>
./scripts/promote-stable
revrem --version
```

`./scripts/promote-stable` reruns `./scripts/dev-check` before it updates
`~/.local/bin/revrem` and `~/.local/bin/code-review-loop`. In sandboxed agent
sessions, `git tag` may need explicit escalation because Git writes tag refs,
and annotated tags also write tag objects, under `.git`.

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
Clear terminal summaries stay compact and point to artifacts instead of
reprinting the successful review prose. Non-clear summaries include the latest
actionable excerpt so the next operator or agent can continue from the right
failure.
Progress log timestamps, including Rich progress timestamps, use local terminal
wall time, so watched runs line up with the operator's shell clock. Shared
history keeps UTC ISO-8601 timestamps for machine processing.
Non-dry-run invocations also append compact JSONL metadata to
`~/.local/share/revrem/runs.jsonl` by default. The per-run transcripts remain in
the target repository's artifact directory; the shared history file stores only
the run identifier, cwd, base, profile, final status, iteration count, and the
artifact pointer map used by the TUI, including the summary path. `revrem history list` skips malformed or truncated JSONL
entries so one interrupted append does not hide earlier valid runs. Set
`XDG_DATA_HOME` to relocate the data root or pass `--no-run-history` for a run
that should not update shared history.

For richer watched-terminal output, install the optional progress extra and use
`--progress-style rich`:

```bash
./.venv/bin/pip install -e ".[progress]"
./.venv/bin/revrem --profile final-pr --progress-style rich
```

If Rich is requested but unavailable, RevRem prints one warning and falls back to
compact progress. Existing commands do not need to change.

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

Use `--initial-review-file latest` with the effective artifact directory. When
`--artifact-dir` or a profile sets `output.artifact_dir`, `latest` resolves
under that directory instead of the default workspace-local tree.

### Profile-based usage

Profiles live in `~/.config/revrem/profiles.toml`. Project-local overrides live
in `.revrem.toml` at the target repository root, so subdirectory invocations
still pick up the same project settings. User-global `[defaults]` entries in
`profiles.toml` are loaded for bare `revrem` runs, merged before the selected
user profile, and are preserved by `revrem config` writes. Existing profiles
stay in their original explicit form when the file is rewritten, so omitted
fields keep inheriting shared defaults. If a profile field is explicitly set
back to a built-in default, the rewrite keeps it when the file's `[defaults]`
table would otherwise change behavior. Profile loading rejects unknown keys in
top-level tables, profile tables, and nested sections, so typos fail fast instead of silently
using defaults. A minimal final-PR profile:

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

[profiles.final-pr.commit]
enabled = false
message_model = "gpt-5.3-codex-spark"

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

True-by-default booleans also have positive CLI overrides. Use `--full-auto`,
`--output-last-message`, or `--final-review` to restore the built-in `true`
behavior for a one-off run when a profile disables one of those settings; use
the `--no-*` or `--skip-final-review` forms to force them off.

Timeout fields are numeric. A TOML boolean such as `timeout_seconds = false`
is rejected during profile loading so that accidental type mistakes cannot
disable bounded execution. A phase timeout set to `0` stays disabled for that
phase and is passed through to the matching subprocess unchanged. If a phase
omits `timeout_seconds`, it falls back to the built-in default timeout instead
of inheriting the sibling phase's value.
Negative phase timeouts are rejected during profile loading as invalid
configuration, matching the CLI's `--timeout-seconds` validation.
When terminal title refresh is enabled, the subprocess wrapper keeps waiting on
the same child after a timeout without resending stdin, which avoids the
`communicate()` retry error on long-running stdin-driven phases.
Profile `review.reasoning_effort` and `remediation.reasoning_effort` values are
validated during profile loading and must be one of `minimal`, `low`, `medium`,
or `high`.

Profile management commands:

```bash
revrem config list
revrem config show final-pr
revrem config new final-pr --description "Full PR readiness check"
revrem config export final-pr
revrem config import profiles.toml
revrem config doctor --profile final-pr --format json
```

`revrem config import` requires an existing TOML file and fails fast if the
path is missing, rather than creating an empty destination config rewrite.

`revrem config list` shows each profile's description, source file, and last-used timestamp from run history.

Run-history commands:

```bash
revrem history list
revrem history --format json list --limit 20
```

These management commands validate reserved harness names and triage syntax
without requiring the backend to be executable yet; only `revrem --profile ...`
rejects unimplemented harnesses before the loop starts.

The `--format` flag is accepted both before and after the subcommand, so the
global form `revrem config --format json doctor --profile final-pr` works too.

Profiles reserve `review.harness`, `triage.harness`, and
`remediation.harness` for future headless adapters such as `claude`, `gemini`,
`opencode`, and `kilo`. The current executable loop supports only Codex; using
another harness in a resolved run fails before starting subprocesses.

Set `commit.enabled = true` or pass `--commit-after-remediation` only in a
worktree where it is acceptable for RevRem to stage all current changes with
`git add -A` after a verified remediation pass, while excluding the configured
artifact directory from staging. If a profile enables commits by default but a
single invocation should remain dry, pass `--no-commit-after-remediation` to
override that profile setting. The commit step is separate from the remediation
model: checks must pass first, RevRem skips the commit if there are no staged
changes, and RevRem runs `git commit` itself. The optional `commit.message_model`
or `--commit-message-model` controls only the read-only Codex call that drafts
the commit subject. If no explicit CLI value is supplied, the profile value is
used; the built-in profile default is `gpt-5.3-codex-spark`. With the default
prompt, RevRem normalizes the final subject to Conventional Commit syntax and
appends ` (RevRem)`. Passing `--commit-message-prompt` intentionally disables
that default subject policy so special-purpose commit formats can be tested
without fighting the normalizer. If a verified remediation pass produces no
staged changes, RevRem stops the loop immediately; an `unknown` review status
in that no-op path is treated as a clear terminal result and still records the
unexpected-status bug-report artifact. Auto-commit also requires a clean
worktree before the loop starts so unrelated local edits cannot be staged by
the broad `git add -A` step.

```bash
revrem --profile final-pr --commit-after-remediation
revrem --profile final-pr --commit-after-remediation --commit-message-model gpt-5.3-codex-spark
revrem --profile final-pr --commit-after-remediation --commit-message-prompt "Write a release-note style subject."
```

Use phase-specific reasoning-effort flags when one phase needs a different
cost/quality tradeoff:

```bash
revrem --profile final-pr \
  --review-reasoning-effort high \
  --triage-reasoning-effort low \
  --remediation-reasoning-effort medium \
  --commit-reasoning-effort minimal
```

Optional Codex triage can run between review and remediation. It uses
`codex exec` with `--sandbox read-only`, writes `triage-N.txt` beside the review
and remediation artifacts, and passes a concise handoff plus the original
review/check context into the remediation prompt. This is intended for cheaper
interpretation models that can convert review prose into ordered action items
without editing the workspace:

```toml
[profiles.final-pr.triage]
enabled = true
model = "gpt-5.4-mini"
reasoning_effort = "low"
timeout_seconds = 300
prompt = "Break down the review into confirmed actions, likely false positives, and verification steps."
```

### Current CLI boundary

Rich progress is available via `--progress-style rich` when the optional
`progress` extra is installed. In Rich output, the timestamp is dimmed, the
phase/action word and status word are highlighted, labels are cyan, and model
or review text is rendered literally so markup-like review output cannot break
the display.

`revrem ui` is available as a dependency-gated entry point for the planned
Textual interface:

```bash
./.venv/bin/pip install -e ".[tui]"
./.venv/bin/revrem ui
```

Without the `tui` extra, `revrem ui` exits cleanly with an installation hint.
The first TUI slice is a navigational shell; the CLI remains the authoritative
execution path while the full Home, Profiles, Pipeline Builder, and Run Monitor
screens are completed. The shell is backed by dependency-free view models for
profiles, recent runs, harness metadata, and pipeline phases so future Textual
widgets can reuse the same tested state without duplicating CLI logic. Profile
command previews and dry-run launch plans are generated from the same profile
data so the UI can show the operator the exact `revrem --profile ...` command
before launch. Recent-run summaries are also flattened into artifact-link view
models for the future Run Monitor screen.

Codex is currently the only executable review/remediation harness. The profile
schema reserves `claude`, `gemini`, `opencode`, and `kilo` for future headless
adapters; config management accepts those values, but executable runs fail fast
until a backend adapter is implemented.

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
- Enable `--commit-after-remediation` only when automatic staging of the current
  worktree is intended. It is best suited to focused loop runs where each pass
  should become a reviewable checkpoint commit.
- Relative artifact directories that resolve inside the current worktree are
  excluded from the staged commit too, so `--artifact-dir artifacts/revrem`
  keeps generated loop transcripts out of the checkpoint commit. Paths that
  resolve outside `cwd` are left unstaged instead of being passed to
  `git reset`.
- Use `--debug-status-detection` when a run appears to keep remediating after
  the review text looks clear. The flag writes `*-status.json` files next to
  review artifacts and logs the compact reason for each clear/findings/unknown
  classification.
- If any review still classifies as `unknown`, the final text summary includes a
  warning and writes `unexpected-behavior-report.txt` in the artifact directory.
  Include that report, the referenced `review-N.txt`, and any
  `review-N-status.json` diagnostics when filing a RevRem bug report.
- Use `--terminal-title` in a watched terminal to update the window/tab title as
  the loop moves between review and remediation phases, for example
  `rev 1/2 RevRem` and `rem 1/2 RevRem`. The tool uses terminal title-stack
  escape sequences to restore the previous title on exit where the terminal
  supports them, and emits both common window-title escape forms for broader
  terminal compatibility. Terminals that ignore those sequences will still run
  normally.
- If a subprocess refresh times out while a remediation prompt is still being
  written, the loop retries without manually closing stdin so the child can
  keep receiving the buffered prompt while title updates continue.

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
| 0.7 | 2026-05-03 | Codex | Documented TUI launch-plan and run-monitor artifact state |
| 0.6 | 2026-05-03 | Codex | Added release/version promotion guidance and documented sandbox tagging behavior |
| 0.5 | 2026-05-02 | Codex | Documented harness adapter boundary and TUI profile command previews |
| 0.4 | 2026-05-02 | Codex | Documented Rich progress column styling and current dependency-gated TUI shell behavior |
| 0.3 | 2026-05-02 | Codex | Added profile-based usage, config commands, current harness/triage boundary, history/progress hardening, and verified commit-after-remediation guidance |
| 0.2 | 2026-05-01 | Codex | Updated usage guidance for stable `revrem` entry point, dev/stable install boundary, terminal title progress, and current CLI limitations |
| 0.1 | 2026-04-30 | GitCmurf | Initial draft |
