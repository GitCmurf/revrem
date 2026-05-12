---
document_id: REVREM-DEVEX-001
type: DEVEX
title: Using code-review-loop
status: Draft
version: '1.5'
last_updated: '2026-05-12'
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
> **Version:** 1.3
> **Last Updated:** 2026-05-06
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
`~/.local/bin/revrem` and `~/.local/bin/code-review-loop`. It also refreshes
the stable runtime dependency install on every promotion so an older stable
virtualenv keeps working after the launcher source tree advances. In sandboxed
agent sessions, `git tag` may need explicit escalation because Git writes tag
refs, and annotated tags also write tag objects, under `.git`.

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
that should not update shared history. Review invocation failures still write
the per-run `summary.json` before the run is surfaced as a failed history entry,
so auth, timeout, and startup errors remain inspectable.

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

Do not carry a Python `pytest` check into TypeScript-only repositories. Prefer
the repository's native checks, for example:

```bash
--check "pnpm test"
--check "pnpm run typecheck"
--check "pnpm run lint"
```

As a guardrail for shared profiles, RevRem treats a configured pytest command as
not applicable when the target repository has Node/TypeScript project markers
such as `package.json` or `tsconfig.json` and no recognized Python
project/test surface. A stray helper `.py` file is not enough to keep pytest
active. In that case pytest is recorded as a skipped adaptive check instead of
blocking a clear review because pytest returned `2`, `4`, or `5`.

### Continuation after findings

The loop writes artifacts under `.revrem/runs/<timestamp>-<suffix>/` by default. On the
first default-artifact run in a Git repository, RevRem adds the default run
path to the repository-local `.git/info/exclude` even when invoked from a
subdirectory; outside Git repositories it falls back to `.revrem/.gitignore`
containing `runs/`. This keeps local transcripts out of commits without
mutating tracked ignore files. Linked worktrees use the common repository's
`.git/info/exclude`.
If a capped run ends with findings, continue from the final review artifact:

```bash
revrem \
  --base main \
  --max-iterations 2 \
  --initial-review-file .revrem/runs/<timestamp>-<suffix>/review-final.txt \
  --check "pytest -q"
```

Use `--initial-review-file latest` with the effective artifact directory. When
`--artifact-dir` or a profile sets `output.artifact_dir`, `latest` resolves
under that directory instead of the default workspace-local tree. `latest`
uses the newest `review-final.txt` only when that run is still non-clear. If
the newest run's `summary.json` reports `final_status = "clear"`, or there is
no previous final review, RevRem starts with a fresh review instead of reviving
older feedback.

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
harness = "codex"
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

To capture a one-off command as a project-local profile, add
`--save-profile NAME`. RevRem writes the effective configuration to
`.revrem.toml` at the repository root and exits without running the loop. This
is non-destructive by default; pass `--save-profile-force` only when replacing
an existing project profile intentionally. Explicit `--timeout-seconds 0`
settings are written back as `timeout_seconds = 0` so a saved profile keeps the
no-timeout behavior.

```bash
revrem \
  --base main \
  --max-iterations 11 \
  --review-model gpt-5.5 \
  --remediation-model gpt-5.4-mini \
  --reasoning-effort medium \
  --timeout-seconds 1800 \
  --summary-format text \
  --debug-status-detection \
  --terminal-title \
  --check "pytest -q" \
  --check "git diff --check" \
  --progress-style rich \
  --commit-after-remediation \
  --commit-message-model gpt-5.3-codex-spark \
  --save-profile final-pr
```

Boolean profile values can be overridden from the CLI. Use `--full-auto`,
`--output-last-message`, `--final-review`, `--exec-json`,
`--debug-status-detection`, `--quiet-progress`, or `--terminal-title` to force
them on for a one-off run; use the matching `--no-*` form, or
`--skip-final-review`, to force them off.

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
revrem config edit final-pr
revrem config clone final-pr final-pr-copy
revrem config export final-pr
revrem config import profiles.toml
revrem config delete final-pr-copy --yes
revrem config doctor --profile final-pr --format json
```

In an interactive terminal, `revrem config new NAME` prompts for the common
profile fields: description, harness, review model, remediation model,
reasoning effort, timeout, and a first check command. Use `--no-interactive`
for automation and TUI-launched profile creation, or pass `--interactive` to
force the wizard when stdin/stdout are not detected as a terminal.

`revrem config import` requires an existing TOML file and fails fast if the
path is missing, rather than creating an empty destination config rewrite. When
the imported file contains `[defaults]`, RevRem folds those source defaults
into each imported profile before writing the destination config. This preserves
the behavior of portable shared-profile files even when the destination
`profiles.toml` has different user-wide defaults.

`revrem config list` shows each profile's description, source file, and last-used timestamp from run history.

Run-history commands:

```bash
revrem history list
revrem history --format json list --limit 20
```

Bug-report bundle command:

```bash
revrem bundle-bug-report .revrem/runs/<run-id> --output revrem-bug.tar.gz
```

If `--output` is omitted, the command writes `revrem-bug-<safe-run-id>.tar.gz`
in the current working directory. The run-id component is reduced to a safe
basename and falls back to the run directory name when necessary.

The bundle is deterministic and redacted by default. It includes the manifest,
`summary.json`, diagnostics/event JSON when present, and sanitized check output.
Raw text transcripts such as review and remediation artifacts are excluded
unless `--include-raw-transcripts` is passed. Disabling redaction requires both
`--no-redact` and `--i-understand-the-risks`.
When a repository-level suppression audit exists, the bundle also includes a
redacted suppression-audit summary resolved from the owning repo, even for runs
stored under `.revrem/runs/<run-id>`.

Local setup diagnostics:

```bash
revrem doctor --base main --check "pytest -q" --format json
```

`revrem doctor` validates deterministic preconditions before the first model
call: the working directory is inside Git, the base ref resolves and shares
history with `HEAD`, the effective artifact directory is writable, Codex is on
`PATH`, and configured check executables exist. If Git itself is missing, the
doctor returns a blocking `revrem.preflight.git_not_found` diagnostic instead
of crashing. Relative `--artifact-dir` values are resolved against the doctor
`cwd`, not the shell's current directory. When no artifact directory is
supplied, that effective path is the default `.revrem/runs/<timestamp>-<suffix>/`
tree that a normal loop run will create. It exits `4` for blocking setup
failures, `6` for warnings when `--strict` is used, and `0` when the local
preflight is clear.

These management commands validate reserved harness names and triage syntax
without requiring the backend to be executable yet; only `revrem --profile ...`
rejects unimplemented harnesses before the loop starts.

The `--format` flag is accepted both before and after the subcommand, so the
global form `revrem config --format json doctor --profile final-pr` works too.

Profiles reserve `review.harness`, `triage.harness`,
`remediation.harness`, and `commit.harness` for future headless adapters such
as `claude`, `gemini`, `opencode`, and `kilo`. The current executable loop
supports only Codex; using another harness in a resolved run fails before
starting subprocesses.

Set `commit.enabled = true` or pass `--commit-after-remediation` only in a
worktree where it is acceptable for RevRem to stage all current changes with
`git add -A` after a verified remediation pass, while excluding the configured
artifact directory from staging. If a profile enables commits by default but a
single invocation should remain dry, pass `--no-commit-after-remediation` to
override that profile setting. The commit step is separate from the remediation
model: checks must pass first, RevRem skips the commit if there are no staged
changes, and RevRem runs `git commit` itself. The optional `commit.harness`
field selects the commit-message drafting adapter; only `codex` is executable
today. The optional `commit.message_model` or `--commit-message-model` controls
only the read-only Codex call that drafts the commit subject. If no explicit
CLI value is supplied, the profile value is used; the built-in profile default
is `gpt-5.3-codex-spark`. With the default
prompt, RevRem normalizes the final subject to Conventional Commit syntax and
appends `(RevRem)`. Passing `--commit-message-prompt` intentionally disables
that default subject policy so special-purpose commit formats can be tested
without fighting the normalizer. If a verified remediation pass produces no
staged changes, RevRem stops the loop immediately; in that no-op path an
`unknown` review status remains `final_status: "unknown"` with
`stopped_reason: "no_changes_after_remediation"`, and the unexpected-status
bug-report artifact is still recorded for operator follow-up. Auto-commit also
requires a clean worktree before the loop starts so unrelated local edits
cannot be staged by the broad `git add -A` step.

Commit hooks are part of the commit phase, not an afterthought. When `git
commit` appears to fail inside hooks, RevRem defaults to `commit.on_hook_failure
= "remediate"`: it leaves staged changes intact, records the hook output in
`commit-N.txt`, and injects that output into the next bounded remediation pass.
Use `commit.on_hook_failure = "stop"` or `--commit-on-hook-failure stop` when a
hook failure should end the run immediately with `stopped_reason:
"commit_hook_failed"`. Use `no-verify` only for explicit operator-controlled
flows; RevRem records that policy as `commit_no_verify: true` in `summary.json`
and runs `git commit --no-verify`.

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
on_invalid = "continue"
prompt = "Break down the review into confirmed actions, likely false positives, and verification steps."
```

When the triage output is JSON, RevRem treats it as a structured v1 artifact:
it stamps envelope fields, validates against `docs/52-api/schemas/triage-v1.schema.json`,
writes `triage-N.json`, and still includes the original review/check context in
the remediation prompt. Invalid structured triage writes `diagnostics.json` with
`revrem.triage.invalid_output`. The default `triage.on_invalid = "continue"`
fails safe by ignoring invalid triage guidance; set `triage.on_invalid = "stop"`
when a workflow should halt on malformed triage output.

Structured triage is also the suppression-aware path. Add an explicit
suppression when a fingerprinted finding is accepted, tracked elsewhere, or
known to be a false positive:

```bash
revrem suppress add f1:c6ace015ccd20120 \
  --summary "Accepted generated-code finding" \
  --rationale "Generated fixture is intentionally vulnerable for tests." \
  --severity medium
```

Repo-local suppressions live in `.revrem/suppressions.toml`; user-local
suppressions live in `~/.config/revrem/suppressions.toml`. Repo suppressions
win when both scopes contain the same fingerprint. `revrem suppress check
<fingerprint>` exits `0` when suppressed and `2` when not suppressed. Critical
findings require `--critical-override` and an expiry within 30 days. Each
mutation appends to a local audit JSONL file. Suppressed findings remain visible
in `triage-N.json` under `suppressed_findings`; if every confirmed finding is
suppressed, RevRem stops with `stopped_reason: "all_findings_suppressed"`
without running remediation and records `suppressed_findings_count` in
`summary.json`. If structured triage returns only `rejected_findings` and no
confirmed or `needs_more_info` items, RevRem stops without remediation only
when there are no pending check failures; otherwise it continues the loop with
the unresolved check context. `revrem doctor` warns about expired suppressions
and unsupported future fingerprint versions.
Bug-report bundles include a redacted suppression audit summary by default; raw
audit logs are included only with the same raw transcript opt-in used for review
transcripts.

### Current CLI boundary

Rich progress is available via `--progress-style rich` when the optional
`progress` extra is installed. The `tui` extra includes Rich as well as
Textual. In Rich output, the active run is maintained in a compact in-place
RevRem panel with the most recent events only. The timestamp is dimmed, the
phase/action word and status word are highlighted, labels are cyan, and model
or review text is rendered literally so markup-like review output cannot break
the display. Terminal-title escape output is suppressed in Rich mode because
some terminals render OSC title bytes inside the live panel instead of consuming
them.

`revrem ui` is available as a dependency-gated Textual interface:

```bash
./.venv/bin/pip install -e ".[tui]"
./.venv/bin/revrem ui
./.venv/bin/revrem ui --profile final-pr
```

Without the `tui` extra, `revrem ui` exits cleanly with an installation hint.
The CLI remains the authoritative execution path. The TUI renders Home,
Profiles, Pipeline, Run Monitor, and Controls views from dependency-free view
models for profiles, recent runs, harness metadata, phase state, command
previews, and artifact links. Use `--profile NAME` to select the initial
profile. Key bindings shell through `revrem config` and the normal run CLI:
`d` dry-runs the selected profile, `s` shows it, `e` edits it, `n` creates a
profile, `c` clones the selected profile, `x` exports, `i` imports from the
path field, `delete` deletes through `revrem config delete --yes`, and `q`
quits.

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
  interrupt manually. Timeout artifacts include the command, cwd, timeout, and
  any partial stdout/stderr captured before the subprocess was killed.
  RevRem starts each child command in its own process group and kills the whole
  group on timeout, so wrappers that leave pipe-holding descendants behind do
  not block artifact creation indefinitely.
- Ensure `--base` names a local commit that shares history with `HEAD`. During
  branch-topology transitions, a stale local `main` can be unrelated to the
  active PR branch even when `origin/main` is correct. RevRem preflights this
  with `git merge-base HEAD <base>` and fails before launching Codex when the
  base is invalid.
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
  terminal compatibility. In Rich progress mode, phase title updates are
  suppressed to avoid leaking OSC bytes into the live progress panel; use
  compact or verbose progress when terminal-tab title updates are more valuable
  than the Rich panel.
  Terminals that ignore those sequences will still run normally. RevRem also
  emits the cursor-show control on normal exit, termination, and terminal
  suspension signals so a forced stop is less likely to leave the cursor hidden.
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
| 1.5 | 2026-05-12 | Codex | Documented suppression CLI, repo/user suppression scope, critical suppression guardrails, and structured-triage suppression behavior |
| 1.4 | 2026-05-12 | Codex | Documented commit hook failure policies, default bounded remediation retry, and explicit `--no-verify` recording |
| 1.3 | 2026-05-06 | Codex | Clarified that the profile wizard prompts separately for review and remediation models |
| 1.2 | 2026-05-06 | Codex | Documented the `config new` interactive wizard, non-interactive automation path, and current stable smoke expectations |
| 1.1 | 2026-05-06 | Codex | Documented CLI-backed TUI profile lifecycle actions, `config clone`, and current TUI controls |
| 1.0 | 2026-05-03 | Codex | Documented negative boolean CLI overrides, `.revrem/runs` artifact namespace, commit-message harness profile setting, Rich live progress, terminal recovery, timeout diagnostics, and import-default preservation semantics |
| 0.9 | 2026-05-03 | Codex | Documented the completed first TUI slice with profile selection, operator sections, and dry-run launch action |
| 0.8 | 2026-05-03 | Codex | Documented adaptive pytest skipping for non-Python repositories and native TypeScript check guidance |
| 0.7 | 2026-05-03 | Codex | Documented TUI launch-plan and run-monitor artifact state |
| 0.6 | 2026-05-03 | Codex | Added release/version promotion guidance and documented sandbox tagging behavior |
| 0.5 | 2026-05-02 | Codex | Documented harness adapter boundary and TUI profile command previews |
| 0.4 | 2026-05-02 | Codex | Documented Rich progress column styling and current dependency-gated TUI shell behavior |
| 0.3 | 2026-05-02 | Codex | Added profile-based usage, config commands, current harness/triage boundary, history/progress hardening, and verified commit-after-remediation guidance |
| 0.2 | 2026-05-01 | Codex | Updated usage guidance for stable `revrem` entry point, dev/stable install boundary, terminal title progress, and current CLI limitations |
| 0.1 | 2026-04-30 | GitCmurf | Initial draft |
