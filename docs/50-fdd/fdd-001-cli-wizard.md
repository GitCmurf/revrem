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
- The first screen distinguishes `no-profile` merged defaults from profiles
  named `default`, shows compact config sources, and previews the default
  command before asking for input.
- Pressing Enter on the first screen selects the recommended command and
  continues to normal confirmation; it does not start provider calls by itself.
- After selecting a starting config, the wizard shows a line-oriented run-shape
  preview with the generated command, base branch, review, triage, routing,
  remediation loop, checks, final review, commit-message drafting, output, and
  budgets.
- Model-calling phases are shown as `harness:model(effort)` so cost/quota
  choices are visible before the operator accepts the command.
- The normal path accepts the preview. Edit screens cover essentials
  (base branch, iterations, checks, final review, output, wall-clock budget)
  and phase settings (triage, routing, model/effort overrides, timeouts,
  auto-commit, pending-review handling).
- Routing is presented as "use profile routing policy" only when the selected
  config defines routes. The wizard does not offer routing for defaults with no
  routes, preventing generated commands that fail on the built-in
  `midtier-coder` default route.
- Verification checks default to the selected profile when present. Otherwise
  the wizard offers detected repo presets such as `./scripts/dev-check`,
  Python pytest/static checks, Meminit DocOps checks, and `git diff --check`;
  manual shell commands are available as an explicit custom option.
- The final action is run, dry-run, save-profile, print, or cancel.
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
- `revrem --wizard` feeds the generated argv back into the normal CLI path.
- Bare `revrem` dispatches to the wizard only in interactive terminals.
- Cancellation exits before provider calls with the standard operator-cancel
  code.
- The run-shape preview includes effective review, triage, remediation,
  routing, commit, check, and output settings so operators can see what a
  profile will run before accepting it.
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
