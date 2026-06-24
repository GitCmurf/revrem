---
document_id: REVREM-TASK-007
type: TASK
title: Good First Issue GitLab CI Example
status: Draft
version: '0.1'
last_updated: '2026-06-23'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Starter issue to add a GitLab CI example for RevRem.
keywords:
- good-first-issue
- ci
related_ids:
- REVREM-PLAN-005
---

# TASK: Good First Issue GitLab CI Example

## Context

RevRem ships a reference GitHub Action, but teams using GitLab CI need a
copy-pasteable shell example that keeps the same privacy and boundedness
defaults.

## Content

## Acceptance Criteria

- Add `examples/gitlab-ci/.revrem.toml` and `examples/gitlab-ci/README.md`.
- Include a minimal `.gitlab-ci.yml` snippet that installs RevRem, runs
  `revrem --no-tty --progress-style compact --summary-format json`, renders
  `revrem report`, and uploads only the redacted HTML report by default.
- Document that raw run artifacts are opt-in because they are not redacted.
- Add or extend an examples validation test so the profile remains parseable.
- Update `REVREM-DEVEX-001` with a short GitLab CI pointer.
