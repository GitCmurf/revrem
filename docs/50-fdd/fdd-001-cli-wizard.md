---
document_id: REVREM-FDD-001
type: FDD
title: CLI Wizard
status: Draft
version: '0.1'
last_updated: '2026-06-13'
owner: GitCmurf
docops_version: '2.0'
area: cli
description: Dependency-free terminal wizard for building RevRem commands from repo
  defaults and profiles
keywords:
- wizard
- cli
- profiles
related_ids:
- REVREM-PRD-001
---

# FDD: CLI Wizard

## Context

RevRem has a powerful CLI, a profile system, and an optional Textual TUI, but
the TUI work was postponed while secondary harnesses and routing were built
out. Human operators still need a bridge that reduces flag memorization without
adding a runtime dependency or bypassing the existing CLI/config path.

## Content

### Goal

Add a dependency-free terminal wizard that builds a normal `revrem` command
from repo defaults, project/user profiles, and explicit operator choices. The
wizard should guide common PR-readiness runs while preserving the existing CLI
as the source of truth for validation, execution, profile saving, artifacts,
and run history.

### Behavior

- `revrem --wizard` always opens the wizard.
- Bare `revrem` opens the wizard only when stdin and stdout are interactive
  TTYs; non-interactive invocations keep the existing default CLI behavior.
- The wizard starts from resolved defaults or a named profile and emits a
  minimal command: accepted profile/default values are not repeated as flags.
- If local run history contains a compatible run for the current repository,
  the wizard offers those last settings before the profile/default starting
  point. The recovered settings are replayed from the saved invocation command
  through the normal CLI parser.
- The first screen is the recommended run-shape diagram. Profile selection is
  available from "choose another profile" and distinguishes `no-profile`
  merged defaults from profiles named `default`.
- The run-shape preview is built from the same phase command builders used at
  runtime, including review, triage, remediation, routed remediation, and
  commit-message drafting provider CLI commands.
- Model-calling phases are shown as `harness:model(effort)`. If a command
  omits `--model`, the wizard resolves trusted provider defaults when
  available; Codex defaults come from `$CODEX_HOME/config.toml` or
  `~/.codex/config.toml`.
- If a model cannot be resolved, the preview marks `model unresolved` and the
  wizard blocks run, dry-run, and save-profile actions until the operator
  chooses an explicit model.
- The preview includes the generated RevRem command, base branch, outer
  remediation pass limit, terminal output mode, review, triage, routing,
  remediation, verification checks, inner check retry policy, conditional
  commit-message drafting, final-review behavior, and budgets.
- The normal path accepts the preview. Edit screens cover run settings
  (base branch, pass limit, checks, final review, output, wall-clock budget)
  and model settings. Model settings are presented as a phase table: review,
  triage, remediation, and commit-message drafting each expose their own
  harness, model, and reasoning effort.
- Timeouts are edited from a separate main-menu option. The wizard uses the
  existing shared `--timeout-seconds` flag for review, remediation,
  commit-message drafting, and shell checks, and accepts `0` to disable those
  subprocess timeouts.
- Generated commands use phase-specific flags for phase-specific edits, for
  example `--review-reasoning-effort`,
  `--remediation-reasoning-effort`, `--triage-model`, and
  `--commit-message-model`, instead of applying one shared model or effort to
  every provider phase.
- Disabled triage is shown as a setup action. Selecting it enables triage,
  prompts for triage harness/model/effort, and then handles routing only when
  profile routes exist.
- Profiles without routes explain how to choose or create a routed profile
  instead of only saying routing is unavailable. This repository's project
  `default` profile keeps triage opt-in but includes v2 route definitions.
- Harness prompts are bounded to known RevRem harnesses so invalid input is
  rejected before preview rebuild.
- Suspicious model names, including bare numbers and unknown-looking names,
  require confirmation before they are stored.
- Routing is presented as "use profile routing policy" only when the selected
  config defines routes. The wizard does not offer routing for defaults with no
  routes, preventing generated commands that fail on the built-in
  `midtier-coder` default route.
- Verification checks default to the selected profile when present. Otherwise
  the wizard offers detected repo presets such as `./scripts/dev-check`,
  Python pytest/static checks, Meminit DocOps checks, and `git diff --check`;
  manual shell commands are available as an explicit custom option.
- The final action is run, dry-run, save-profile, print, or cancel.
- The command confirmation line uses stdout only for `print`; `run`,
  `dry-run`, and `save-profile` keep stdout reserved for the normal CLI
  output path, including JSON summaries.
- Generated commands are parsed and validated through the existing
  `parse_args` and `build_loop_config` path before the operator confirms them.
- `Ctrl-C`, EOF, `q`, `quit`, and `cancel` exit cleanly before provider calls.
- When Rich is installed and stderr is a color-capable TTY, headings, default
  markers, and command previews use color; plain text remains the fallback and
  `NO_COLOR` disables Rich styling.

### Acceptance Criteria

- Scripted tests prove default profile choices produce a minimal
  `revrem --profile NAME --dry-run` command.
- Scripted tests prove common and advanced overrides produce the expected argv
  and shell-quoted command preview.
- Scripted tests prove review, triage, remediation, and commit-message model
  settings can be changed independently.
- Scripted tests prove last-run settings can be offered, disabled triage can
  be enabled, shared timeout can be set to `0`, suspicious model input is
  confirmed, and invalid harness input is reprompted without a traceback.
- Scripted tests prove routed preview commands use runtime fallback resolution
  instead of blocking profiles that can run through a configured fallback.
- `revrem --wizard` feeds the generated argv back into the normal CLI path.
- Bare `revrem` dispatches to the wizard only in interactive terminals.
- Cancellation exits before provider calls with the standard operator-cancel
  code.
- The run-shape preview includes effective review, triage, remediation,
  routing, commit, check, and output settings so operators can see what a
  profile will run before accepting it.
- Scripted tests prove command-builder-derived provider commands and models
  appear in the run-shape preview.
- Scripted tests prove unresolved non-Codex provider models block provider
  actions.
- Scripted tests prove defaults without routes cannot enable routing through
  the wizard.
- Scripted tests prove repo check presets are detected and selectable.
- `README.md` documents the wizard beside profiles and the postponed optional
  TUI.

### Verification

```bash
./.venv/bin/pytest -q tests/test_cli_wizard.py tests/test_cli_dispatch.py
./scripts/dev-check
uv run --locked meminit check --format json
```
