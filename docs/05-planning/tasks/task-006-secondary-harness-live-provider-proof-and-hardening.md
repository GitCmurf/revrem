---
document_id: REVREM-TASK-006
type: TASK
title: Secondary harness live provider proof and hardening
status: Approved
version: '0.3'
last_updated: '2026-06-01'
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
- Missing or unavailable provider routes fail, fall back, or skip with clear
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
  tests/test_live_secondary_harnesses.py \
  tests/test_harnesses.py \
  tests/test_harness_adapters.py \
  tests/test_routing_artifacts.py \
  tests/test_cli_v2.py \
  tests/test_tui_state.py
```

Default local live-test skip check:

```bash
./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
```

Provider-gated live commands are off by default and documented in
`REVREM-DEVEX-001`:

```bash
REVREM_LIVE_GEMINI=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
REVREM_LIVE_CLAUDE=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
REVREM_LIVE_OPENCODE=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
REVREM_LIVE_KILO=1 ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py
```

### Implementation Progress

2026-05-31:

- Added `tests/test_live_secondary_harnesses.py` with provider-gated direct live
  smoke tests for Claude, Gemini, opencode, and KiloCode.
- Added a provider-gated routed live smoke that defaults to Gemini and can be
  redirected with `REVREM_LIVE_ROUTED_PROVIDER`.
- Added model and executable overrides through
  `REVREM_LIVE_<PROVIDER>_MODEL` and `REVREM_LIVE_<PROVIDER>_BIN`.
- Configured the Gemini live smoke to trust pytest temporary workspaces with
  `GEMINI_CLI_TRUST_WORKSPACE=true`.
- Classified interactive provider authentication setup as a skipped
  prerequisite when a CLI tries to open an auth flow in a non-interactive test.
- Updated `REVREM-DEVEX-001` with commands, skip behavior, and routed artifact
  expectations.
- Verified the default no-credential path skips cleanly:
  `./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py`
  reported `5 skipped`.

### Closeout Evidence

2026-06-01:

- Provider: Gemini CLI.
- Command:

  ```bash
  REVREM_LIVE_GEMINI=1 \
    REVREM_LIVE_ROUTED_PROVIDER=gemini \
    ./.venv/bin/pytest -q tests/test_live_secondary_harnesses.py::test_live_routed_secondary_provider_smoke -s
  ```

- Result: `1 passed in 25.84s` in the credentialed maintainer terminal.
- Run directory:
  `/tmp/pytest-of-cmf/pytest-462/test_live_routed_secondary_pro0/artifacts`.
- Evidence:
  - `summary.json` reports `final_status: "clear"` and
    `stopped_reason: "review_clear"`.
  - `routing-1.json.effective_route.harness` is `gemini`.
  - `routing-outcome-1.json` exists and is listed under
    `summary.json.artifact_paths.routing`.
  - `remediation-1-prompt.txt` exists and is listed under
    `summary.json.artifact_paths.prompts`.
  - `remediation-1.txt` contains `REVREM_LIVE_SECONDARY_SMOKE_OK`.

The task is complete: secondary harness live proof exists for one real
provider, the other provider tests remain opt-in and skip by default, and
provider setup/auth failures are classified distinctly from internal loop
failures.

## Version History

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.3 | 2026-06-01 | Codex | Recorded Gemini live routed smoke evidence and marked the task complete |
| 0.2 | 2026-05-31 | Codex | Added live secondary harness tests and evidence tracking |
| 0.1 | 2026-05-31 | Codex | Initial governed task for live secondary provider proof |
