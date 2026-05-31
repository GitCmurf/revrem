---
document_id: REVREM-TASK-004
type: TASK
title: Dogfood hardening and operator UX
status: In Review
version: '0.6'
last_updated: '2026-05-30'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Dogfood-derived hardening programme for RevRem operator UX, runtime configuration
  visibility, triage controls, commit-message quality, and multi-harness validation
  after REVREM-TASK-003.
keywords:
- revrem
- dogfood
- devex
- triage
- harness
- operator-ux
- hardening
related_ids:
- REVREM-TASK-003
- REVREM-DEVEX-001
- REVREM-TEST-001
---

# TASK: Dogfood hardening and operator UX

## Context

`REVREM-TASK-003` made the review loop architecturally dogfoodable: the CLI is
thin, the application boundary is typed, the engine and runner shell have
headless acceptance tests, and the import graph is guarded. The first real
dogfood runs after that work proved the core loop can remediate, verify, and
commit useful changes, but also exposed a different class of defects:
operator-facing control, visibility, and failure handling are not yet polished
enough for confident daily use.

The dogfood runs used the local repository, full verification, automatic
commits, `--timeout-seconds 0`, Rich progress, final reviews, and resumed
review artifacts. They produced valid commits and caught real regressions:

- golden-master drift in the run summary contract;
- read-only `.git/info/exclude` no-op handling for default artifacts;
- missing latest-review excerpts for unresolved final outcomes;
- route capability checks firing even when v2 routing is disabled;
- Codex commit-message drafting failing with `reasoning_effort=minimal` and
  falling back to an unprofessional generic subject;
- no CLI override for enabling triage despite profile/config booleans being
  expected to have one-off overrides;
- insufficient live feedback about the harness, model, reasoning effort,
  timeout, sandbox, and source of each phase configuration.

This task is the dogfood hardening programme that turns those findings into a
reviewable set of implementation slices. It is not a re-opening of
`REVREM-TASK-002` (closed) or `REVREM-TASK-003` (architecture refactor). It is
the next product-quality layer after the architecture became strong enough to
exercise.

## Goal

Make RevRem trustworthy and pleasant to dogfood from this repository by
delivering:

- a project-local `dogfood` profile that encodes the first-class dogfood run;
- visible, reproducible resolved phase configuration in progress output,
  summaries, resume payloads, and dry runs;
- CLI overrides for runtime profile booleans and key phase controls, especially
  triage;
- robust commit-message drafting and deterministic professional fallback;
- correct handling of disabled routing, read-only no-op artifact setup,
  unresolved final-review excerpts, and explicit unbounded timeouts;
- a documented multi-model and multi-harness validation matrix, including a
  first non-Codex remediation path through Gemini CLI when available.

## Non-Goals

- Do not redesign the Wave C/D engine or runner architecture.
- Do not add hosted service, telemetry, background daemon, or GitHub PR comment
  integration.
- Do not make non-Codex harness availability mandatory for local development or
  CI. Non-Codex dogfood runs are operator-gated and skipped cleanly when the
  executable or credentials are absent.
- Do not require dogfood profile settings to be sensible outside this
  repository. The `dogfood` profile is intentionally project-local.
- Do not preserve compatibility for weak placeholder commit subjects,
  ambiguous summaries, or missing CLI overrides.

## Dogfood Findings To Carry Forward

### DF-001 — Commit-message fallback quality

- **Observed:** `--commit-reasoning-effort minimal` caused Codex to reject the
  commit-message model call with HTTP 400:
  `The following tools cannot be used with reasoning.effort 'minimal': web_search`.
  RevRem then committed with `chore: remediate review iteration 2 (RevRem)`.
- **Root cause (verified from the evidence artifact):** RevRem's own
  commit-message command path (`build_commit_message_command()` ->
  `harnesses.build_phase_command()` -> `CodexHarnessAdapter.command()`) adds
  *no* tool/search flags — it is `codex exec -c
  model_reasoning_effort="minimal" --sandbox read-only --color ... --model ...
  -`. Yet the `web_search` tool was active for the call and
  `reasoning.effort=minimal` is incompatible with it (the tool is supplied by
  Codex defaults or operator Codex config, not by a RevRem phase flag). The key
  point is that **RevRem does not add the tool, so the fix is not "delete a flag
  we set"** — it is to **explicitly disable the tool for the commit-message exec
  call** using Codex's current config override (`-c web_search="disabled"`) so
  `minimal` is not rejected because of inherited search tooling. Model-specific
  effort support still applies.
- **Impact:** The commit is technically valid but professionally inadequate.
  It obscures the change and makes dogfood history look careless.
- **Required fix:**
  1. The commit-message exec invocation must explicitly disable server-side
     tools (`web_search` at minimum) so incompatible inherited tools do not
     cause a `minimal` request to fail before the model can run.
     For known Codex commit-message models that do not support
     `reasoning.effort=minimal`, RevRem promotes `minimal` to `low`; `low` is
     the lowest live-compatible effort for those models.
  2. Any model failure must still fall back to a deterministic local subject
     derived from staged files, changed domains, and review context. Note the
     current `deterministic_commit_message(iteration)` takes only the iteration
     number and emits the generic subject; this fix requires giving it the
     staged-file/context inputs it does not have today.
- **Evidence:** `.revrem/runs/20260528T233809Z-79cbe75060a3437086bcb3baba4addb7/commit-2-message-draft.txt`
  (contains the verbatim 400 error quoted above).

### DF-002 — Phase configuration visibility

- **Observed:** Progress output shows phase starts, but not the resolved
  harness/model/effort/timeout/sandbox for every phase. Operators must inspect
  raw artifacts or `summary.json` after the fact.
- **Impact:** It is hard to verify that `--review-model`,
  `--remediation-model`, `--commit-reasoning-effort`, profile defaults, or
  route overrides actually took effect.
- **Required fix:** Every model-backed phase start prints a compact resolved
  config line. `summary.json` and dry-run output expose the same normalized
  phase plan.

### DF-003 — Triage has no one-off enable flag

- **Observed:** `--triage-enabled true` fails as an unrecognized argument.
- **Impact:** Users cannot test triage from the CLI without editing or saving a
  profile, contradicting the profile override convention.
- **Required fix:** Add explicit boolean overrides for triage and routing, with
  clear names and tests for CLI-over-profile precedence.

### DF-004 — Route capability checks ignore routing disabled

- **Observed:** A review found that profiles with `triage.routes` can be
  rejected even when `triage.routing.enabled = false`.
- **Impact:** Draft route tables become runtime hazards for normal non-routing
  runs.
- **Required fix:** Always validate route syntax and internal references, but
  require implemented executable harness chains only when routing is enabled or
  a lint/doctor command explicitly asks for executable-route validation.

### DF-005 — Latest review excerpts for unresolved outcomes

- **Observed:** A review found that unresolved final outcomes could lose
  `latest_review_excerpt`.
- **Impact:** Terminal summaries and resume workflows lose the actionable
  review text in the most important failure mode.
- **Required fix:** Preserve latest review output for `OutcomeFindings` and
  `OutcomeUnknown`; lock it with summary and integration tests.

### DF-006 — Explicit unbounded timeout loses intent

- **Observed:** Runs invoked with `--timeout-seconds 0` record
  `resume_config.timeout_seconds = null`.
- **Impact:** Operators cannot distinguish "unset/inherited" from "explicitly
  unbounded" in summaries or resume payloads.
- **Required fix:** Preserve explicit `0` in the operator-facing resolved
  config and resume payload. Internal `None` may still mean unbounded for
  subprocess calls, but the source value must remain visible.

### DF-007 — Latest check output wording is imprecise

- **Observed:** The terminal summary prints only two latest check artifact paths
  under "Latest check outputs" even when five checks ran.
- **Impact:** The label suggests completeness but gives a subset.
- **Required fix:** Print a status table for the latest iteration's checks, or
  rename the line to accurately describe the selected subset.

### DF-008 — Resume guidance is a fragment, not a command

- **Observed:** Terminal output prints
  `Continue from latest review: --initial-review-file <path>`.
- **Impact:** Operators must reconstruct the full safe command from memory.
- **Required fix:** Print a complete suggested command, including base, profile
  or checks, commit mode, timeout intent, and the initial review file.

### DF-009 — `command_line` is null

- **Observed:** `summary.json` records `"command_line": null`.
- **Impact:** Run summaries are less reproducible than shell history and
  terminal scrollback.
- **Required fix:** Record a redacted argv or a structured command object.
  Redact secrets, environment-provided paths if needed, and prompt text when it
  may contain sensitive review content.

### DF-010 — Read-only artifact ignore no-op

- **Observed:** A review found that default artifact setup locked
  `.git/info/exclude` before checking whether the ignore entry already existed.
- **Impact:** Dry runs or no-op setup can fail in read-only Git metadata
  environments.
- **Required fix:** This appears remediated by the dogfood run; retain it in
  this task as a closed dogfood finding with regression proof.

## Target Dogfood Profile

Add a project-local `[profiles.dogfood]` to `.revrem.toml`. This profile is
allowed to be opinionated for this repository. It should make the normal
dogfood command short, inspectable, and hard to misconfigure.

Recommended shape:

```toml
[profiles.dogfood]
description = "Project-local RevRem dogfood run with full verification, commits, diagnostics, and explicit phase models."

[profiles.dogfood.pipeline]
max_iterations = 3
checks = [
  "./.venv/bin/ruff check .",
  "./.venv/bin/mypy src",
  "lint-imports",
  "uv run --locked meminit check --format json",
  "./.venv/bin/pytest -q",
]

[profiles.dogfood.review]
harness = "codex"
model = "gpt-5.5"
reasoning_effort = "low"
timeout_seconds = 0

[profiles.dogfood.triage]
enabled = true
contract = "v2"
harness = "codex"
model = "gpt-5.5"
reasoning_effort = "low"
timeout_seconds = 0
on_invalid = "continue"

[profiles.dogfood.triage.routing]
enabled = true
mode = "first-match"
default_route = "codex-midi"
allow_model_escalation = true
strict_on_unavailable_route = false

[[profiles.dogfood.triage.routing.rule]]
id = "high-risk-frontier"
when.risk_level_min = "high"
then.route = "codex-frontier"

[[profiles.dogfood.triage.routing.rule]]
id = "multi-file-gemini"
when.module_count_gte = 4
then.route = "gemini-pro"

[profiles.dogfood.triage.routes.codex-frontier]
harness = "codex"
model = "gpt-5.5"
reasoning_effort = "medium"
timeout_seconds = 0

[profiles.dogfood.triage.routes.codex-midi]
harness = "codex"
model = "gpt-5.4-mini"
reasoning_effort = "medium"
timeout_seconds = 0

[profiles.dogfood.triage.routes.gemini-pro]
harness = "gemini"
model = "gemini-3.1-pro-preview"
reasoning_effort = "medium"
timeout_seconds = 0
fallback = "codex-midi"

[profiles.dogfood.remediation]
harness = "codex"
model = "gpt-5.4-mini"
reasoning_effort = "medium"
timeout_seconds = 0

[profiles.dogfood.commit]
enabled = true
harness = "codex"
message_model = "gpt-5.3-codex-spark"
reasoning_effort = "low"
timeout_seconds = 0

[profiles.dogfood.output]
debug_status_detection = true
progress_style = "rich"
terminal_title = true
summary_format = "both"
```

Notes:

- A multi-model profile is mandatory for dogfood because it exercises the
  phase-specific config surfaces users actually care about.
- A multi-harness route is desirable but must be optional at runtime. The
  profile should support Gemini CLI through a route with fallback, not make
  Gemini a hard dependency for every local dogfood run.
- `strict_on_unavailable_route = false` is appropriate for the project-local
  profile if the fallback route is implemented and visible in routing
  artifacts.

> **Schema validation reality (verified against `profiles.py`, 2026-05-29).**
> The profile parser uses strict `_reject_unknown_keys` validation, so an
> unknown key raises `ValueError` and the whole profile fails to load — it does
> not warn-and-continue. The shape above was corrected after parsing the
> original draft with `profiles.parse_profile`, which rejected it. Watch these
> key names specifically; they are the ones the draft got wrong:
>
> - routing rules use `id`, not `name` (`ROUTING_RULE_KEYS = ("id", "when", "then")`);
> - `when` predicates use `risk_level_min`/`risk_level_max` and
>   `module_count_gte`/`module_count_lt`, not `risk` or `min_modules`
>   (see `ROUTING_WHEN_KEYS`);
> - `[profiles.*.commit]` uses `message_model`, not `model`;
> - `[profiles.*.commit]` does **not** currently accept `reasoning_effort` or
>   `timeout_seconds` (`COMMIT_KEYS`). This task deliberately changes that
>   schema so the project-local dogfood profile is self-contained.
>
> Acceptance for T4a must include parsing this exact profile in a test so the
> dogfood command cannot regress into an unparseable profile.

- **Commit reasoning effort is a real schema gap and this task closes it.**
  There is no `commit.reasoning_effort` profile key today. In
  `config_builder.py` commit effort resolves as
  `args.commit_reasoning_effort or remediation_reasoning_effort`, so absent a
  CLI flag the dogfood profile would commit at the *remediation* effort
  (`medium`), not `low`. T4a must extend `COMMIT_KEYS`, `CommitConfig`, and the
  profile→`LoopConfig` mapping to accept `reasoning_effort` and
  `timeout_seconds`, with CLI overrides taking precedence. Commit-message
  timeout should use the commit profile timeout when set, then the global
  timeout; it must preserve explicit `0` in user-visible projections.

## CLI Control Surface

Flags split into two groups (verified against `cli/args.py`, 2026-05-29).

**Already present — reuse, do not re-add:** `--review-model`,
`--review-reasoning-effort`, `--remediation-model`,
`--remediation-reasoning-effort` (alias `--remediate-reasoning-effort`),
`--commit-message-model`, `--commit-message-prompt`, `--commit-reasoning-effort`,
`--triage-reasoning-effort`, `--timeout-seconds`. The triage *effort* flag
exists but the triage *enable* flag does not — that asymmetry is DF-003.

**New — add in this task:**

- `--triage` / `--no-triage` for `triage.enabled`;
- `--triage-contract {v1,v2}`;
- `--triage-model MODEL`;
- `--triage-harness HARNESS`;
- `--triage-timeout-seconds SECONDS`;
- `--routing` / `--no-routing` for `triage.routing.enabled`;
- `--routing-strict` / `--no-routing-strict` for
  `triage.routing.strict_on_unavailable_route`;
- `--commit-message-harness HARNESS` if commit-message drafting can use
  non-Codex harnesses; otherwise document that only the model/prompt/effort are
  currently exposed.

> **Internal plumbing already exists for most triage controls.** `resume_config`
> already records `triage_model`, `triage_harness`, `triage_enabled`, and
> `triage_reasoning_effort` (see `resume.py`), and `config_builder` already maps
> profile triage values into `LoopConfig`. So T4b is predominantly
> argument-parsing plus CLI-over-profile wiring in `config_builder` — not new
> config plumbing. The new work is the flags, their precedence, and tests.

Boolean flags should follow existing negative override style. Avoid flags that
require string booleans such as `--triage-enabled true`.

## Runtime UX Requirements

### Phase start lines

Each model-backed phase start must include a compact resolved config:

```text
review 1 start: codex review --base main [model=gpt-5.5 effort=low timeout=0 sandbox=read-only source=cli]
triage 1 start: codex exec [model=gpt-5.5 effort=low timeout=0 contract=v2 source=profile:dogfood]
remediate 1 start: codex exec [model=gpt-5.4-mini effort=medium timeout=0 sandbox=workspace-write source=route:codex-midi]
commit 1 start: draft commit subject [harness=codex model=gpt-5.3-codex-spark effort=low timeout=0]
```

### Summary and resume payload

`summary.json` must include:

- `phase_config.review`;
- `phase_config.triage`;
- `phase_config.remediation`;
- `phase_config.commit_message`;
- `phase_config.checks`;
- source markers for profile/default/CLI/route-derived values;
- explicit `0` for user-visible unbounded timeouts;
- redacted command invocation or structured argv.

### Terminal closeout

Closeout output must include:

- full resume command;
- check status table for the latest iteration;
- model/effort summary for the run;
- clear reason when a model-backed helper failed and fallback was used;
- paths to routing decision and outcome artifacts when routing ran.

## Implementation Slices

### T4a — Dogfood profile and resolved-config model

- Add `[profiles.dogfood]` to `.revrem.toml` using the **corrected** key names
  (`id`, `risk_level_min`, `module_count_gte`, `message_model`). The draft shape
  in this doc was confirmed unparseable by `profiles.parse_profile`; do not copy
  the original draft verbatim.
- Extend `COMMIT_KEYS`, `CommitConfig`, profile rendering, config builder, and
  resume/phase-plan projections so `[profiles.*.commit]` accepts
  `reasoning_effort` and `timeout_seconds`. Precedence is:
  CLI commit override, profile commit setting, remediation/global fallback.
- Introduce a typed resolved phase-plan projection used by dry run, progress,
  summary, and resume.
- Preserve explicit `timeout_seconds = 0` in user-visible projections.
- Add docs in `REVREM-DEVEX-001` for the dogfood command and profile.
- Tests:
  - **`profiles.parse_profile` accepts the exact committed `[profiles.dogfood]`
    block** (regression guard so the dogfood command can never ship an
    unparseable profile);
  - commit reasoning effort and timeout parse from `[profiles.dogfood.commit]`
    and flow into `LoopConfig`;
  - explicit zero timeout survives profile, CLI, summary, and resume payload;
  - dry-run JSON includes phase plan.

### T4b — CLI triage and routing overrides

- Add CLI flags for triage and routing controls.
- Apply CLI-over-profile precedence consistently in `config_builder`.
- Ensure help text includes examples and avoids string-boolean patterns.
- Tests:
  - `--triage` enables triage over profile false;
  - `--no-triage` disables triage over profile true;
  - `--routing` requires or implies compatible `triage.contract = "v2"` with a
    clear error if impossible;
  - `--no-routing` preserves route definitions but disables route execution.

### T4c — Commit-message robustness

- Explicitly disable Codex's default server-side `web_search`/tools for the
  commit-message exec role (the failure is the default tool being incompatible
  with `reasoning.effort=minimal`, not a flag RevRem adds — see DF-001). The
  fix belongs in the `PhaseCommandRequest` -> `CodexHarnessAdapter.command()`
  path, scoped to the `commit-message` role so other roles are unaffected. Use
  Codex's current `-c web_search="disabled"` override, and assert the generated
  command shape.
- Treat model-drafting failure as a first-class event and summary field.
- Replace generic fallback with deterministic subject synthesis. This requires
  changing `deterministic_commit_message`, which today takes only `iteration`
  and therefore *cannot* be specific — give it staged-file and review context:
  - infer scope from dominant changed path;
  - infer type from review/remediation context and file classes;
  - include `(RevRem)`;
  - never emit `chore: remediate review iteration N` except in a test fixture
    proving it is forbidden.
- Tests:
  - `--commit-reasoning-effort minimal` succeeds (asserts no `web_search` 400);
  - generated Codex command for the `commit-message` role disables
    `web_search`, while review/remediation command shapes are unchanged;
  - model failure yields deterministic non-generic subject;
  - fallback event appears in `events.jsonl` and `summary.json`.

### T4d — Routing validation and disabled-route semantics

- Gate executable route fallback-chain checks on routing enabled, policy lint,
  or doctor executable validation mode.
- Keep syntax and internal-reference validation for draft routes regardless of
  routing enabled.
- Tests:
  - profile with disabled routing and unavailable draft route passes normal
    resolution;
  - the same profile fails `policy lint` or doctor executable validation when
    requested;
  - enabled routing still rejects unavailable chains without valid fallback.

### T4e — Terminal and summary closeout UX

- Print full resume command.
- Replace ambiguous latest-check wording with a per-check table.
- Preserve latest review excerpts for unresolved outcomes and assert them in
  golden masters.
- Record redacted command invocation.
- Tests:
  - terminal summary snapshot for findings includes latest review excerpt;
  - JSON summary includes redacted argv and phase config;
  - latest check table marks each check passed/failed/skipped.

### T4f — Multi-harness dogfood validation

- Add a dogfood runbook section with a Codex-only baseline and an optional
  Gemini route exercise.
- Ensure missing Gemini CLI produces a clear preflight or route fallback, not a
  mid-loop surprise.
- Tests:
  - fake harness route emulates non-Codex fallback in CI;
  - `--harness-bin gemini=<path>` precedence is represented in phase plan;
  - routing artifacts record fallback from unavailable Gemini route to Codex.

## Dogfood Test Matrix

Run these in order before declaring this task done.

### Matrix A — Baseline dogfood

```bash
./.venv/bin/revrem --profile dogfood --base main --max-iterations 3
```

Expected:

- full phase-plan line appears before first model call;
- triage v2 runs;
- checks run after each remediation;
- commits are specific and professional;
- summary has `phase_config` and explicit timeout `0`;
- final output includes a full resume command.

### Matrix B — Resume from final review

```bash
./.venv/bin/revrem \
  --profile dogfood \
  --base main \
  --max-iterations 2 \
  --initial-review-file latest
```

Expected:

- initial review source is preserved;
- unresolved findings retain latest review excerpt;
- resume payload preserves the profile and CLI overrides.

### Matrix C — Codex model and effort overrides

```bash
./.venv/bin/revrem \
  --profile dogfood \
  --base main \
  --max-iterations 2 \
  --review-model gpt-5.5 \
  --review-reasoning-effort low \
  --remediation-model gpt-5.4-mini \
  --remediation-reasoning-effort medium \
  --commit-message-model gpt-5.3-codex-spark \
  --commit-reasoning-effort minimal
```

Expected:

- progress shows each override;
- commit-message drafting does not fail due to incompatible tool config;
- if it fails for any other reason, fallback subject is specific.

### Matrix D — Triage one-off controls

```bash
./.venv/bin/revrem \
  --base main \
  --max-iterations 1 \
  --triage \
  --triage-contract v2 \
  --routing \
  --skip-final-review \
  --dry-run \
  --summary-format json
```

Expected:

- dry run shows triage and routing enabled without editing profiles;
- the same command with `--no-triage` shows triage disabled.

### Matrix E — Gemini remediation route

Only run when Gemini CLI and credentials are available.

```bash
./.venv/bin/revrem \
  --profile dogfood \
  --base main \
  --max-iterations 2 \
  --harness-bin gemini=gemini \
  --triage \
  --routing
```

Expected:

- a routed remediation can select `gemini-3.1-pro-preview`;
- progress shows `harness=gemini model=gemini-3.1-pro-preview`;
- routing decision and outcome artifacts record the route;
- if Gemini is unavailable, configured fallback is visible and the run remains
  bounded.

### Matrix F — Disabled routing with draft routes

```bash
./.venv/bin/revrem \
  --profile dogfood \
  --base main \
  --max-iterations 1 \
  --no-routing \
  --dry-run \
  --summary-format json
```

Expected:

- profile resolves even with route definitions present;
- dry run shows routing disabled;
- no route executable-chain check runs unless policy lint or doctor asks for it.

## Additional Tests To Inform This Task

Run these before implementation if time permits; they provide useful baselines
but are not prerequisites for writing code:

1. `gpt-5.3-codex-spark` as commit-message model with `low` effort.
2. `gpt-5.3-codex-spark` as commit-message model with `minimal` effort after
   disabling Codex-supplied `web_search` for commit drafting.
3. `gpt-5.4-mini` with `medium` effort for remediation through a resumed
   finding.
4. Gemini CLI remediation with `gemini-3.1-pro-preview`, first as a direct
   remediation harness, then through a v2 routing route.
5. Codex review on `gpt-5.5` with `low` effort versus `medium` effort on the
   same diff, comparing actionable finding quality and runtime.
6. Dry-run profile inspection for `dogfood`, `dogfood --no-triage`, and
   `dogfood --no-routing`.
7. A deliberately unavailable Gemini executable with a valid fallback route to
   verify preflight/fallback messaging.

## Acceptance Criteria

- `REVREM-TASK-004` dogfood profile exists in `.revrem.toml`, is documented, and
  parses cleanly under strict `_reject_unknown_keys` validation (guarded by a
  test that loads the exact committed block).
- `[profiles.*.commit]` accepts `reasoning_effort` and `timeout_seconds`, and
  the committed dogfood profile uses those keys.
- Every profile/config boolean that affects the runtime loop and is relevant to
  dogfood has a CLI override or a documented reason it does not.
- Model-backed phases display resolved harness/model/effort/timeout/sandbox
  before execution.
- `summary.json`, dry-run JSON, and resume payloads expose the same resolved
  phase plan.
- Explicit unbounded timeouts are represented as `0` in operator-facing
  projections.
- Commit-message fallback never emits generic iteration-only subjects.
- Disabled routing does not reject draft route tables during normal runs.
- Unresolved final outcomes preserve latest review excerpts.
- Closeout output includes a full resume command and an accurate check table.
- Codex-only dogfood matrix passes.
- Non-Codex route/fallback behavior is covered by deterministic tests and, when
  local Gemini credentials are available, a real Gemini dogfood run.
- `ruff`, `mypy`, `lint-imports`, `meminit check`, and `pytest -q` pass.

## Adversarial Remediation Addendum

An adversarial review after the first implementation pass found that the
feature work was mostly in place, but the task could not be called complete
because `pytest -q` was not hermetic across clean and polluted `/tmp` states.
The accepted remediation scope is:

- centralize lexical repository-root discovery behind a temp-root guard so a
  stray `/tmp/.git` or `/tmp/.revrem.toml` cannot influence project profile,
  suppression, or artifact-ignore discovery;
- make commit artifact exclusion use the injected process runner for
  `git rev-parse --show-toplevel`, and treat missing repo-root information as
  "skip artifact reset" rather than a hard pre-staging failure;
- keep the repo-root artifact-dir refusal for known repository roots;
- make commit adapter tests create their own `.git` when they depend on one,
  and add a no-repository regression for `skipped_no_changes`;
- replace the fragmentary continue hint with a shell-quoted command carrying
  base, max-iterations, profile or checks, timeout intent, commit mode, initial
  review file, and hook policy;
- make deterministic commit-message fallback use staged files plus
  review/remediation context, so local fallback subjects remain professional
  when model drafting fails;
- add field-level `phase_config.*.sources` provenance alongside the existing
  phase-level `source` summary, with mixed phase sources marked explicitly as
  `mixed`;
- remove the invalid stray `docs/tasks/TASK-004-adversarial-review.md` and
  track the valid governed review report at
  `docs/05-planning/tasks/task-004-adversarial-review-findings.md`.

Closeout must verify both temp states:

```bash
rm -rf /tmp/.git /tmp/.revrem.toml
./.venv/bin/pytest -q
mkdir -p /tmp/.git
./.venv/bin/pytest -q
rm -rf /tmp/.git /tmp/.revrem.toml
```

### Round 2 closeout scope

The second adversarial review found the hermeticity fix complete and all gates
green, with one remaining blocker and a small polish set. The accepted Round 2
remediation is:

- add explicit executable-route validation modes:
  `revrem policy lint --executable-routes` and
  `revrem doctor --validate-routes`;
- keep normal disabled-routing behavior unchanged while making requested
  validation fail on unavailable draft route chains;
- expose `--commit-message-harness` for one-off commit-subject drafting
  harness overrides;
- expose `--allow-model-escalation` / `--no-allow-model-escalation` for the
  routing policy boolean used by the dogfood profile;
- document the new triage/routing control surface in `REVREM-DEVEX-001`;
- remove the dead timeout-display parameter, replace the commit artifact-root
  call-for-side-effect with a named guard, and restore always-on
  `default_route` internal-reference validation when a route table exists or
  routing is enabled.

Round 2 implementation evidence:

- added `policy lint --executable-routes` and `doctor --validate-routes`;
- added `--commit-message-harness` and
  `--allow-model-escalation` / `--no-allow-model-escalation`;
- added regression tests for disabled-route default behavior, requested
  executable-route validation, commit-message harness precedence, and routing
  model-escalation precedence;
- verified `ruff`, `mypy`, `lint-imports`, `meminit check`, and `pytest -q`;
- verified `pytest -q` in both required temp states:
  clean `/tmp` -> `838 passed`; polluted `/tmp/.git` -> `838 passed`.

### Round 3 closeout scope

The third adversarial review found TASK-004 complete and the architecture
strong, with a final quality gap in operator-facing polish. The accepted Round
3 remediation is:

- replace the deterministic fallback subject
  `apply verified remediation N` with path/context-derived Conventional Commit
  subjects;
- rank explicit bugfix/regression signals ahead of loose feature words during
  fallback type inference;
- preserve triage, routing, model, harness, effort, commit-message, and
  timeout overrides in suggested resume commands;
- repeat compact progress prefixes on wrapped physical lines so phase logs stay
  grep-friendly;
- show `source=` in closeout phase-configuration summaries;
- avoid subset-like check artifact fallbacks when check artifact names are not
  parseable;
- document intentional temp-root ancestor exclusion in root discovery.

Round 3 implementation evidence:

- added regression coverage for descriptive fallback subjects, bugfix-vs-feat
  inference, complete resume override projection, wrapped progress prefixes,
  closeout phase provenance, and check-artifact parse misses;
- verified the focused TASK-004 regression tests before full gate execution;
- live dogfood Matrix A/C/E remains the final operator exercise after the code
  gate is green because it depends on local Codex/Gemini credentials.

### Round 4 closeout scope

The fourth adversarial review found the remaining TASK-004 issues concentrated
in fallback subject taste and operator truthfulness. The accepted Round 4
remediation is:

- make deterministic commit-message fallback repository-generic, with no
  RevRem-specific canned phrases or project noun lexicon;
- default neutral fallback subjects to `chore`, not `fix`;
- surface Codex commit-message `minimal -> low` promotion as operator-visible
  configuration, including requested/effective effort in `phase_config` and a
  `config-adjusted` progress/event entry;
- apply secret redaction to every recorded command-line token, not only prompt
  flags;
- carry `routing_strict` provenance through the real config builder and verify
  resume output against built `LoopConfig` state rather than hand-authored
  summary fixtures.

Round 4 implementation evidence:

- replaced exact-string fallback tests with property assertions covering
  Conventional Commit shape, path-derived scope, absence of generic/canned
  phrases, and context-derived terms;
- added regression coverage for neutral `chore` fallback, effort-promotion
  events, broad argv redaction, and real `routing_strict` phase-source
  projection;
- retained the live Matrix A/C/E requirement as operator sign-off because those
  runs depend on local Codex/Gemini credentials.

### Round 5 closeout scope

The fifth adversarial review live-tested DF-001 through Codex 0.135.0 and found
the remaining gaps were accuracy and taste, not architecture. The accepted
Round 5 remediation is:

- rename the Codex `minimal -> low` adjustment to
  `codex_minimal_unsupported_by_model` and apply it only to known incompatible
  commit-message models;
- strip redundant trigger verbs from deterministic fallback subjects and
  suppress low-value scopes such as `docs(docs)` and one-character path scopes;
- add a credential-gated live Codex smoke so the DF-001 path can be verified
  continuously when local credentials are available.

Round 5 implementation evidence:

- added property-style fallback tests forbidding verb-doubling and scope/type
  collisions;
- added regression coverage for model-specific effort promotion and future
  Codex models that may support `minimal`;
- added `REVREM_LIVE_CODEX=1` live smoke coverage for real commit-message
  drafting through Codex.

## Verification Commands

```bash
./.venv/bin/ruff check .
./.venv/bin/mypy src
lint-imports
uv run --locked meminit check --format json
./.venv/bin/pytest -q
```

Optional live Codex smoke:

```bash
REVREM_LIVE_CODEX=1 ./.venv/bin/pytest -q tests/test_live_codex_commit_message.py
```

Dogfood verification:

```bash
./.venv/bin/revrem --profile dogfood --base main --max-iterations 3
./.venv/bin/revrem --profile dogfood --base main --max-iterations 2 --initial-review-file latest
```

Optional Gemini verification:

```bash
./.venv/bin/revrem \
  --profile dogfood \
  --base main \
  --max-iterations 2 \
  --harness-bin gemini=gemini \
  --triage \
  --routing
```

## Done Means

Done means a reviewer can run one project-local command, see exactly which
models and harnesses are active, trust commits produced by the loop, resume
from an unresolved finding without reconstructing flags, and inspect a summary
that faithfully records the effective dogfood configuration. The first
non-Codex route does not have to be mandatory, but its availability, fallback,
and artifacts must be clear enough that enabling it is an operator choice, not
a debugging session.
