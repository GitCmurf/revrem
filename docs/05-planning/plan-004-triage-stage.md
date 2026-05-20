---
document_id: REVREM-PLAN-004
type: PLAN
title: Triage Stage as a Routing and Prompt-Construction Layer
status: Approved
version: '1.0'
last_updated: '2026-05-20'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Defines the next-generation optional triage stage for RevRem as a policy-governed routing, classification, and prompt-construction layer that can select remediation models and harnesses across Codex, Claude, Gemini, OpenCode, and KiloCode while preserving bounded execution, auditability, and local-first operator control.
keywords:
  - triage
  - routing
  - remediation
  - harnesses
  - policy
  - audit
  - prompt-construction
  - model-selection
related_ids:
  - REVREM-PRD-001
  - REVREM-PLAN-003
  - REVREM-ADR-003
  - REVREM-ADR-004
  - REVREM-ADR-006
  - REVREM-ADR-008
  - REVREM-ADR-009
  - REVREM-ADR-010
  - REVREM-DEVEX-001
  - REVREM-TEST-001
---

# PLAN: Triage Stage as a Routing and Prompt-Construction Layer

## Context

RevRem already has an optional triage phase. The original implementation was
deliberately narrow:

- `src/code_review_loop/triage.py` loads `triage_v1.txt`, validates structured
  JSON against `triage-v1.schema.json`, stamps envelope fields, writes
  `triage-<iteration>.json`, and formats a structured handoff for remediation.
- `src/code_review_loop/cli.py` ran triage with a read-only Codex `exec`
  command before remediation when `profile.triage.enabled` was true.
- The v1 artifact can confirm, reject, or defer review findings, order the
  implementation, and suggest verification commands.
- Invalid structured triage fails safe: `triage.on_invalid = "continue"`
  ignores invalid structured guidance and falls back to the original
  review/check context; `triage.on_invalid = "stop"` fails the run.
- The harness registry reserved Codex, Claude, Gemini, OpenCode (`opencode`),
  and KiloCode (`kilo`) names. On the maintainer workstation all five CLIs are
  installed and usable, so this plan closes the product gap between local CLI
  availability and first-class RevRem adapter execution.

That v1 contract is useful as a finding filter, but it does not yet answer the
more important operator question:

> Given this review, any failed checks, the repo profile, the configured
> budgets, and the available harness capabilities, who should fix this, with
> what prompt, and why?

This plan upgrades triage into a routing and prompt-construction stage without
turning it into an uncontrolled autonomous agent. The implemented v2 contract
lets the triage model propose classification, route, and prompt content. A
deterministic policy resolver validates the proposal, applies user-configured
if-then routing rules, composes the effective prompt, and hands the loop an
executable remediation request.

## Corrections To The Initial Draft

The first draft captured the right product direction but made several contract
errors that must not be carried into implementation:

- **v1 is not additive.** `triage-v1.schema.json` has
  `additionalProperties: false`. A payload containing `classification` or
  `routing` cannot "continue to validate against v1". Routing requires a real
  `triage-v2` schema, prompt, parser path, and compatibility branch for v1.
- **Config paths must match the implementation.** The current user config path
  is `~/.config/revrem/profiles.toml`; the current project config path is
  `.revrem.toml`. A future policy file may be introduced, but this plan should
  not name `.revrem/policy.toml` as if it already exists.
- **`triage.on_invalid = "warn"` is not a valid value.** Current values are
  `"continue"` and `"stop"`. Routing can add separate strictness knobs, but it
  must not reuse an invalid existing setting.
- **The canonical event stream already exists.** ADR-008 defines
  `events.jsonl`. Routing should extend that event contract or write bounded
  JSON artifacts referenced from it, not create a competing per-iteration event
  stream unless a later ADR explicitly justifies the split.
- **Model-generated prompts are untrusted input.** Passing a triage model's
  arbitrary prompt string directly to a write-capable remediator is a prompt
  injection and policy-bypass risk. The final prompt must be deterministic,
  policy-bounded, recorded exactly, and may include the triage model's draft
  only inside a clearly marked untrusted guidance section.
- **Installed CLI is not the same as implemented RevRem adapter.** Claude,
  Gemini, OpenCode, and KiloCode are installed locally, but the routing layer
  still needed implemented adapters, capability metadata, and executable
  resolution before it could call them safely. Routing must distinguish
  "known", "installed", "capable", and "selected for this run".
- **The original executable model was Codex-specific.** `PhaseCommandRequest`
  originally took a single `executable` value from `runtime.codex_bin`. Real
  multi-harness routing requires per-harness executable resolution instead of
  passing `codex_bin` into every adapter.

## North Star

Triage becomes RevRem's dispatcher:

> It reads review findings and failed checks, classifies the work, applies
> operator policy, selects the remediation route, composes the exact prompt,
> records why the route was chosen, and lets the existing loop execute one
> bounded remediation phase.

The design must preserve RevRem's core product properties:

- **Local-first.** No hosted control plane, no telemetry, and no hidden policy
  service. Profiles, policies, prompts, and artifacts live on disk.
- **Bounded by default.** Routing may choose a different harness/model, but it
  must not bypass iteration, timeout, sandbox, or budget ceilings.
- **Auditable.** Each routing decision records the model proposal, policy rule,
  effective route, effective prompt path/hash, fallback behavior, and outcome.
- **Harness-agnostic.** Triage routes to harness capabilities, not
  vendor-specific command-line syntax.
- **Policy-governed.** The model can recommend, but deterministic policy makes
  the executable decision.

## Goals

- Let a triage model consume the review output, previous failed checks, and
  bounded repo facts, then produce a structured routing proposal.
- Let user/profile/project policy choose remediation route tiers such as
  `frontier-thinking`, `security-specialist`, `midtier-coder`, and
  `efficient-coder`.
- Support future remediation harnesses for Codex, Claude, Gemini, OpenCode,
  and KiloCode through the harness capability boundary.
- Compose the final remediation prompt from structured findings, policy
  fragments, repo engineering principles, failed checks, and triage guidance.
- Record non-committed artifacts that let the operator refine routing policy
  after observing model choice, rationale, prompt, and outcome.
- Make Codex, Claude, Gemini, OpenCode, and KiloCode eligible remediation
  harnesses once their thin non-interactive adapters pass the same contract
  tests; keep the fake harness as the deterministic test double.

## Non-Goals

- Building deep feature-complete adapters for every CLI. This plan does require
  thin non-interactive adapters sufficient for review, triage, and remediation
  routing where the installed CLI supports those roles; richer provider-specific
  features can follow later.
- Training or hosting a custom triage model.
- Allowing a triage model to execute commands, edit files, mutate profiles, or
  override cost/security policy.
- Auto-tuning policy rules. The first version may suggest changes from audit
  artifacts, but rule edits remain explicit operator changes.
- Splitting one iteration into multiple parallel remediation calls. That is a
  later fan-out feature. This plan keeps one effective route per iteration.

## Execution Model

### Inputs To Triage

The triage phase should receive a bounded, deterministic input bundle:

- the current review artifact path and review text;
- failed check outputs carried from the previous loop pass;
- current iteration number and previous iteration outcome;
- configured checks and budget ceilings;
- effective profile values for review, triage, remediation, runtime, and
  suppressions;
- harness capability payloads for known harnesses;
- deterministic repo facts computed by RevRem, for example changed-file count,
  affected top-level modules, generated diff stats, and whether sensitive file
  paths or security keywords appear in findings;
- relevant governance pointers such as `AGENTS.md`, project engineering
  principles, and configured prompt fragment names, not unbounded repository
  dumps.

The triage process remains read-only. It should not receive write sandbox
permissions just because remediation may later need them.

### Phase Responsibilities

The upgraded stage has five boundaries:

1. **Triage model proposal.** A configured triage harness/model reads the input
   bundle and emits `triage-v2` JSON containing finding decisions,
   classification, proposed route, rationale, and prompt requirements.
2. **Deterministic classification merge.** RevRem merges model classification
   with deterministic observations. Deterministic safety signals can escalate
   risk; the model cannot de-escalate them.
3. **Policy resolution.** A pure policy engine evaluates ordered if-then rules
   and produces an effective `ResolvedRoute`.
4. **Prompt composition.** A deterministic composer builds the exact prompt
   sent to the remediation harness. It may include the triage model's prompt
   draft as quoted, untrusted guidance, but the structural instructions,
   definition of done, verification expectations, and safety constraints come
   from RevRem and policy fragments.
5. **Orchestrator execution.** The existing loop executes one remediation
   phase using the effective route, records outcome, runs configured checks,
   and continues the bounded loop.

This keeps triage powerful without making it authoritative over execution.

## Triage v2 Contract

`triage-v2` is a new schema and prompt, not an in-place v1 extension.

Runtime behavior:

- v1 plain text and v1 JSON remain accepted for existing profiles.
- `triage.contract = "v1"` preserves current behavior.
- `triage.contract = "v2"` enables routing fields and policy resolution.
- During migration, `triage.routing.enabled = true` should require v2
  structured output unless an explicit compatibility mode says otherwise.

Sketch:

```json
{
  "schema_version": "2.0",
  "run_id": "stamped-by-revrem",
  "source_review_artifact": "review-1.txt",
  "prompt_version": "triage-v2",
  "confirmed_findings": [],
  "rejected_findings": [],
  "needs_more_info": [],
  "implementation_order": [],
  "verification_commands": [],
  "parsing_warnings": [],
  "classification": {
    "domain_tags": ["security", "auth"],
    "risk_level": "high",
    "refactor_depth": "localised",
    "affected_modules": ["src/auth.py", "tests/test_auth.py"],
    "estimated_blast_radius": {
      "module_count": 2,
      "finding_count": 1
    },
    "safety_signals": ["sensitive-domain:auth"],
    "failed_check_signals": ["pytest:tests/test_auth.py"]
  },
  "route_proposal": {
    "route_tier": "security-specialist",
    "harness": "codex",
    "model": "operator-configured-security-model",
    "reasoning_effort": "high",
    "sandbox": "workspace-write",
    "timeout_seconds": 1800,
    "rationale": "The confirmed finding affects authentication code and a failing auth test."
  },
  "prompt_requirements": {
    "required_fragments": ["engineering-principles", "security-checklist"],
    "definition_of_done": [
      "Fix the confirmed finding without weakening authentication checks.",
      "Add or update regression coverage.",
      "Run the configured checks."
    ],
    "triage_prompt_draft": "Untrusted triage guidance may appear here."
  }
}
```

The executable route is not taken directly from `route_proposal`. RevRem writes
separate routing artifacts after policy resolution.

## Effective Routing Artifact

For each routed iteration, RevRem should write bounded JSON metadata plus the
exact prompt as a text artifact:

- `triage-<iteration>.txt`: raw triage harness transcript, as today.
- `triage-<iteration>.json`: validated `triage-v2` payload.
- `routing-<iteration>.json`: effective routing decision metadata.
- `remediation-<iteration>-prompt.txt`: exact prompt passed to the remediation
  harness.
- `routing-<iteration>-outcome.json`: post-remediation outcome metadata.

`routing-<iteration>.json` should contain:

```json
{
  "schema_version": "1.0",
  "run_id": "same-run-id",
  "iteration": 1,
  "source_triage_artifact": "triage-1.json",
  "model_proposal": {
    "route_tier": "security-specialist",
    "harness": "codex",
    "model": "operator-configured-security-model",
    "reasoning_effort": "high",
    "sandbox": "workspace-write",
    "timeout_seconds": 1800,
    "rationale": "..."
  },
  "policy_decision": {
    "matched_rule_ids": ["sensitive-frontier"],
    "decision": "policy_override",
    "rationale": "Sensitive auth/security finding requires the security route."
  },
  "effective_route": {
    "route_tier": "security-specialist",
    "harness": "codex",
    "model": "operator-configured-security-model",
    "reasoning_effort": "high",
    "sandbox": "workspace-write",
    "timeout_seconds": 1800
  },
  "fallbacks_considered": [],
  "prompt": {
    "path": "remediation-1-prompt.txt",
    "sha256": "hex-digest",
    "bytes": 12345,
    "fragments": ["base-remediation", "engineering-principles", "security-checklist"]
  }
}
```

The exact prompt belongs in a text artifact, not inline in JSON. That keeps JSON
artifacts bounded and aligns with ADR-004's rule that public JSON artifacts
should not inline unbounded transcript-like content.

Routing events should be emitted through the canonical `events.jsonl` stream.
This will require extending `EVENT_KINDS` and the event schema with one or more
route-aware kinds such as `routing_decision` and `routing_outcome`, or a single
generic event with stable payload fields. The implementation should not add a
second event stream unless ADR-008 is revised.

## Policy System

### Location And Precedence

The current config system merges user and project profiles from:

- user: `~/.config/revrem/profiles.toml`
- project: `.revrem.toml`

The first implementation should extend that profile system rather than invent a
parallel policy store. If a dedicated `.revrem/policy.toml` is later justified,
it should be introduced as a separate migration with explicit precedence rules.

Recommended precedence for the first implementation:

1. built-in default route tiers and prompt fragments;
2. user profile defaults;
3. named user profile;
4. project defaults;
5. named project profile;
6. CLI one-shot overrides, where explicitly supported.

Project config should be able to tighten safety policy but should not silently
weaken user-level budget ceilings unless the operator opted into that profile.

### Rule Shape

Policy should be a small declarative grammar, not an embedded programming
language. Ordered first-match rules are sufficient for the first version.

Example profile sketch:

```toml
[profiles.pr-ready.triage]
enabled = true
harness = "codex"
model = "operator-configured-triage-model"
reasoning_effort = "medium"
timeout_seconds = 300
on_invalid = "continue"
contract = "v2"

[profiles.pr-ready.triage.routing]
enabled = true
mode = "first-match"
default_route = "midtier-coder"
strict_on_unavailable_route = true

[[profiles.pr-ready.triage.routing.rule]]
id = "sensitive-frontier"
when.domain_tags_any = ["security", "auth", "secrets", "pii"]
then.route = "frontier-thinking"
then.prompt_fragments = ["engineering-principles", "security-checklist"]
then.allow_model_deescalation = false

[[profiles.pr-ready.triage.routing.rule]]
id = "architectural-frontier"
when.refactor_depth_any = ["architectural"]
when.module_count_gte = 6
then.route = "frontier-thinking"
then.prompt_fragments = ["engineering-principles", "architecture-checklist"]

[[profiles.pr-ready.triage.routing.rule]]
id = "careful-refactor"
when.refactor_depth_any = ["localised", "cross-module"]
when.module_count_lt = 6
then.route = "midtier-coder"
then.prompt_fragments = ["definition-of-done", "regression-test-checklist"]

[[profiles.pr-ready.triage.routing.rule]]
id = "trivial-atomic"
when.refactor_depth_any = ["atomic"]
when.risk_level_max = "low"
then.route = "efficient-coder"
then.prompt_fragments = ["atomic-task-list"]

[profiles.pr-ready.triage.routes.frontier-thinking]
harness = "codex"
model = "operator-configured-frontier-model"
reasoning_effort = "high"
timeout_seconds = 1800
sandbox = "workspace-write"

[profiles.pr-ready.triage.routes.midtier-coder]
harness = "codex"
model = "operator-configured-midtier-model"
reasoning_effort = "medium"
timeout_seconds = 900
sandbox = "workspace-write"

[profiles.pr-ready.triage.routes.efficient-coder]
harness = "codex"
model = "operator-configured-efficient-model"
reasoning_effort = "low"
timeout_seconds = 300
sandbox = "workspace-write"
```

The examples intentionally use operator-configured model identifiers. Vendor
model names drift, and RevRem should not hard-code today's "best" model names
into governed planning docs. Bundled example profiles may use concrete model
IDs, but they need normal release maintenance.

### Policy Semantics

The policy resolver should obey these rules:

- Unknown rule keys fail `revrem policy lint`.
- Unknown routes fail profile validation.
- Unknown harness names fail profile validation.
- Known harnesses may remain valid in profile syntax, but a route cannot
  execute unless the selected harness has an implemented adapter, a resolvable
  executable, and the required capabilities for the selected role.
- A model proposal can escalate above the matched policy route only when the
  policy allows escalation.
- A model proposal cannot de-escalate sensitive or deterministic safety
  signals when `allow_model_deescalation = false`.
- Configured check commands remain authoritative. Triage-suggested
  `verification_commands` can appear in the remediation prompt, but RevRem
  should not execute newly suggested shell commands without an explicit
  operator-controlled feature.
- Budget ceilings are checked before triage and before remediation. A route
  that cannot satisfy remaining budget/time constraints should resolve to an
  allowed cheaper fallback or fail with a routing diagnostic before invoking
  the model.

## Classification Taxonomy

The v2 taxonomy should be closed enough for policy and extensible enough for
repo-specific needs.

Core fields:

- `domain_tags`: `security`, `auth`, `secrets`, `pii`, `public-api`,
  `data-loss`, `concurrency`, `performance`, `migration`, `build`, `tests`,
  `docs`, `release`, `dependency`, `style`.
- `risk_level`: `trivial`, `low`, `medium`, `high`, `critical`.
- `refactor_depth`: `atomic`, `localised`, `cross-module`, `architectural`.
- `affected_modules`: path-like module identifiers from findings and
  deterministic repo facts.
- `safety_signals`: deterministic or model-proposed signals that explain why a
  route should be escalated.
- `failed_check_signals`: structured references to failed check categories.

Extension fields should be namespaced, for example `x:team:billing` or
`x:repo:governed-docs`. Policy may match namespaced tags, but built-in rules
should depend only on the core vocabulary.

Deterministic observations must be distinguished from model observations. If
the model omits `security` but deterministic scanning sees auth/secrets/PII
signals, policy must still see the deterministic signal.

## Prompt Construction

The remediation prompt is a first-class artifact. It should be constructed by
RevRem, not improvised inside `run_remediation()`.

Prompt sections:

1. **Execution frame.** Bounded loop context, AGENTS.md summary, preserve user
   changes, do not revert unrelated work, obey code + docs + tests.
2. **Effective route.** Harness/model tier, policy rule, and why this route was
   chosen.
3. **Findings to fix.** Confirmed findings with fingerprints, severity,
   affected paths, rationale, and implementation order.
4. **Rejected or deferred findings.** Include enough detail to prevent the
   remediator from re-fixing false positives accidentally.
5. **Failed checks.** Prior check failures that must be addressed.
6. **Policy fragments.** Versioned fragments such as
   `engineering-principles`, `security-checklist`,
   `architecture-checklist`, `definition-of-done`,
   `regression-test-checklist`, and `atomic-task-list`.
7. **Triage guidance.** The triage model's prompt draft or advice, clearly
   marked as untrusted guidance that cannot override the execution frame or
   policy fragments.
8. **Verification expectations.** Configured checks that RevRem will run and
   any triage-suggested commands the remediator may run manually if relevant.

Prompt fragments should be versioned package resources. User-defined fragments
may be allowed, but they need path validation, deterministic ordering, and
prompt-hash recording.

The composer must enforce size ceilings. If the prompt exceeds a configured
limit, it should fail or ask for a narrower route; it must not silently
truncate the safety frame, policy fragment, or definition of done.

## Harness Integration

Routing requires a stronger adapter boundary than the current Codex-centric
command request.

Required changes:

- Add per-harness executable configuration instead of passing `runtime.codex_bin`
  to every harness.
- Extend `HarnessCapabilities` or add route validation helpers for
  role support, sandbox support, timeout support, cancellation support,
  structured output support, and cost reporting.
- Add a `ResolvedRoute` or equivalent value object that contains
  `harness`, `model`, `reasoning_effort`, `sandbox`, `timeout_seconds`,
  `full_auto`, and output-capture requirements.
- Ensure `build_phase_command()` validates that the selected harness supports
  the selected role before command construction.
- Implement the thin installed-CLI adapters for Claude, Gemini, OpenCode, and
  KiloCode behind the same adapter boundary as Codex. Each adapter should start
  with the smallest safe non-interactive command surface: prompt on stdin,
  bounded timeout/cancellation through RevRem, configured model where the CLI
  supports it, and transcript capture.
- Preserve the fake harness as the executable contract for routing tests so the
  adapter behavior remains testable without invoking live model CLIs.
- Make fallback behavior explicit. A fallback can only be used when policy
  names it; otherwise a route-unavailable diagnostic is safer than silent
  downgrading.

Example unavailable-route behavior:

- If policy routes to `claude` and the Claude CLI is not found, RevRem checks
  for a policy-approved fallback such as
  `frontier-thinking.fallback = "codex-frontier"`.
- If the CLI is found but the adapter cannot satisfy the requested role,
  sandbox, timeout, or output-capture capability, the same fallback path
  applies.
- If the fallback is implemented and satisfies capability/budget constraints,
  RevRem records `decision = "fallback_applied"` and proceeds.
- If no fallback is valid, RevRem writes
  `revrem.triage.route_unavailable`, records the failed route, and stops before
  remediation.

## Audit And Privacy

Routing artifacts are local run artifacts and must stay out of commits. The
default run directory already lives under `.revrem/runs`; commit mode already
resets artifact paths before committing. This plan should add tests covering
the new prompt and routing artifacts.

Audit artifacts must answer:

- What did the triage model propose?
- Which deterministic safety signals were present?
- Which policy rules matched?
- What route was selected?
- Was a fallback applied?
- What exact prompt was sent?
- Which harness/model ran remediation?
- What was the return code, wall time, and reported token/USD cost, if any?
- Did configured checks pass afterward?
- Did a later iteration still find related issues?

Privacy expectations:

- `remediation-<iteration>-prompt.txt` may contain source excerpts, review
  findings, failed check output, and policy guidance. Treat it as sensitive
  local artifact data.
- Bug bundles and future export/report commands must pass the prompt artifact
  through the same redaction boundary as transcripts.
- The policy review command should summarize corpus metadata and route
  effectiveness by default, not print full prompts unless explicitly asked.

## CLI, TUI, And Developer Experience

Initial CLI surface:

- `revrem policy lint --profile <name>` validates routing rules, routes,
  fragments, harness names, model strings, and fallbacks without running a
  model.
- `revrem triage explain <run-dir>` renders route proposal, policy decision,
  effective route, prompt hash/path, and outcome.
- `revrem policy review --artifact-dir <dir>` summarizes historical routing
  outcomes and suggests policy refinements without editing config.

Loop output:

- Compact progress should show the selected route tier and harness/model after
  triage, but not print the full prompt.
- Rich/TUI surfaces should add a Routing panel fed from `events.jsonl` and
  routing artifacts.
- Replay should render routing decisions from events without invoking a model.

Documentation:

- `docs/70-devex` needs a worked profile showing a security escalation route,
  a mid-tier refactor route, and an efficient trivial-fix route.
- API docs need schemas for `triage-v2`, `routing-v1`, and
  `routing-outcome-v1`.
- Harness docs need to explain the difference between known, implemented,
  capable, and selected harnesses.

## Workstreams

### W1. Contract And Fixtures

- Add `triage-v2.schema.json` in source and API docs.
- Add `routing-v1.schema.json` and `routing-outcome-v1.schema.json`.
- Add prompt `triage_v2.txt`.
- Add fixtures for sensitive finding, architectural refactor, careful
  refactor, trivial atomic change, invalid route, unavailable harness, and v1
  compatibility.
- Keep v1 tests green.

### W2. Policy Parser And Linter

- Extend profile parsing with routing configuration.
- Add policy linting independent of model execution.
- Implement rule evaluation as a pure function with deterministic tests.
- Validate unknown keys, route references, fallbacks, sandbox values, timeout
  values, and unavailable harness behavior.

### W3. Classification Merge

- Implement deterministic repo facts and safety signals.
- Merge model classification with deterministic observations.
- Ensure deterministic safety signals can escalate but not silently
  de-escalate.
- Add unit tests for security/auth/secrets/PII detection, module counts, failed
  check signals, and namespaced taxonomy extensions.

### W4. Prompt Composer

- Add versioned package prompt fragments.
- Compose and hash the exact prompt before remediation.
- Write `remediation-<iteration>-prompt.txt`.
- Enforce prompt size ceilings without truncating safety-critical sections.
- Add tests for section ordering, hash stability, fragment inclusion, and
  untrusted triage guidance boundaries.

### W5. Orchestrator Integration

- Add route resolution between triage and remediation.
- Let remediation use the effective route instead of only
  `config.remediation_*`.
- Record routing artifacts and routing events.
- Write outcome metadata after remediation and checks.
- Add fake-harness end-to-end tests for accepted proposal, policy override,
  fallback, route unavailable, budget ceiling before remediation, and v1
  degradation path.

### W6. Harness Boundary Hardening

- Add per-harness executable resolution.
- Strengthen capability validation for role, sandbox, timeout, cancellation,
  output capture, and cost reporting.
- Add thin installed-CLI adapters for Claude, Gemini, OpenCode, and KiloCode
  after the shared fake-harness contract is green.
- Document what each adapter must prove before it can be enabled by default:
  non-interactive invocation, stdin prompt support, model selection semantics,
  timeout/cancellation behavior, output capture, error classification, and any
  unsupported capability fields.

### W7. Operator Surfaces

- Implement `revrem policy lint`.
- Implement `revrem triage explain`.
- Implement read-only `revrem policy review` suggestions.
- Update replay/TUI state to display routing decisions from artifacts/events.
- Update DevEx docs with examples and failure diagnosis.

## Quality Gates

This plan is not complete until:

- Existing v1 triage behavior and tests remain unchanged for profiles not using
  routing.
- v2 schema fixtures validate against source and docs schemas.
- Routing profile parsing rejects unknown keys and invalid routes.
- Policy tests cover first-match order, no-match defaults, policy override,
  model escalation requests, forbidden de-escalation, fallback, unavailable
  route, and budget-limited route selection.
- Prompt composer tests prove stable hashes and no silent truncation of safety
  sections.
- End-to-end fake-harness tests prove the selected remediation route changes
  the actual command request.
- Event schema tests cover routing events and replay rendering.
- Artifact path tests prove routing and prompt artifacts are excluded from
  auto-commits.
- Documentation shows one portable Codex-only profile and one multi-harness
  profile using the installed Claude, Gemini, OpenCode, and KiloCode adapters,
  with clear fallback guidance for machines where those CLIs are absent.
- `meminit check --format json` passes.
- `./scripts/dev-check` passes before PR.

## Implementation Closeout Evidence

> **Status note (2026-05-20, post-review remediation).** A critical review after
> the initial closeout found that several items below were claimed complete but
> failed in practice. They have since been fixed; see *Post-Review Remediation*
> at the end of this section. Read the bullet list as the intended contract, not
> as independently re-verified at original-closeout time.

The implementation now satisfies the plan's first complete routing slice:

- `triage-v2` exists as a source schema, API-doc schema, prompt, parser path,
  and fixture-backed contract. Existing v1 triage behavior remains covered for
  profiles that do not enable routing.
- Routing writes `routing-<iteration>.json`,
  `remediation-<iteration>-prompt.txt`, and
  `routing-outcome-<iteration>.json`; routing JSON references the exact prompt
  path, hash, byte count, fragments, model proposal, effective route, policy
  decision, and fallback history.
- The routing artifact records proposal presence and proposal acceptance
  honestly. If the triage proposal is absent, the artifact records that absence;
  if policy changes any proposed executable field, the artifact records a
  policy override and the overridden fields.
- Policy resolution is deterministic, validates route references, validates
  routing taxonomy values, rejects circular fallback chains, respects remaining
  wall-clock budget, and applies only explicit configured fallbacks.
- Prompt composition is deterministic and includes execution frame, route
  rationale, confirmed/rejected/needs-more-info findings, previous failed
  checks, configured policy fragments, untrusted triage guidance, and
  verification expectations.
- Codex, Claude, Gemini, OpenCode, KiloCode, and fake harness adapters share
  the same non-interactive command-construction boundary. Operators can set
  per-harness executable paths through `runtime.harness_executables` or the
  `--harness-bin HARNESS=EXECUTABLE` CLI override.
- Routing emits `routing_decision` and `routing_outcome` events through
  `events.jsonl`; replay and TUI run-monitor views render the route and
  outcome without invoking a model or printing full prompts.
- `summary.json` includes first-class prompt and routing artifact paths while
  preserving artifact privacy by not inlining prompt content.
- Operator surfaces include `revrem policy lint`, `revrem triage explain`, and
  read-only `revrem policy review --artifact-dir <run-dir>`.
- DevEx documentation includes portable Codex-only and multi-harness examples,
  per-harness executable configuration, routing artifacts, event kinds,
  prompt sensitivity, policy linting, triage explain, and policy review.
- Scenario fixtures cover sensitive finding, architectural refactor, careful
  refactor, trivial atomic change, invalid route, unavailable harness, and v1
  compatibility.

### Post-Review Remediation (2026-05-20)

A post-closeout critical review found three blocking defects and one safety gap
that the original `494 passed` suite masked because its policy tests used a
tier vocabulary the shipped product never uses. All are now fixed with
regression coverage:

- **B1 — multi-harness routing was unusable with timeouts.** Non-Codex harnesses
  were marked `timeout_supported=false`, and the route capability check rejected
  any route that set `timeout_seconds`, so the documented multi-harness profile
  failed both `revrem policy lint` and runtime resolution. RevRem enforces
  timeouts through its own subprocess wrapper, so the gate was wrong; it has been
  removed and `timeout_supported` is now metadata only.
- **B2 — escalation ranking was dead for the real tier names.** `TIER_RANK` used
  `frontier`/`midtier`/`efficient`, but the product ships
  `frontier-thinking`/`midtier-coder`/`efficient-coder`/`security-specialist`.
  Ranking now uses the canonical names, and an uncomparable model proposal keeps
  the policy route instead of being silently applied (closing a policy-bypass).
- **B3 — five of six prompt fragments were missing.** Only
  `engineering-principles` shipped; the composer hard-crashed on the rest. All
  six fragments now ship, and `prompts/fragments/*.txt` is included in
  `package-data` so they survive installed builds.
- **M1 — deterministic safety backstop never reached `domain_tags_any` rules.**
  Deterministic detection wrote only to `safety_signals`. It now also folds the
  detected domain into `domain_tags` (retaining `sensitive-domain:*` provenance),
  so a security rule escalates even when the model omits the tag.
- **M2 — Gemini adapter passed an empty `--prompt`.** Adapters were verified
  against the installed CLIs; the Gemini adapter now passes the prompt as the
  value of `-p/--prompt`. Claude, OpenCode, and Kilo adapters were confirmed
  correct. Adapter contract tests now assert the exact non-interactive argv and
  prompt-delivery channel per CLI.

Remaining known follow-ups (not blocking this slice):

- Live end-to-end smoke runs against each installed CLI (the contract tests
  encode the verified argv but do not invoke live models).
- `src/code_review_loop/cli.py` has grown into a large module and should be
  split in a later refactor.

Verification evidence for this closeout:

- `./scripts/dev-check` passed on 2026-05-20 after remediation with `513
  passed`, Ruff clean, mypy clean, and Meminit checks clean.
- `git diff --check` must also pass on the completed branch immediately before
  opening the PR.

## Risks And Mitigations

- **Prompt injection through triage.** Mitigation: deterministic prompt
  composer; untrusted triage draft is quoted below policy instructions; model
  output cannot override route, checks, sandbox, or budget.
- **Misclassification routes sensitive work to a cheap model.** Mitigation:
  deterministic safety signals, forbidden de-escalation, strict policy tests,
  and route audit artifacts.
- **Policy grammar grows into a programming language.** Mitigation: small
  first-match grammar, no arbitrary expressions, lint command, documented
  examples.
- **Harness fragmentation.** Mitigation: capability contract, fake harness
  contract tests, explicit known/installed/enabled state, and thin adapters
  that defer provider-specific advanced features until the common path is
  stable.
- **Cost and time surprises.** Mitigation: resolve budget before each model
  boundary, route fallbacks only when policy allows them, record missing cost
  data as unsupported rather than zero.
- **Artifact privacy.** Mitigation: local-first defaults, gitignored run
  artifacts, redaction on export, and no full prompt printing by default.
- **Operator confusion when triage and remediation use different harnesses.**
  Mitigation: progress output, `triage explain`, and TUI Routing panel make the
  cross-harness handoff explicit.

## Open Questions For Peer Review

### OQ1. Does `triage.contract = "v2"` imply routing?

Options:

- **A: v2 always means routing.** Simple mental model, but it prevents using
  v2 classification and richer prompt handoff before teams trust automated
  route selection.
- **B: v2 permits classification-only and routing.** `triage.contract = "v2"`
  selects the schema/prompt; `triage.routing.enabled` separately controls
  whether the route is executable.
- **C: split into separate contracts.** For example,
  `triage-classification-v1` and `triage-routing-v1`. This is explicit, but
  creates more schema churn before the shape is proven.

Recommendation: choose **B**. v2 should unlock the richer structured payload,
while routing remains separately gated. This lets operators adopt safer prompt
handoff and audit artifacts first, then enable executable routing once policy
and harness adapters are trusted.

### OQ2. Can project policy select a more expensive route than user defaults?

Options:

- **A: project policy may freely escalate.** Best for repo safety, but a cloned
  repository could unexpectedly spend the operator's model budget.
- **B: project policy may request escalation, but user/profile budget and
  route ceilings remain authoritative.** Safety-sensitive repos can express
  desired routing, while the operator retains cost control.
- **C: project policy can only de-escalate.** Cost-safe, but undermines the
  main purpose of repo-local policy for security or architecture-sensitive
  work.

Recommendation: choose **B**. Project config may require a minimum route tier
for certain risks, but effective execution is still bounded by user-selected
profile, CLI flags, and budgets. If the required route violates the operator's
ceilings, RevRem should fail before remediation with a clear diagnostic instead
of silently downgrading.

### OQ3. What happens when the preferred route exceeds remaining budget?

Options:

- **A: automatically choose the cheapest allowed fallback.** Keeps runs moving,
  but can silently assign hard work to an underpowered model unless the audit is
  read carefully.
- **B: use only explicit policy-approved fallbacks.** The route may fall back
  when the policy author named that behavior; otherwise the run stops before
  remediation.
- **C: ask interactively.** Good for watched local runs, but not viable for
  hooks, CI, or hands-off operation.

Recommendation: choose **B**, with optional **C** later for interactive TUI
mode. The default CLI and CI behavior should never invent a cheaper route. A
fallback is safe only when the policy explicitly says the fallback is
acceptable for that class of work.

### OQ4. How strict should deterministic sensitive-signal detection be?

Options:

- **A: broad detection.** Escalate on security/auth/secrets/PII terms in
  findings, paths, failed checks, and changed-file names. This over-escalates
  some benign changes but reduces safety misses.
- **B: narrow detection.** Escalate only on high-confidence structured review
  findings or known sensitive path patterns. This reduces cost but misses more
  ambiguous issues.
- **C: two-tier detection.** High-confidence deterministic signals force
  escalation; low-confidence signals add a warning and prevent de-escalation
  below mid-tier.

Recommendation: choose **C**. Security-sensitive misses are worse than some
over-escalation, but broad keyword matching alone is noisy. A two-tier signal
model gives policy useful safety brakes without routing every mention of
"token" or "auth" to the most expensive model.

### OQ5. Should user-defined prompt fragments ship in the first routing release?

Options:

- **A: built-in fragments only.** Safest and easiest to validate, but less
  useful for repos with strong local engineering principles.
- **B: allow user-defined fragments from configured files.** Useful and
  extensible, but requires path safety, deterministic ordering, provenance, and
  clear prompt-injection boundaries.
- **C: allow repo-defined fragments only after an explicit trust flag.** Safer
  for cloned repos, but still lets maintainers opt into project-local guidance.

Recommendation: choose **B for user-profile fragments and C for repo fragments**.
User-profile fragments are operator-controlled and should be allowed in v1.
Repo-local fragments should require an explicit trust setting because a cloned
repository should not silently inject arbitrary remediation instructions into a
write-capable model.

### OQ6. Should prompt artifacts be first-class summary artifacts?

Options:

- **A: reference prompt artifacts only from routing JSON and events.** Keeps
  `summary.json` smaller but makes prompts harder for operators and reports to
  discover.
- **B: include prompt artifacts in `summary.artifact_paths`.** Improves
  discoverability and replay/report integration, but requires privacy-aware
  handling wherever summary artifacts are exported.
- **C: include only hashes in `summary.json`.** Privacy-conservative, but makes
  diagnosis more cumbersome.

Recommendation: choose **B**, with redaction/export safeguards. The prompt is
the exact instruction sent to the remediator; it is central audit evidence and
should be discoverable from `summary.json`. Export surfaces must treat it as
sensitive transcript-like data.

### OQ7. Should multi-route fan-out happen inside one loop iteration?

Options:

- **A: one route per iteration only.** Simple, preserves current loop
  semantics, and keeps outcome attribution clear.
- **B: sequential fan-out inside one iteration.** Allows security and docs
  findings to route to different models in one pass, but complicates budgets,
  artifact naming, and check attribution.
- **C: parallel fan-out inside one iteration.** Fastest, but the riskiest for
  conflicting edits, budget control, cancellation, and operator comprehension.

Recommendation: choose **A for this plan**. Multi-route fan-out should be a
separate plan after single-route routing is reliable. If later implemented,
start with sequential fan-out and disjoint write scopes before considering any
parallel execution.

### OQ8. Should installed non-Codex CLIs be enabled in the first slice?

Options:

- **A: Codex plus fake harness only.** Lowest implementation risk, but leaves
  the central multi-harness value untested despite the CLIs being installed.
- **B: thin adapters for all installed CLIs.** Best validates the actual
  product goal, but requires a shared adapter contract and honest unsupported
  capability metadata.
- **C: one additional adapter first.** Reduces scope, but risks overfitting the
  route contract to the first non-Codex CLI.

Recommendation: choose **B**, constrained to a thin common surface. Because
Gemini, Claude, OpenCode, and KiloCode CLIs are installed and working locally,
the first routing slice should include adapters for all four if they can meet
the minimum non-interactive contract. If one CLI lacks a required capability,
mark that capability unsupported and route around it rather than blocking the
others.

## Recommended First Slice

The first implementation should be intentionally narrow:

1. Add v2 schema/prompt and routing artifacts.
2. Implement the shared adapter contract and fake-harness tests first.
3. Add thin non-interactive adapters for installed Codex, Claude, Gemini,
   OpenCode, and KiloCode CLIs.
4. Implement policy tiers and prompt composition.
5. Prove route selection changes the actual remediation command across fake
   harness fixtures and at least one smoke fixture per installed CLI.
6. Ship `revrem policy lint` and `revrem triage explain`.
7. Document multi-harness routing as an active supported path on machines with
   the configured CLIs installed, with explicit fallbacks for machines where a
   chosen CLI is absent.

This slice gives operators the core value, better remediation prompts and
auditable model choice, while validating the multi-harness design against the
CLIs available on the maintainer workstation.

## Pointers

- Current triage implementation: `src/code_review_loop/triage.py`
- Current triage prompt: `src/code_review_loop/prompts/triage_v1.txt`
- Current triage schema: `src/code_review_loop/schemas/triage-v1.schema.json`
  and `docs/52-api/schemas/triage-v1.schema.json`
- Loop orchestration: `src/code_review_loop/cli.py`
- Profile system: `src/code_review_loop/profiles.py`
- Harness registry and capability contract: `src/code_review_loop/harnesses.py`
  and REVREM-ADR-010
- Artifact schema and canonical writes: REVREM-ADR-004
- Triage v1 ADR: REVREM-ADR-006
- Event/replay contract: REVREM-ADR-008
- Budget/cancellation contract: REVREM-ADR-009
- Post-launch roadmap and harness sequencing: REVREM-PLAN-003
