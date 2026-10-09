---
document_id: REVREM-PLAN-008
type: PLAN
title: Codex Review Clear Classification Sprint
status: Draft
version: '0.2'
last_updated: '2026-06-27'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: Focused sprint plan to improve native Codex review clear-output classification
  while preserving fail-closed unknown-review behavior.
keywords:
- review-classification
- clear-prose
- codex-review
- triage
related_ids:
- REVREM-PLAN-004
- REVREM-PLAN-007
---

# PLAN: Codex Review Clear Classification Sprint

## Context

RevRem treats native `codex review` output differently from prompted external
review harnesses. Prompted harnesses receive a RevRem-controlled contract and
must return explicit `REVIEW_STATUS: clear|findings` or structured findings.
Native Codex review does not expose a RevRem-controlled status line, so RevRem
uses conservative prose and finding-marker heuristics in
`src/code_review_loop/core/review_interpretation.py`.

That fail-closed approach is correct: an unclassified review must remain
`unknown (review_unknown)` rather than being silently treated as clear. However,
live dogfood has shown that native Codex often emits clear prose that is
obviously safe to classify but outside the current corpus. One recent example:

> No actionable correctness, safety, or maintainability defects were found in
> the changed code. The added TypeScript surfaces typecheck cleanly; targeted
> Vitest execution could not be completed in this read-only sandbox because Vite
> attempted to write a temporary bundled config file.

`REVREM-PLAN-004` already reserves triage as a strict, auditable classification
stage, but using triage as the primary answer for every native clear phrase
would add cost and latency while hiding useful deterministic classifier gaps.
This sprint therefore improves the deterministic classifier first and treats
triage as a bounded fallback option only after measurement.

## Goals

- Increase native Codex clear-classification recall for common, safe
  "no actionable defects" review summaries.
- Preserve fail-closed behavior for ambiguous prose, contrastive findings, and
  any output containing Codex finding bullets or review-comment headings.
- Make `unknown` diagnostics more useful so future misses explain whether the
  classifier lacked a clear signal or rejected one for safety.
- Build fixture-based evidence from historical `.revrem/runs/**/review*.txt`
  artifacts so changes are measured, not anecdotal.
- Decide whether a strict triage-rescue path is worth implementing after the
  deterministic classifier improvements land.

## Non-Goals

- Do not treat positive sentiment such as "looks good", "LGTM", or "patch is
  okay" as clear without an explicit status or structured empty findings.
- Do not relax prompted external harness behavior. Claude, Gemini, OpenCode,
  and Kilo still need explicit or structured status because RevRem controls
  their review prompt.
- Do not let triage convert review findings into clear before the existing
  finding-confirmation contract runs.
- Do not parse provider stderr as the review outcome except for existing
  provider-control diagnostics.

## Design Principles

1. **Fail closed.** The default outcome for unfamiliar prose remains `unknown`.
2. **Generalize only negated issue statements.** Accept "no/not/without/zero"
   forms tied to concrete issue nouns; reject vague praise.
3. **Color within the lines of review scope.** Clear prose must refer to changed
   code, diff, patch, reviewed paths, or an equivalent review scope unless it is
   an exact known safe phrase.
4. **Contrastive clauses win.** "No defects, but there is a bug" is never clear.
5. **Environmental test disclaimers are neutral, not clear.** A sandbox/tooling
   limitation may be ignored only when paired with an otherwise strong clear
   statement.
6. **Diagnostics are part of the product.** Unknown-review summaries should say
   why clear was not accepted.

## Sprint Slices

### S1 — Table-Driven Clear-Prose Grammar

**Intent.** Replace the growing ad hoc clear phrase list with a small
table-driven grammar for native Codex clear statements.

**Implementation.**

- Add domain terms: `correctness`, `security`, `safety`, `maintainability`,
  `reliability`, and `behavior`.
- Add issue nouns: `issue(s)`, `bug(s)`, `defect(s)`, `regression(s)`,
  `finding(s)`, `problem(s)`, and `failure(s)`.
- Add severity/scope prefixes: `actionable`, `introduced`, `new`, `blocking`,
  `material`, `discrete`, `substantive`, `remaining`, and `open`.
- Add negated forms:
  - `no <prefix/domain> <issue-noun>`
  - `not found|identified|detected|observed|seen`
  - `did not find|identify|detect|observe|see`
  - `without revealing|surfacing`
  - `zero <prefix/domain> <issue-noun>`
- Keep exact phrase matching as a compatibility layer, but make the generated
  grammar the primary path for new variants.

**Acceptance.**

- Existing clear-prose tests remain green.
- The observed "correctness, safety, or maintainability defects" case is clear.
- Positive but vague text remains unknown.
- Contrastive issue text remains unknown or findings, never clear.

### S2 — Environmental Disclaimer Handling

**Intent.** Prevent sandbox/test/tooling limitations from blocking clear status
when the review also has a strong clear signal.

**Implementation.**

- Add a neutral-disclaimer detector for sentences that explicitly mention:
  `read-only sandbox`, `permission denied`, `could not write`, `temporary bundled
  config`, `network unavailable`, `credential unavailable`, or comparable
  execution-environment constraints.
- Require the disclaimer to be scoped to verification execution, not the changed
  code.
- Strip or neutralize those spans before affirmative issue detection only when a
  strong clear signal is present in the same review.

**Acceptance.**

- "Tests could not run in a read-only sandbox" does not block an otherwise clear
  review.
- "The code fails because it writes in a read-only path" still blocks clear.
- Diagnostics record that an environmental disclaimer was neutralized.

### S3 — Unknown-Review Diagnostics

**Intent.** Make future misses actionable without reading classifier internals.

**Implementation.**

- Extend `review_status_diagnostics()` with:
  - `clear_candidate_present`
  - `clear_candidate_source`
  - `clear_blocked_by`
  - `environmental_disclaimer_present`
  - `environmental_disclaimer_neutralized`
- Keep the terminal status-debug line compact, but include the block reason when
  status is `unknown`.
- Preserve the existing JSON sidecar shape by adding fields without removing or
  renaming current keys.

**Acceptance.**

- Unknown diagnostics distinguish "no clear signal" from "clear signal rejected
  because affirmative issue prose was present".
- Existing status-debug tests remain green with updated expectations where
  necessary.

### S4 — Historical Fixture Measurement

**Intent.** Measure recall and false-clear risk against real local artifacts.

**Implementation.**

- Add a developer-only script or pytest helper that scans
  `.revrem/runs/**/review*.txt` when present.
- Classify each artifact before and after the grammar changes.
- Emit a compact report with:
  - previously unknown now clear
  - previously findings unchanged
  - clear candidates rejected and why
  - any risky-looking examples requiring manual review
- Store a small curated fixture set under `tests/fixtures/review_status/` for
  durable regression tests; do not commit private local run artifacts.

**Acceptance.**

- Curated fixtures cover at least:
  - native clear with environmental disclaimer
  - native clear with safety/defect terminology
  - contrastive bug after a clear clause
  - review-comment heading with clear preface
  - vague praise
- The measurement report has no unexplained findings-to-clear flips.

### S5 — Optional Triage Rescue Decision

**Intent.** Decide whether to add a bounded model-backed rescue path for native
Codex reviews that remain unknown after deterministic classification.

**Candidate design.**

- Add profile/runtime option, default off:
  `review_unknown_triage_rescue = false`.
- Only run rescue when:
  - harness is native Codex,
  - status is `unknown`,
  - no Codex finding bullets are present,
  - no review-comment heading is present,
  - no provider/tool denial is present.
- Rescue prompt must require strict JSON:
  `{"status":"clear|findings|unknown","reason":"...","evidence":["..."]}`.
- Any invalid response remains `unknown`.
- `findings` from rescue should route through normal triage/remediation; `clear`
  may stop only when the evidence quotes an explicit no-defect statement.

**Decision gate.**

Implement S5 only if S1-S4 leave a meaningful number of safe-looking unknowns
and deterministic grammar would become too broad to cover them safely.

## Test Plan

- Unit tests in `tests/test_cli_review_helpers.py` for every grammar family and
  every negative/contrastive case.
- Diagnostics tests for clear phrase used, clear phrase blocked, and
  environmental disclaimer neutralization.
- A fixture-driven test module for curated real-world native Codex outputs.
- Existing integration tests must continue to prove:
  - unknown review status fails closed,
  - finding bullets win over clear prefaces,
  - prompted harnesses require explicit/structured status.
- Full local gate: `./scripts/dev-check`.

## Release Gate

This sprint is complete only when:

- `detect_review_status()` accepts the known safe native clear variants without
  accepting vague praise.
- The classifier's negative corpus includes every newly generalized grammar
  family.
- Unknown diagnostics are specific enough to guide the next miss.
- Historical fixture measurement shows no unexplained false-clear risk.
- `CHANGELOG.md`, `REVREM-DEVEX-001`, and `REVREM-TEST-001` are updated if the
  public/operator contract changes.
- `./scripts/dev-check` passes.

## Open Questions

- Should the historical-artifact scanner be a permanent developer tool or only a
  test helper?
- Should S5 live behind a profile field, a runtime flag, or both if it is
  implemented?
- Should native Codex eventually receive a wrapped prompt that asks it to emit
  `REVIEW_STATUS`, or is that too invasive for `codex review`'s native review
  surface?
