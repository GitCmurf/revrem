---
document_id: REVREM-DEVEX-001
type: DEVEX
title: Using code-review-loop
status: Draft
version: '1.27'
last_updated: '2026-06-03'
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
> **Version:** 1.27
> **Last Updated:** 2026-06-03
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
  --max-wall-seconds 7200 \
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
Each `summary.json` also records `git_state` for resume safety: current `HEAD`,
configured base ref, resolved base commit, merge base, and whether those values
were available. Repositories without a Git worktree record explicit `null`
values instead of pretending a resume precondition was checked.
When `--max-wall-seconds` is set, the summary also stores the cumulative wall
seconds already spent so a resumed run continues against the same total wall
budget instead of starting a fresh ceiling.
`revrem resume <run-dir>` validates the resume preconditions and returns code
`4` when the summary, event stream, `HEAD`, or base commit do not match. When
the checks pass, it rebuilds the loop config from `resume_config`, starts from
the latest review artifact as `review-initial.txt`, and avoids re-running
completed review phases. Resume uses the recorded review artifact path from
`summary.json` as written so default relative artifact directories keep working;
older summaries that only stored a bare filename still fall back to the run
directory.

For richer watched-terminal output, install the optional progress extra and use
`--progress-style rich`:

```bash
./.venv/bin/pip install -e ".[progress]"
./.venv/bin/revrem --profile final-pr --progress-style rich
```

If Rich is requested but unavailable, RevRem prints one warning and falls back to
compact progress. Existing commands do not need to change.

For workflows that want an additional secret scanner alongside RevRem's built-in
bug-bundle redaction regexes, install the optional redaction extra:

```bash
./.venv/bin/pip install -e ".[redaction]"
```

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
mutating tracked ignore files. When the ignore entry is already present, RevRem
returns before taking the exclude-file write lock so no-op setup works in
read-only Git metadata environments. Linked worktrees use the common
repository's `.git/info/exclude`.
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
under that directory instead of the default workspace-local tree. `latest` uses
the newest compatible usable generated review artifact from a non-clear run,
including interrupted runs that have `review-1.txt`, `review-2.txt`, or later
iteration reviews but no `review-final.txt`. Imported `review-initial.txt`
artifacts are ignored so a restart does not keep reusing stale carried-in
feedback. When run summaries include git state, `latest` skips artifacts from a
different current `HEAD` or base. If the newest compatible run's `summary.json`
reports `final_status = "clear"`, or there is no previous generated review,
RevRem starts with a fresh review instead of reviving older feedback.

### Profile-based usage

Profiles live in `~/.config/revrem/profiles.toml`. Project-local overrides live
in `.revrem.toml` at the target repository root, so subdirectory invocations
still pick up the same project settings. If a temporary filesystem root such as
`/tmp` contains an incidental `.git` marker, RevRem ignores that marker when
discovering project config so isolated scratch work can still use its local
`.revrem.toml`. User-global `[defaults]` entries in
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

[profiles.final-pr.suppressions]
scope = "repo"
```

Run it from the target repository:

```bash
revrem --profile final-pr
```

CLI flags override profile values, so this is valid:

```bash
revrem --profile final-pr --base release/1.2 --check "pytest -q tests/smoke"
```

This repository also carries a project-local `dogfood` profile in
`.revrem.toml`. It is intentionally not a portable profile: it runs the full
local verification stack, enables commits, turns on triage v2 routing, records
debug status diagnostics, and uses explicit phase models so RevRem can exercise
its own operator surface. The normal Codex-only dogfood run is:

```bash
./.venv/bin/revrem --profile dogfood --base main --max-iterations 3
```

The profile includes an optional Gemini route for multi-file changes. Use it
only when Gemini CLI and credentials are available; otherwise the Codex routes
remain sufficient for local dogfood:

```bash
./.venv/bin/revrem \
  --profile dogfood \
  --base main \
  --max-iterations 2 \
  --harness-bin gemini=gemini \
  --triage \
  --routing
```

To dogfood Gemini deliberately instead of waiting for routing policy to select
it, force the profile's Gemini route from the CLI:

```bash
GEMINI_CLI_TRUST_WORKSPACE=true \
./.venv/bin/revrem \
  --profile dogfood \
  --base main \
  --max-iterations 3 \
  --harness-bin gemini=gemini \
  --routing \
  --routing-strict \
  --route gemini-pro
```

That command verifies the route machinery calls Gemini for routed remediation,
passes the same triage-prescribed prompt context that Codex would receive, and
records the selected harness in `routing-N.json` and `phase_config`.

Dogfood summaries include a `phase_config` object for review, triage,
remediation, commit-message drafting, and checks. Each phase records the
resolved harness, model, effort, timeout, sandbox where relevant, and whether
the effective value came from CLI flags, the selected profile, or defaults.
Explicit unbounded timeouts are shown as `0` in this operator-facing projection
even though the subprocess layer receives `None`.

Terminal progress and closeout output repeat phase provenance on line-wrapped
messages so line-oriented tools can still grep for phase markers such as
`|tri|`, `contract=v2`, and `source=mixed`. Suggested resume commands preserve
one-off triage, routing, model, harness, effort, and explicit timeout overrides
so a profile-less dogfood run can be resumed without silently dropping the
operator's control surface.

Commit-message drafting disables Codex web search for that read-only helper
call so `--commit-reasoning-effort minimal` can be tested without inheriting
tool settings from local Codex defaults. If model drafting still fails, RevRem
records the fallback in `commit-N-message-fallback.json`, includes it in the
summary, and uses a deterministic repository-generic Conventional Commit
subject derived from staged paths plus review/remediation context rather than an
iteration-only placeholder or RevRem-specific canned vocabulary.
For the Codex commit-message harness, `minimal` is promoted to `low` at config
resolution time only for known commit-message models that reject
`reasoning.effort=minimal`; `low` is the lowest live-compatible drafting effort
for those models. Summaries record both `requested_reasoning_effort` and the
effective `reasoning_effort`, and progress emits a `config-adjusted` event when
the promotion is applied.

Credentialed environments can continuously smoke-test the live Codex
commit-message path:

```bash
REVREM_LIVE_CODEX=1 ./.venv/bin/pytest -q tests/test_live_codex_commit_message.py
```

Credentialed environments can also smoke-test the secondary harness adapters.
These tests are skipped by default and run only when the provider-specific
opt-in is set:

```bash
./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py

REVREM_LIVE_GEMINI=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
REVREM_LIVE_CLAUDE=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
REVREM_LIVE_OPENCODE=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
REVREM_LIVE_KILO=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
```

Use `REVREM_LIVE_<PROVIDER>_MODEL` to override the CLI's default model and
`REVREM_LIVE_<PROVIDER>_BIN` when the executable is not on `PATH`, for example
`REVREM_LIVE_GEMINI_MODEL=gemini-3-flash` or
`REVREM_LIVE_CLAUDE_BIN=/opt/claude/bin/claude`. The routed live smoke defaults
to Gemini; set `REVREM_LIVE_ROUTED_PROVIDER=claude`, `opencode`, or `kilo` to
exercise another secondary provider. The routed smoke uses a temporary
workspace, a fake review/triage front half, and the selected live provider only
for routed remediation. The Gemini live smoke sets
`GEMINI_CLI_TRUST_WORKSPACE=true` for the pytest process because Gemini refuses
headless execution from pytest temporary directories unless the workspace is
trusted.

To capture a one-off command as a project-local profile, add
`--save-profile NAME`. RevRem writes the effective configuration to
`.revrem.toml` at the repository root and exits without running the loop. This
is non-destructive by default; pass `--save-profile-force` only when replacing
an existing project profile intentionally. Explicit `--timeout-seconds 0`
settings are written back as `timeout_seconds = 0` so a saved profile keeps the
no-timeout behavior. When the source profile uses v2 triage routing,
`--save-profile` preserves the triage contract, routing rules, route table, and
effective `runtime.harness_executables` map, including any one-off
`--harness-bin HARNESS=EXECUTABLE` overrides supplied on the same command.

Project profile discovery intentionally ignores system temp roots and their
ancestors when walking for `.git`. This prevents an ambient `/tmp/.git` marker
from making every temporary test directory appear to be part of a repository.

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
`--max-iterations` and profile `pipeline.max_iterations` must be positive
integers; invalid values fail before the review/remediation loop starts.
Generated TOML config output rejects non-finite floats instead of writing
non-portable `nan` or `inf` tokens.
When terminal title refresh is enabled, the subprocess wrapper keeps waiting on
the same child after a timeout without resending stdin, which avoids the
`communicate()` retry error on long-running stdin-driven phases.
Profile `review.reasoning_effort` and `remediation.reasoning_effort` values are
validated during profile loading and must be one of `minimal`, `low`, `medium`,
or `high`.

### Budgets

`--timeout-seconds` bounds individual child processes. `--max-wall-seconds`
bounds the total RevRem run and is checked before each model-invoking phase.
When the wall-clock ceiling has already been reached, RevRem stops before the
next model call, writes `summary.json` and `events.jsonl`, emits
`cost_ceiling_hit`, and exits with code `3`.

`--soft-warn-fraction` controls the warning threshold for configured ceilings
and defaults to `0.8`. `--max-tokens` and `--max-usd` are enforced once a
harness reports usage through `cost_charge`; Codex does not currently report
those values, so summaries record token and USD usage as `null` until a charge
is observed rather than pretending unsupported accounting is zero usage.

Profiles may set the same defaults:

```toml
[profiles.final-pr.budgets]
max_wall_seconds = 7200
max_tokens = 250000
max_usd = "2.50"
soft_warn_fraction = 0.8
```

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
`summary.json`, diagnostics/event JSON when present, sanitized check output,
status diagnostics, and sanitized profile/preflight snapshots when the run
recorded them.
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
preflight is clear. It warns when a profile explicitly disables a phase timeout
with `timeout_seconds = 0` and when the current locale is not UTF-8 capable,
because both conditions make unattended artifact generation less predictable.
Regenerate the diagnostics table with `scripts/dev-render-diagnostics` after
adding or changing diagnostic codes.

Normal live CLI runs use the same diagnostics path before the first model call.
When setup preflight blocks execution, RevRem writes `diagnostics.json`,
`summary.json`, and `events.jsonl` under the run artifact directory and exits
with code `4` without invoking review or remediation.

These management commands validate harness names, triage syntax, routing rules,
and route capability chains without invoking a model. Executable runs still
fail before remediation when the selected route names an unimplemented or
incapable harness without an explicit valid fallback.

The `--format` flag is accepted both before and after the subcommand, so the
global form `revrem config --format json doctor --profile final-pr` works too.

Profiles use `review.harness`, `triage.harness`, `remediation.harness`, and
`commit.harness` to select headless adapters. Codex, Claude, Gemini, opencode,
and KiloCode are executable when their installed CLIs satisfy the declared
capabilities. Override non-default executable names from the profile:

```toml
[profiles.multi.runtime.harness_executables]
claude = "/opt/claude/bin/claude"
gemini = "gemini-dev"
```

or for a single run:

```bash
revrem --profile multi --harness-bin claude=/opt/claude/bin/claude
```

Harnesses expose a schema-validated capability payload that records supported
phases, sandbox modes, timeout/cancellation support, structured output, and
cost reporting mode. Codex currently reports `cost_reporting = "none"`, so
token/USD budgets remain declared ceilings until a cost-aware harness emits
charges. The `fake` harness is reserved for deterministic test fixtures and is
hidden unless `REVREM_ALLOW_FAKE_HARNESS=1` is set. When enabled, it replays
local fixture files through RevRem's runner boundary and never shells out; it
is for tests and contract development, not production review.

Set `commit.enabled = true` or pass `--commit-after-remediation` only in a
worktree where it is acceptable for RevRem to stage all current changes with
`git add -A` after a verified remediation pass, while excluding the configured
artifact directory from staging. If a profile enables commits by default but a
single invocation should remain dry, pass `--no-commit-after-remediation` to
override that profile setting. The commit step is separate from the remediation
model: checks must pass first, RevRem skips the commit if there are no staged
changes, and RevRem runs `git commit` itself. The optional `commit.harness`
field selects the commit-message drafting adapter. Pass
`--commit-message-harness` to override that drafting harness for one run. The
optional `commit.message_model` or `--commit-message-model` controls only the
read-only model call that drafts the commit subject. If no explicit
CLI value is supplied, the profile value is used; the built-in profile default
is `gpt-5.3-codex-spark`. With the default
prompt, RevRem normalizes the final subject to Conventional Commit syntax and
appends `(RevRem)`. If the commit-message model returns explanatory prose
instead of a subject, RevRem records `commit-N-message-fallback.json` with
`reason: "model_drafting_invalid"` and uses the deterministic fallback subject
instead of committing the prose. Harnesses that can extract a concise subject
from their own transcript may write `commit-N-message-subject.txt`; RevRem
prefers that sidecar over the raw draft transcript. Passing
`--commit-message-prompt` intentionally disables that default subject policy so
special-purpose commit formats can be tested without fighting the normalizer.
If a verified remediation pass produces no staged changes after checks pass,
RevRem stops the loop immediately with
`final_status: "clear"` and
`stopped_reason: "no_changes_after_remediation"`; the passing checks plus zero
staged diff are treated as deterministic clear evidence when the preceding
review status was still `unknown`. Auto-commit also requires a clean worktree
before the loop starts so unrelated local edits cannot be staged by the broad
`git add -A` step.

Commit hooks are part of the commit phase, not an afterthought. When `git
commit` appears to fail inside hooks, RevRem defaults to `commit.on_hook_failure
= "remediate"`: it leaves staged changes intact, records the hook output in
`commit-N.txt`, and injects that output into the next bounded remediation pass.
Use `commit.on_hook_failure = "stop"` or `--commit-on-hook-failure stop` when a
hook failure should end the run immediately with `stopped_reason:
"commit_hook_failed"`. Use `no-verify` only for explicit operator-controlled
flows; RevRem records that policy as `commit_no_verify: true` in `summary.json`
and runs `git commit --no-verify`. Once a later remediation pass and commit
succeed, RevRem clears `pending_check_failures` before writing `summary.json`
so the final status and summary flags stay aligned.

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

Optional triage can run between review and remediation. It uses the configured
triage harness in read-only mode, writes `triage-N.txt` beside the review and
remediation artifacts, and passes a concise handoff plus the original
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

For routing, use `triage.contract = "v2"` plus
`triage.routing.enabled = true`. RevRem validates `triage-v2`, resolves the
effective route through profile policy, writes `routing-N.json`,
`remediation-N-prompt.txt`, and `routing-outcome-N.json`, and emits
`routing_decision` / `routing_outcome` events into `events.jsonl`. Prompt and
routing artifacts are also listed under `summary.artifact_paths.prompts` and
`summary.artifact_paths.routing` for auditability; treat prompt artifacts as
sensitive transcript-like local data. In `routing-N.json`, `prompt.bytes` is
the UTF-8 byte size of the written prompt artifact, and
`effective_route.timeout_seconds` records the timeout RevRem will pass to
remediation execution after inheritance; `0` means unbounded.

Codex-only routing profile:

```toml
[profiles.secure.triage]
enabled = true
contract = "v2"
harness = "codex"
model = "gpt-5.4-mini"

[profiles.secure.triage.routing]
enabled = true
default_route = "midtier-coder"

[[profiles.secure.triage.routing.rule]]
id = "security-frontier"
when.domain_tags_any = ["security", "auth", "secrets", "pii"]
then.route = "frontier-thinking"
then.allow_model_deescalation = false
then.prompt_fragments = ["engineering-principles", "security-checklist"]

[profiles.secure.triage.routes.frontier-thinking]
harness = "codex"
model = "gpt-5.5"
reasoning_effort = "high"
timeout_seconds = 1800
sandbox = "workspace-write"

[profiles.secure.triage.routes.midtier-coder]
harness = "codex"
model = "gpt-5.4-mini"
reasoning_effort = "medium"
timeout_seconds = 900
sandbox = "workspace-write"
```

Multi-harness routing profile:

```toml
[profiles.multi.runtime.harness_executables]
claude = "claude"
gemini = "gemini"
opencode = "opencode"
kilo = "kilo"

[profiles.multi.triage]
enabled = true
contract = "v2"
harness = "gemini"
model = "gemini-3-flash"

[profiles.multi.triage.routing]
enabled = true
default_route = "midtier-coder"

[[profiles.multi.triage.routing.rule]]
id = "sensitive-frontier"
when.safety_signals_any = ["sensitive-domain:auth", "sensitive-domain:secrets"]
then.route = "frontier-thinking"
then.allow_model_deescalation = false

[profiles.multi.triage.routes.frontier-thinking]
harness = "claude"
model = "sonnet"
reasoning_effort = "high"
timeout_seconds = 1800
sandbox = "workspace-write"
fallback = "midtier-coder"

[profiles.multi.triage.routes.midtier-coder]
harness = "gemini"
model = "gemini-3-flash"
reasoning_effort = "medium"
timeout_seconds = 900
sandbox = "workspace-write"
fallback = "efficient-coder"

[profiles.multi.triage.routes.efficient-coder]
harness = "kilo"
model = "provider/model"
timeout_seconds = 300
sandbox = "workspace-write"
```

Use `revrem policy lint --profile multi` to verify rule and fallback chains,
`revrem triage explain <run-dir>` to inspect one routing decision, and
`revrem policy review --artifact-dir <run-dir>` to summarize route outcomes
without printing full prompts.
For live routed smoke tests, inspect the temporary run directory reported by
pytest on failure or rerun with `-s` while debugging. A successful routed smoke
writes `summary.json`, `events.jsonl`, `routing-1.json`,
`remediation-1-prompt.txt`, `remediation-1.txt`, and
`routing-outcome-1.json`; `routing-1.json.effective_route.harness` identifies
the selected secondary provider.

For one-off dogfood runs, CLI flags can override the profile's triage and
routing controls without editing `.revrem.toml`:

```bash
revrem --profile dogfood --triage --triage-contract v2 --routing
revrem --profile dogfood --routing --route gemini-pro
revrem --profile dogfood --no-triage --no-routing --dry-run --summary-format json
revrem --profile dogfood --no-allow-model-escalation
```

Use `--review-harness`, `--triage-harness`, `--remediation-harness`, and
`--commit-harness` to override the per-phase harnesses. Use `--triage-model`,
`--triage-timeout-seconds`, and the phase-specific model/effort flags to
override model context. Use `--route` to force an existing route from the
selected profile for one run, and `--routing-strict` or `--no-routing-strict`
to control whether an unavailable selected route is a hard failure. When strict
routing is enabled, RevRem stops on the selected route's capability or budget
failure even if that route names a fallback. Disabled routing may carry draft
routes during normal runs, but references inside the route table are still
validated.

Executable route validation is opt-in when routing is disabled:

```bash
revrem policy lint --profile dogfood --executable-routes
revrem doctor --profile dogfood --validate-routes
```

Use those checks before enabling a draft Gemini or Claude route. Without the
opt-in flag, normal lint and doctor runs do not require disabled draft route
harnesses to be installed.

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
the unresolved check context. If a suppression file cannot be parsed or read,
structured triage emits a warning and continues without applying suppressions.
`revrem doctor` warns about expired suppressions and unsupported future
fingerprint versions.

Profiles can declare the expected suppression write policy:

```toml
[profiles.final-pr.suppressions]
scope = "repo"
```

`scope = "repo"` is the default and keeps project-wide dismissals reviewable in
the repository. `scope = "user"` is for personal local dismissals that should
not affect other operators. Explicit `revrem suppress add --scope ...` usage
still controls each mutation.
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

Codex, Claude, Gemini, opencode, and KiloCode are executable
review/remediation harnesses through the shared adapter boundary. Their CLIs
must be installed and discoverable through `PATH`,
`runtime.harness_executables`, or `--harness-bin`. Reserved harness names
remain valid management syntax but fail fast on executable runs.

External review harnesses do not have Codex's native `codex review --base`
command, so RevRem supplies a review prompt that includes base/working-directory
metadata plus a generated read-only context bundle: `git status --short`,
`git diff --stat <base>...HEAD`, `git diff --name-status <base>...HEAD`,
`git diff <base>...HEAD`, `git diff --cached`, and `git diff`. This lets Gemini
and other prompted providers review the actual patch even when their headless
read-only mode denies shell tools. External review harnesses must return an
explicit `REVIEW_STATUS` line; Codex native review remains classified through
its finding markers and conservative clear-prose examples because RevRem does
not control the native review prompt. Review is always invoked in read-only
mode; for Gemini this means `--approval-mode plan`. Gemini remediation still
uses `--approval-mode auto_edit` when workspace writes are allowed. Review
prompt and full generated context artifacts are listed under
`summary.artifact_paths.prompts` and `summary.artifact_paths.contexts`; the
review transcript itself remains under `summary.artifact_paths.reviews`. The
provider-facing external review prompt is bounded by
`runtime.external_review_input_chars` / `--external-review-input-chars`; RevRem
trims by character count with an omission marker rather than attempting
provider-specific token accounting. When no CLI/profile cap is set, Gemini Pro
review models use a larger `600000` character cap while other prompted review
harnesses retain the conservative `80000` character default. Phase-start
progress and events report whether the generated review context was supplied
in full or truncated.
If an external review subprocess fails with a known transient provider-side
error, such as an OpenCode server error or a temporary rate-limit response,
RevRem records `review-N-attempt-1.txt`, emits a `review retry` progress event,
and retries that review once. CLI contract errors, auth/setup failures, quota
exhaustion, and Codex native review failures are not retried.

Progress output intentionally summarizes prompt-bearing commands. Phase start
lines show the executable role, model, effort, timeout, sandbox, prompt size,
delivery mode, and config source without repeating raw CLI syntax. For example:
`opencode run · opencode/minimax-m3-free · n/a effort · timeout=0 · sandbox
read-only · prompt=80.0k file · source=profile+cli`. Exact argv and prompt
artifacts remain in `events.jsonl` and the run artifact directory. OpenCode
receives prompt-bearing phases through `opencode run --file <prompt-artifact>`,
plus a short positional instruction, not through stdin, so large RevRem prompts
stay out of process listings and match OpenCode's headless CLI contract.
Long-running
model subprocesses emit `waiting` progress every five minutes without changing
timeout behavior; `timeout=0` still means RevRem does not enforce a subprocess
deadline. For prompted review harnesses, waiting messages add a stronger
diagnostic after `runtime.external_review_warning_seconds` /
`--external-review-warning-seconds` elapses, explaining that provider output is
not available until the subprocess exits. Set
`REVREM_OPENCODE_DEBUG=1` to add OpenCode provider logs
(`--print-logs --log-level INFO`) to OpenCode phase commands during local
diagnosis. When a review reports `findings` without Codex-style `[P1]` finding
bullets, RevRem prints the leading review line before the status so operators
can see the context being passed to triage/remediation. Remediation failures
name the active harness, for example `gemini remediation failed`, and point to
the remediation artifact. Known provider-state failures are called out in the
same error; Gemini CLI quota exhaustion is reported as `provider quota
exhausted`, OpenCode server-side failures include the provider reference when
one is present, and the full CLI stderr remains in the phase artifact.

### Exit codes

- `0`: the loop ended clear.
- `1`: the utility itself failed, for example invalid arguments or a failed
  subprocess invocation.
- `2`: the utility completed but the bounded loop still has findings or pending
  check failures.
- `3`: a configured budget ceiling was reached before the next model call.
- `4`: setup diagnostics blocked execution before the first model call, or a
  resumability precondition failed.
- `5`: the operator cancelled the run with Ctrl-C/SIGTERM and RevRem wrote
  best-effort cancellation artifacts.
- `6`: `revrem doctor --strict` found warning-level diagnostics.

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
- Ctrl-C and SIGTERM are treated as controlled cancellation. RevRem restores
  terminal display state, kills the active child process group through the
  subprocess wrapper, emits a `cancellation` event, writes `summary.json`, and
  exits with code `5`. A repeated Ctrl-C/SIGTERM within five seconds is marked
  as forced cancellation but still follows the same best-effort artifact and
  exit-code path.
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
- `revrem bundle-bug-report` includes `review-N-status.json` status diagnostics
  by default, so you can share the structured status evidence without adding
  the raw transcript unless it is necessary for debugging.
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

## Release Dry Runs And Rollback

RevRem is not published on PyPI until the release workflow has successfully
completed the Trusted Publishing path. Maintainers validate the package path in
three stages:

1. `workflow_dispatch` dry run builds, checks, signs, attests, and uploads
   artifacts without publishing.
2. `vX.Y.Z-rcN` tags publish to TestPyPI.
3. `vX.Y.Z` tags publish to PyPI and create the GitHub Release.

The release workflow validates that the tag matches `__version__` (including
`vX.Y.Z-rcN` tags for PEP 440 `X.Y.ZrcN` release-candidate versions), writes
`SHA256SUMS`, emits build-provenance attestations, and signs artifacts with
Sigstore. Rollback, yanking, and hotfix steps live in
`REVREM-RUNBOOK-001`; the release trust decision is `REVREM-ADR-011`.

### Related documents

- `REVREM-ADR-001` records why this is a Python CLI with companion skill
  guidance rather than a copied script or skill-only implementation.
- `REVREM-ADR-011` records the Trusted Publishing, provenance, and rollback
  release policy.
- `REVREM-RUNBOOK-001` gives the operator checklist for release dry runs,
  TestPyPI/PyPI publication, provenance checks, and rollback.
- `REVREM-PRD-001` defines the profile, progress, and TUI milestones.
- `REVREM-TEST-001` defines the verification gates for this utility.

## Version History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.27 | 2026-06-03 | Codex | Documented OpenCode file attachment plus positional message invocation |
| 1.26 | 2026-06-03 | Codex | Documented Gemini review context cap and external review quiet-run diagnostics |
| 1.25 | 2026-06-03 | Codex | Documented provider-failure review retry and commit-message prose rejection |
| 1.24 | 2026-06-02 | Codex | Documented OpenCode prompt-file delivery and waiting progress diagnostics |
| 1.23 | 2026-06-02 | Codex | Documented compact phase-start progress, OpenCode debug logs, and dedicated external review prompt cap |
| 1.22 | 2026-06-02 | Codex | Documented prompt-size bounds, progress prompt summaries, and provider-specific remediation failure wording |
| 1.21 | 2026-06-02 | Codex | Documented external review diff-context artifacts and no-diff clear evidence |
| 1.20 | 2026-06-01 | Codex | Documented external review prompts and Gemini read-only review invocation |
| 1.19 | 2026-06-01 | Codex | Documented per-phase harness CLI parity and forced Gemini dogfood route selection |
| 1.18 | 2026-06-01 | Codex | Documented Gemini workspace trust and live secondary auth prerequisite behavior |
| 1.17 | 2026-05-31 | Codex | Documented credential-gated secondary harness live smoke tests and routed artifact expectations |
| 1.16 | 2026-05-30 | Codex | Documented model-specific commit-effort promotion and the credential-gated live Codex smoke |
| 1.15 | 2026-05-30 | Codex | Documented repository-generic fallback subjects, visible commit-effort promotion, and broader command-line redaction |
| 1.14 | 2026-05-29 | Codex | Documented resume override fidelity, wrapped progress prefix behavior, and temp-root ancestor exclusion |
| 1.13 | 2026-05-29 | Codex | Documented triage/routing CLI overrides, executable-route validation modes, model-escalation controls, and commit-message harness override |
| 1.12 | 2026-05-29 | Codex | Documented the project-local dogfood profile, resolved phase configuration summaries, and commit-message fallback hardening |
| 1.11 | 2026-05-21 | Codex | Documented positive iteration validation and finite TOML numeric output |
| 1.10 | 2026-05-21 | Codex | Documented temp-root `.git` marker handling during project profile discovery |
| 1.9 | 2026-05-13 | Codex | Documented profile-level suppression scope policy |
| 1.8 | 2026-05-13 | Codex | Documented optional redaction extra alongside progress and TUI extras |
| 1.7 | 2026-05-13 | Codex | Documented live CLI preflight diagnostics before first model invocation |
| 1.6 | 2026-05-13 | Codex | Documented release dry runs, Trusted Publishing stages, provenance artifacts, and rollback runbook linkage |
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
