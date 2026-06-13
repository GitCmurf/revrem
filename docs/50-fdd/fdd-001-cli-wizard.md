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
- Common prompts cover base branch, max iterations, checks, final review, and
  the final action: run, dry-run, save-profile, print, or cancel.
- Advanced prompts cover structured triage, routing, model/effort overrides,
  timeouts, auto-commit, progress style, summary format, wall-clock budget, and
  pending-review handling.
- Generated commands are parsed and validated through the existing
  `parse_args` and `build_loop_config` path before the operator confirms them.

### Acceptance Criteria

- Scripted tests prove default profile choices produce a minimal
  `revrem --profile NAME --dry-run` command.
- Scripted tests prove common and advanced overrides produce the expected argv
  and shell-quoted command preview.
- `revrem --wizard` feeds the generated argv back into the normal CLI path.
- Bare `revrem` dispatches to the wizard only in interactive terminals.
- Cancellation exits before provider calls with the standard operator-cancel
  code.
- `README.md` documents the wizard beside profiles and the postponed optional
  TUI.

### Verification

```bash
./.venv/bin/pytest -q tests/test_cli_wizard.py tests/test_cli_dispatch.py
./scripts/dev-check
uv run --locked meminit check --format json
```
