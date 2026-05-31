---
document_id: REVREM-TASK-006
type: TASK
title: Secondary harness live provider proof and hardening
status: Draft
version: '0.1'
last_updated: '2026-05-31'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Follow-up task for proving and hardening live secondary harness
  execution after the deterministic routed-remediation slice in REVREM-PLAN-004.
keywords:
- revrem
- harnesses
- provider-smoke
- claude
- gemini
- opencode
- kilo
- routing
related_ids:
- REVREM-PLAN-004
- REVREM-PLAN-003
- REVREM-ADR-010
- REVREM-TASK-004
---

# TASK: Secondary harness live provider proof and hardening

## Context

`REVREM-PLAN-004` completed the deterministic first routed-remediation slice:
triage v2 schemas, routing artifacts, prompt construction, policy linting,
fake-harness proof, and thin command adapters for Codex, Claude, Gemini,
opencode, and KiloCode are implemented and locally tested.

That does **not** prove that every secondary provider works end-to-end against
real installed CLIs, credentials, model names, provider errors, and live
non-interactive behavior. The live/provider work was previously described only
as a roadmap M6 follow-up, which made PLAN-004 look complete while leaving an
unowned obligation. This task is the concrete governed home for that remaining
M6 work.

## Goal

Prove and harden live secondary harness execution without expanding the common
adapter surface beyond the thin local CLI contract already introduced by
`REVREM-PLAN-004`.

Done means RevRem can route to at least one real secondary provider in a live
smoke when credentials are present, skip unavailable provider tests cleanly in
normal CI, and produce useful diagnostics when secondary-provider setup or
execution fails.

## Content

### Scope

- Add credential-gated live smoke coverage for Claude, Gemini, opencode, and
  KiloCode harnesses.
- Keep live smoke disabled by default unless explicit environment variables are
  set for the provider under test.
- Prove the live smoke writes the expected run artifacts: `summary.json`,
  `events.jsonl`, `routing-<iteration>.json`,
  `remediation-<iteration>-prompt.txt`, and
  `routing-outcome-<iteration>.json` when routing executes.
- Classify provider setup and execution failures clearly: missing executable,
  missing credentials/auth, unsupported model, timeout, cancellation, and
  malformed or empty output.
- Document how operators run, skip, and interpret live provider validation.
- Preserve the deterministic fake-harness and command-shape tests as the normal
  CI contract.

### Non-Goals

- Do not build deep provider-specific feature surfaces.
- Do not add generic HTTP, OpenRouter, hosted service, daemon, telemetry, or
  plugin entry points.
- Do not implement multi-route fan-out inside one loop iteration.
- Do not require live provider credentials for ordinary local development or CI.
- Do not weaken bounded execution, sandbox, budget, or artifact privacy
  controls to make a provider smoke pass.

### Acceptance Criteria

- A provider-gated live test exists for each implemented secondary harness:
  Claude, Gemini, opencode, and KiloCode.
- Each live test skips cleanly by default and runs only when its explicit
  provider opt-in and executable/credential prerequisites are present.
- At least one secondary provider completes an end-to-end routed remediation
  smoke in the maintainer environment and records the run directory in the task
  closeout evidence.
- Missing or unavailable provider routes fail or fall back with clear
  diagnostics and do not look like generic internal errors.
- Provider-specific command/prompt delivery remains covered by deterministic
  unit tests, independent of live credentials.
- `REVREM-DEVEX-001` documents the live smoke commands, required environment
  variables, expected skip behavior, and how to read routing artifacts.
- `REVREM-PLAN-003` M6 progress is updated from "partially complete" only after
  this task's closeout evidence exists.
- `meminit check --format json` and the focused harness/routing test suite pass.

### Verification Commands

```bash
meminit check --format json
./.venv/bin/pytest -q \
  tests/test_harnesses.py \
  tests/test_harness_adapters.py \
  tests/test_routing_artifacts.py \
  tests/test_cli_v2.py \
  tests/test_tui_state.py
```

Provider-gated live commands are defined by the implementation PR. They must be
off by default, named per provider, and documented in `REVREM-DEVEX-001`.
