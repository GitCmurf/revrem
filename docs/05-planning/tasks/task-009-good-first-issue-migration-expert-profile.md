---
document_id: REVREM-TASK-009
type: TASK
title: Good First Issue Migration Expert Profile
status: Draft
version: '0.1'
last_updated: '2026-06-23'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Starter issue to propose a migration-focused expert profile.
keywords:
- good-first-issue
- expert-profiles
related_ids:
- REVREM-PLAN-005
---

# TASK: Good First Issue Migration Expert Profile

## Context

The Tier 2 expert profiles cover security, performance, refactor, test gaps,
and docs drift. A migration-focused profile is a good follow-on because it is
useful but does not need to block the v0.5.0 release.

## Content

## Acceptance Criteria

- Propose a `migration` profile TOML under `src/code_review_loop/expert_profiles/`
  with `pipeline.checks = []` by default.
- Add a short migration checklist prompt fragment focused on schema/data/API
  compatibility risks.
- Extend the expert-profile validation tests and expected overlap fixture.
- Document the profile intent and recommended checks in `REVREM-DEVEX-001`.
- Do not claim real-model distinctness without adding or updating the skipped
  live-smoke evidence path.
