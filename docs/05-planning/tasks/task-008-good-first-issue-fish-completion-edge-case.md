---
document_id: REVREM-TASK-008
type: TASK
title: Good First Issue Fish Completion Edge Case
status: Draft
version: '0.1'
last_updated: '2026-06-23'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Starter issue to harden fish completion behavior.
keywords:
- good-first-issue
- completions
related_ids:
- REVREM-PLAN-005
---

# TASK: Good First Issue Fish Completion Edge Case

## Context

RevRem now emits fish completions, but shell completions tend to accumulate
edge cases around quoted flags, profile names, and subcommand-specific options.

## Content

## Acceptance Criteria

- Add a failing test that captures one fish completion edge case before fixing
  it.
- Keep `revrem completions fish` deterministic and dependency-free.
- Ensure the completion still includes `report`, `config`, `--profile`, and
  `--no-tty`.
- Update the completions documentation if installation guidance changes.
