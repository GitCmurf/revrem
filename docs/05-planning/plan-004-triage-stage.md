---
document_id: REVREM-PLAN-004
type: PLAN
title: Triage Stage as a Routing and Prompt-Construction Layer
status: Draft
version: '0.1'
last_updated: '2026-05-16'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Redefines the optional triage stage from a JSON-summariser into a routing and prompt-construction layer that selects the remediation harness and model, builds the remediation prompt, and emits auditable rationale — under user-configurable if-then policy and with full harness portability across Codex, Claude, Gemini, opencode, and Kilo.
keywords:
  - triage
  - routing
  - remediation
  - harnesses
  - policy
  - audit
  - prompt-construction
related_ids:
  - REVREM-PRD-001
  - REVREM-PLAN-003
  - REVREM-ADR-003
  - REVREM-DEVEX-001
  - REVREM-TEST-001
---

# PLAN: Triage Stage as a Routing and Prompt-Construction Layer

## Context

Triage is currently the loop's quietest stage. It runs optionally after the
review pass, calls the configured harness with the `triage_v1` prompt, and
emits a JSON document conforming to `schemas/triage-v1.schema.json`:
`confirmed_findings`, `rejected_findings`, `needs_more_info`,
`implementation_order`, `verification_commands`, `parsing_warnings`. The
loop then either drops the structured handoff into the remediation prompt
or, on `triage.on_invalid=stop`, fails the run.

This contract works as a *filter* — it dedupes false positives and orders
fixes — but it stops well short of what an operator actually needs the
triage stage to do. Today triage:

- Cannot influence *which* model or harness runs remediation.
- Cannot adapt the remediation prompt's depth, framing, or "definition of
  done" to the kind of work being asked for.
- Cannot escalate sensitive or architectural findings to a stronger model,
  or de-escalate trivial fixes to a cheaper one.
- Cannot pull in additional context (related modules, architectural
  notes, security policies) the way a senior engineer triaging a review
  would.
- Produces an artifact that is read by the loop but is rarely re-read by
  the operator — there is no auditable log of *why a route was chosen*,
  because no route is ever chosen.

This plan reframes triage as the loop's **routing and prompt-construction
layer**: the stage where a small, deliberate model decides *which*
remediator to hand the work to, *what prompt* that remediator gets, and
*why*. The output is a contract that the loop orchestrator can execute
without further interpretation, plus an auditable record that lets the
operator refine the routing policy over time.

The motivation is concrete:

1. **Cost shape.** Running a frontier model on every remediation pass is
   wasteful when most findings are typo-class or single-file refactors.
   Running a cheap model on a security finding or a cross-module
   refactor is dangerous.
2. **Model and harness diversity.** RevRem's harness registry already
   reserves slots for Codex, Claude, Gemini, opencode, and Kilo. Only
   Codex is implemented today, but the loop must not bake "Codex
   everywhere" assumptions into the routing layer.
3. **Prompt quality.** A remediator does materially better work when the
   prompt names the engineering principles in play, lists the affected
   modules, sets a concrete definition-of-done, and supplies the
   verification commands. Triage already produces most of these
   ingredients — it just doesn't assemble them.
4. **Operator trust.** If RevRem starts choosing models, the operator
   must be able to inspect *every* choice after the fact and adjust the
   policy. Routing without an audit trail is unacceptable.

## Non-Goals

- Implementing the Claude, Gemini, opencode, or Kilo harness adapters.
  That work is gated by REVREM-PLAN-003 and is a prerequisite for
  *exercising* this plan end-to-end, but it is not part of this plan's
  deliverables.
- Replacing the existing `triage_v1` JSON contract. The new triage output
  is a superset; the existing fields remain and must continue to validate
  against the v1 schema (a new `routing` block is additive under a
  bumped `triage-v2` prompt/schema pair).
- Building a hosted policy-management UI. Policies live in the TOML
  profile system already proposed in REVREM-PRD-001.
- Training a custom triage model. The triage stage is a normal headless
  CLI call; the model behind it is whatever the configured harness
  routes to.

## North Star

> **Triage is the loop's dispatcher: it reads the review, decides who
> should fix what and with what prompt, explains its reasoning in an
> auditable artifact, and hands the orchestrator a directly executable
> remediation plan.**

Three properties are non-negotiable:

- **Harness-agnostic.** The routing block names a harness and model
  from the harness registry; it never embeds harness-specific
  invocation details. The orchestrator translates that block into a
  `PhaseCommandRequest` exactly as it does today.
- **Policy-driven, not model-driven.** The triage *model* proposes a
  route; the *policy* validates, overrides, or rejects it. A model
  cannot silently escalate to a more expensive route without a policy
  rule that permits it.
- **Auditable by default.** Every route decision writes a
  `routing-<iteration>.json` artifact recording inputs, policy rules
  consulted, model rationale, final route, prompt sent, and outcome
  (after remediation completes). These artifacts are local, never
  committed, and form the corpus for refining policy.

## Proposed Architecture

### Stage redefinition

The triage stage's responsibility expands from one job to four:

1. **Filter** (existing). Confirm, reject, or defer findings; produce
   `implementation_order` and `verification_commands`. Unchanged
   contract.
2. **Classify**. Tag the run with a small set of routing-relevant
   attributes drawn from the confirmed findings: domain tags
   (`security`, `auth`, `secrets`, `pii`, `concurrency`, `migration`,
   `public-api`, `build`, `docs-only`, `trivial`, …), blast radius
   (modules touched, estimated LOC), refactor depth (`atomic`,
   `localised`, `cross-module`, `architectural`), and risk indicators
   carried over from any failed checks in the previous iteration.
3. **Route**. Choose a `(harness, model, reasoning_effort, sandbox,
   timeout)` tuple by evaluating the user's policy rules against the
   classification. The model proposes; the policy adjudicates.
4. **Compose**. Build the remediation prompt — including any
   model-tier-specific framing (engineering principles, definition of
   done, atomic task list) — and emit it as a literal string that the
   orchestrator passes to the remediator without further templating.

### Output contract (triage v2, additive)

The triage artifact gains a `routing` block. Existing keys are
preserved. Sketch:

```jsonc
{
  // existing v1 fields, unchanged
  "confirmed_findings": [...],
  "rejected_findings":  [...],
  "needs_more_info":    [...],
  "implementation_order": [...],
  "verification_commands": [...],
  "parsing_warnings": [...],

  // new in v2
  "classification": {
    "domain_tags": ["security", "auth"],
    "blast_radius": {"modules": 2, "estimated_loc": 40},
    "refactor_depth": "localised",
    "risk_signals": ["failed_check:bandit"],
    "prior_iteration_outcome": "review_only"
  },
  "routing": {
    "proposed_by": "model",       // or "policy_override"
    "harness": "claude",
    "model":   "claude-opus-4-7",
    "reasoning_effort": "high",
    "sandbox": "workspace-write",
    "timeout_s": 1800,
    "policy_rule_id": "sec-frontier-thinking",
    "rationale": "Confirmed finding tagged `security`+`auth`; policy `sec-frontier-thinking` requires a frontier thinking model. No de-escalation permitted.",
    "remediation_prompt": "<<<full literal prompt string>>>",
    "fallback": {
      "harness": "codex",
      "model":   "gpt-5.2-thinking",
      "reason":  "if claude harness unavailable or budget cap hit"
    }
  }
}
```

The schema bumps to `triage-v2`; the prompt template bumps to
`triage-v2.txt`. The loop continues to accept v1 outputs from harnesses
that have not yet been upgraded; routing then defaults to the profile's
configured remediation harness/model and a "policy not applied" warning
is recorded.

### Policy system

Policies are user-configurable, declarative, and live alongside profiles
in `~/.config/code-review-loop/profiles.toml` (per REVREM-PRD-001) with
a per-repo override at `.revrem/policy.toml`. Sketch:

```toml
[triage.policy]
# Ordered: first matching rule wins, unless `mode = "all"` is set.
mode = "first-match"

[[triage.policy.rule]]
id = "sec-frontier-thinking"
when.domain_tags_any = ["security", "auth", "secrets", "pii"]
then.route = "frontier-thinking"
then.prompt_addendum = "engineering-principles + security-checklist"
then.allow_model_override = false

[[triage.policy.rule]]
id = "arch-refactor-frontier"
when.refactor_depth = "architectural"
when.blast_radius.modules_gte = 6
then.route = "frontier-thinking"
then.prompt_addendum = "engineering-principles"

[[triage.policy.rule]]
id = "midtier-careful-refactor"
when.refactor_depth_in = ["localised", "cross-module"]
when.blast_radius.modules_lt = 6
then.route = "midtier-coder"
then.prompt_addendum = "definition-of-done"

[[triage.policy.rule]]
id = "trivial-atomic"
when.refactor_depth = "atomic"
then.route = "efficient-coder"
then.prompt_addendum = "atomic-task-list"

# Named routes resolve to harness/model tuples. Keeping the indirection
# means a user can swap "frontier-thinking" globally without editing
# every rule.
[triage.routes.frontier-thinking]
harness = "claude"
model   = "claude-opus-4-7"
reasoning_effort = "high"

[triage.routes.midtier-coder]
harness = "codex"
model   = "gpt-5.2-mini"

[triage.routes.efficient-coder]
harness = "gemini"
model   = "gemini-3-flash-lite"
```

Policy evaluation happens *after* the triage model returns. The model's
proposed route is recorded; if a policy rule fires with
`allow_model_override = false`, the policy's route wins and the model's
proposal is preserved in the audit log alongside the override reason.

### Prompt construction

Triage emits a literal `remediation_prompt` string. Construction is
deterministic given the classification and the matched policy rule:

- **Base.** The confirmed findings (with fingerprints), affected paths,
  rationale, and verification commands.
- **Addenda.** Named, versioned prompt fragments shipped with RevRem:
  `engineering-principles`, `security-checklist`, `definition-of-done`,
  `atomic-task-list`. Users may register their own fragments under
  `[triage.prompt_fragments]`.
- **Tier-appropriate framing.** Frontier routes get longer rationale
  and explicit "consider these principles" framing; efficient routes get
  flat numbered task lists with no preamble.
- **Carry-over from failed checks.** When the prior iteration failed a
  check, the triage prompt includes the failure context and the
  composed remediation prompt names which findings address which
  failure.

This is a deliberate move away from "the orchestrator builds the
prompt." Triage owns prompt assembly so that the audit record contains
*exactly* what the remediator received.

### Audit log

For every triage run the loop writes, in the existing run directory:

- `triage-<iteration>.json` — the v2 payload above.
- `routing-<iteration>.jsonl` — append-only events: classification,
  candidate policy rules, model proposal, policy decision, final
  route, prompt hash. One JSON object per line.
- `routing-<iteration>.outcome.json` — written by the orchestrator
  after remediation completes: returncode, wall-clock, token/cost (when
  the harness reports it), whether verification commands passed,
  whether subsequent iterations were needed, and a pointer to the
  remediation artifact.

These files are local, gitignored by the existing run-artifact rules,
and form a corpus the operator can grep, summarise, or hand to a future
"refine my policy" subcommand. A later `revrem policy review` command
can scan the corpus and propose policy diffs ("rule
`midtier-careful-refactor` fired 38 times; in 11 of those cases a
follow-up iteration was needed — consider tightening
`blast_radius.modules_lt` to 4").

### Harness portability

The routing block names `harness` and `model` from the harness
registry. The orchestrator:

1. Calls `validate_harness_name` and `require_implemented_harness` on
   the chosen route.
2. If the chosen harness is reserved-but-unimplemented, applies the
   `fallback` block from the routing payload.
3. If no fallback applies, fails the iteration with a structured
   diagnostic (`revrem.triage.route_unavailable`) rather than
   silently degrading to the profile default.

The triage stage itself is also a harness call. Profiles get a new
`[triage]` section mirroring `[review]` and `[remediation]`:

```toml
[triage]
enabled = true
harness = "codex"
model   = "gpt-5.2-mini"
reasoning_effort = "medium"
on_invalid = "warn"   # existing knob, unchanged
```

Any implemented harness can host triage; capabilities already expose
`triage_supported`.

## Workstreams

Each workstream below is independently shippable behind a feature flag
(`triage.routing.enabled = false` by default during rollout). The full
sequence assumes the harness adapters from REVREM-PLAN-003 land in
parallel; if they slip, workstreams 3–5 still ship and route only
between Codex models.

### W1. Schema and prompt v2 (foundational)

- Add `triage-v2.schema.json` as a superset of v1.
- Add `triage_v2.txt` prompt teaching the model to emit the
  `classification` and `routing.rationale` fields *only* — the
  orchestrator will overwrite `harness`, `model`, and
  `remediation_prompt` if policy overrides apply.
- Keep v1 fully accepted; v2 is opt-in via `triage.contract = "v2"`.

### W2. Classification taxonomy

- Define and document the closed set of `domain_tags`, `refactor_depth`
  values, and `risk_signals`.
- Treat the taxonomy as a small versioned vocabulary (`taxonomy-v1`)
  with explicit deprecation policy. The triage prompt embeds the
  vocabulary so off-vocab tags are rejected at parse time.

### W3. Policy engine

- TOML schema and validator for `[triage.policy]`, `[triage.routes]`,
  `[triage.prompt_fragments]`.
- Pure-function policy evaluator: `classify → rules[] → route + rule_id`.
- Unit-test matrix covering rule ordering, `allow_model_override`,
  unknown-route resolution, missing-harness fallback.

### W4. Prompt fragment library

- Ship `engineering-principles`, `security-checklist`,
  `definition-of-done`, `atomic-task-list` as versioned text files
  under `src/code_review_loop/prompts/fragments/`.
- Composer that joins base + addenda deterministically (stable
  ordering, hashed for audit).

### W5. Orchestrator integration

- Read `routing` block from triage payload.
- Apply policy; resolve route to `PhaseCommandRequest`; handle
  fallback; emit `routing-<iteration>.jsonl` events.
- After remediation, write `routing-<iteration>.outcome.json`.
- Diagnostic codes: `revrem.triage.route_unavailable`,
  `revrem.triage.policy_override_applied`,
  `revrem.triage.policy_no_match`.

### W6. CLI and TUI surface

- `revrem triage explain <run-id>` — render the routing artifact as a
  human-readable summary (classification, rule fired, route, prompt
  hash, outcome).
- `revrem policy lint` — validate policy TOML without running the loop.
- `revrem policy review` — corpus analysis over recent
  `routing-*.outcome.json` files; suggests policy diffs.
- Run Monitor (per REVREM-PRD-001) gains a "Routing" panel showing the
  current iteration's chosen route, rule id, and rationale.

### W7. Audit corpus + privacy

- Confirm the new artifacts are covered by existing
  `.gitignore`/run-directory rules.
- Document in the runbook that `remediation_prompt` may contain code
  excerpts and is therefore subject to the operator's existing data
  policy when sharing run directories.

## Open Questions (for peer discussion)

1. **Vocabulary vs free-form tags.** A closed taxonomy is auditable
   but brittle. A free-form tag set is flexible but hard to write
   policy against. The current proposal is closed-with-deprecation;
   the alternative is closed-core-plus-namespaced-extensions
   (`x:my-team:concurrency`). Which scales better?
2. **Where does classification *actually* live?** Options: (a) the
   triage model emits classification and the policy engine consumes
   it; (b) a deterministic classifier runs on the review output and
   the model only fills gaps; (c) both — the model proposes and the
   deterministic classifier vetoes. (c) is most defensible but the
   most code.
3. **Model override of policy.** The current proposal forbids the
   model from overriding `allow_model_override = false` rules.
   Should there be a `model_request_override` mechanism (model can
   *request* an escalation with rationale, policy can opt in to
   allowing it per-rule)?
4. **Cost-aware routing.** Should policy rules be able to reference
   per-harness cost ceilings (`when.budget_remaining_lt = 0.20`)?
   The harness capability schema already reserves a `cost_reporting`
   field but most harnesses return `"none"` today.
5. **Multi-route fan-out.** Some iterations contain both a security
   finding and a docs-only finding. Should triage be able to split
   the work across two remediator calls in one iteration, or is the
   right answer "one route per iteration, let the loop's next pass
   pick up the other tag"? The latter is simpler and preserves the
   loop's existing iteration semantics.
6. **Prompt-fragment versioning.** If a user pins
   `engineering-principles@v1` and v2 ships, do we warn, auto-upgrade,
   or hard-fail? Suggest: warn-and-pin until the operator opts in.
7. **Triage harness ≠ remediation harness — is that surprising?** A
   profile could end up with triage on Codex and remediation routed
   to Claude. That is the *intent*, but it may confuse first-run
   operators. The Run Monitor should make the cross-harness handoff
   explicit.

## Risks

- **Policy complexity creep.** TOML if-then is approachable until it
  isn't. Mitigation: keep the rule grammar deliberately small; ship
  `revrem policy lint` from day one; document the corpus-driven
  refinement workflow.
- **Triage model misclassification.** A model that mistags a security
  finding as `trivial` would route to a cheap remediator. Mitigation:
  policy rules with `allow_model_override = false` form the safety
  net; the audit log makes misclassification detectable; consider a
  "shadow route" mode where the chosen route runs but the proposed
  route is logged for comparison.
- **Harness drift.** Adapters for Claude/Gemini/opencode/Kilo land at
  different times and with different capabilities. Mitigation: the
  capability schema already gates this; policy resolution must
  surface "route requires capability X, harness Y lacks it" cleanly.
- **Prompt size.** Composed remediation prompts can become large for
  cross-module refactors. Mitigation: hash + length checks; warn
  above a per-route threshold; never silently truncate.

## Quality Gates

Before this plan can be considered shipped:

- Triage v2 schema validates a corpus of fixture payloads including
  every routing rule example documented in `[triage.policy]`.
- Policy engine has full-coverage unit tests with property-based
  rule-ordering tests.
- Orchestrator integration has end-to-end fake-harness tests for:
  policy override applied, model proposal accepted, fallback fires,
  unimplemented-harness rejection, v1 payload degradation path.
- Documentation: a worked example in `docs/70-devex` showing a
  multi-finding review routed across two harnesses, including the
  full audit trail and a `revrem policy review` invocation.
- Backwards compatibility: every existing profile continues to work
  unchanged with `triage.routing.enabled = false`.

## Out of Scope (explicit deferrals)

- Auto-tuning policy from the audit corpus. We ship the corpus and
  `revrem policy review` (read-only suggestions); automated
  rule-writing is a follow-up.
- Cross-run policy sharing (a "policy registry"). Local-first first;
  sharing is a separate plan if there is demand.
- A web UI for inspecting the audit corpus. The CLI surface is the
  shipping target.

## Pointers

- Existing triage implementation: `src/code_review_loop/triage.py`,
  `src/code_review_loop/prompts/triage_v1.txt`,
  `src/code_review_loop/schemas/triage-v1.schema.json`.
- Harness registry and capability schema:
  `src/code_review_loop/harnesses.py`.
- Finding fingerprint algorithm (consumed by classification):
  REVREM-ADR-003.
- Profile system and TUI surfaces this plan extends: REVREM-PRD-001.
- Post-launch roadmap that sequences harness adapter work:
  REVREM-PLAN-003.
