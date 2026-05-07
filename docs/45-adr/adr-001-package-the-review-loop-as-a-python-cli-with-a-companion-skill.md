---
document_id: REVREM-ADR-001
type: ADR
title: Package the review loop as a Python CLI with a companion skill
status: Draft
version: '0.1'
last_updated: '2026-04-30'
owner: GitCmurf
area: architecture
docops_version: '2.0'
template_type: adr-standard
template_version: '2.0'
description: Distribution decision for cross-repo review-loop automation
keywords:
- packaging
- codex
- skills
---

> **Document ID:** REVREM-ADR-001
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 0.1
> **Last Updated:** 2026-04-30
> **Type:** ADR
> **Area:** architecture
> **Description:** Distribution decision for cross-repo review-loop automation


# REVREM-ADR-001: Package the review loop as a Python CLI with a companion skill

<!-- MEMINIT_SECTION: title -->

<!-- AGENT: The title should be concise and descriptive of the decision being made. -->

- **Date decided:** 2026-04-30
- **Status:** Draft
- **Deciders:** GitCmurf
- **Consulted:** Codex
- **Informed:** Users of local agentic review workflows
- **References:** `REVREM-DEVEX-001`, `REVREM-TEST-001`

## 1. Context & Problem Statement

<!-- MEMINIT_SECTION: context -->

<!-- AGENT: Describe the motivating problem, constraints, and forces. State the scope and what is explicitly out of scope. -->

The review-remediation loop started as a Meminit repo-local script. That was a
good proof of concept, but it is the wrong long-term distribution boundary for
a workflow intended to run against many local repositories. Copying the script
would create version drift, while a skill-only implementation would bury
executable behavior in agent instructions rather than testable code.

The utility must remain easy to run from arbitrary Linux repositories, preserve
operator-visible artifacts, and keep nested Codex execution bounded by default.

## 2. Decision Drivers

<!-- MEMINIT_SECTION: decision_drivers -->

<!-- AGENT: List the key forces that influence the decision (e.g., latency, cost, safety, operability, compliance, UX, delivery risk). -->

- Cross-repo reuse without copy-paste drift.
- Testable executable behavior with deterministic fake-runner tests.
- Minimal runtime dependencies.
- Clear operator guidance for long-running local automation.
- Compatibility with Codex skills as guidance, not as the implementation store.
- Straightforward installation on a development machine.

## 3. Options Considered

<!-- MEMINIT_SECTION: options -->

<!-- AGENT: For each option, capture summary, evidence, pros, cons, and risks. Present options fairly. -->

- **Option A:** Keep a repo-local script in Meminit
  - Pros: fastest path and already working.
  - Cons: not discoverable from other repositories and encourages copying.
  - Evidence / benchmarks: the original script and tests were useful but lived
    under Meminit-specific paths.
  - Risks / unknowns: future fixes may not propagate to other checkouts.
- **Option B:** Package the loop as a Python CLI utility
  - Pros: testable, installable, versionable, and easy to expose on `PATH`.
  - Cons: requires a small standalone repository and release discipline.
  - Evidence / benchmarks: the loop has no non-stdlib runtime dependencies.
  - Risks / unknowns: CI needs a reliable way to install Meminit for DocOps
    checks until Meminit distribution is finalized.
- **Option C:** Implement only as a Codex skill
  - Pros: convenient agent instructions and easy discovery by Codex.
  - Cons: poor home for executable logic, tests, versioned CLI behavior, and
    subprocess failure handling.
  - Evidence / benchmarks: the existing workflow needs unit tests around
    command construction and loop transitions.
  - Risks / unknowns: skill copies can drift from actual executable behavior.

## 4. Decision Outcome

<!-- MEMINIT_SECTION: decision -->

<!-- AGENT: Clearly state the chosen option with rationale tied to decision drivers. Define scope/applicability and status gates. -->

- **Chosen option:** Option B, with a companion skill later for agent guidance.
- **Why this option:** The Python CLI keeps the loop testable and installable.
  A skill can then describe when and how to use it without becoming the source
  of executable behavior.
- **Scope/Applicability:** Applies to local Linux development machines and
  repositories where `codex review --base <branch>` and `codex exec` are valid.
- **Status gates:** Move to In Review once tests and DocOps checks pass in the
  standalone repo. Move to Approved once at least one external repository has
  successfully run a dry run and a real review loop.

## 5. Consequences

<!-- MEMINIT_SECTION: consequences -->

<!-- AGENT: Document positive outcomes, negative trade-offs, and any follow-up work needed. -->

- Positive: one source of truth for loop behavior, tests, and docs.
- Negative / trade-offs: another small tool repository must be maintained.
- Follow-up migrations / cleanups: replace the Meminit repo-local script with
  either a compatibility wrapper or documentation that invokes this utility.

## 6. Implementation Notes

<!-- MEMINIT_SECTION: implementation -->

<!-- AGENT: Include implementation plan, owners, rollout strategy, and monitoring needs. -->

- Plan / milestones:
  - Extract current behavior into `src/code_review_loop/cli.py`.
  - Add package metadata and console entry point `code-review-loop`.
  - Preserve and adapt the existing test coverage.
  - Add DevEx, testing, and greenfield bootstrap docs.
  - Create a companion Codex skill after the CLI stabilizes.
- Owners: GitCmurf.
- Backward compatibility / rollout strategy: keep the Meminit script in place
  until users have installed this utility and the Meminit docs are updated.
- Telemetry / monitoring to add: no network telemetry. Use local artifacts and
  `summary.json` for operator visibility.

## 7. Validation & Compliance

<!-- MEMINIT_SECTION: validation -->

<!-- AGENT: Specify tests, tooling checks, operational checks, and success metrics. -->

- Tests required: `tests/test_cli.py` and one real dry run from another repo.
- Tooling checks: `pytest`, `ruff`, `mypy`, and `meminit check`.
- Operational checks: verify artifact layout and terminal progress output.
- Success metrics or acceptance criteria: the CLI can be installed once and run
  from Meminit without referencing a repo-local script path.

## 8. Alternatives Rejected

<!-- MEMINIT_SECTION: alternatives -->

<!-- AGENT: List rejected options with one-line reason each. -->

- Keeping only the Meminit script: rejected because the workflow is explicitly
  cross-repo.
- Skill-only packaging: rejected because executable behavior belongs in tested
  code.
- Symlinking the Meminit script into other repositories: rejected because it is
  fragile and does not create a clean utility development boundary.

## 9. Supersession

<!-- MEMINIT_SECTION: supersession -->

<!-- AGENT: Track what this ADR supersedes and what supersedes it. -->

- Supersedes: none
- Superseded by: none

## 10. Notes for Agents

<!-- MEMINIT_SECTION: agent_notes -->

<!-- AGENT: Include key entities/terms for RAG, code anchors this ADR governs, and known gaps/TODOs. -->

- Key entities/terms for RAG: `code-review-loop`, Codex review, remediation
  loop, bounded automation, DevEx.
- Code anchors (paths, modules, APIs) this ADR governs:
  `src/code_review_loop/cli.py`, `tests/test_cli.py`, `pyproject.toml`.
- Known gaps / TODOs: companion Codex skill is not yet created.

## 11. Version History

<!-- MEMINIT_SECTION: version_history -->

<!-- AGENT: Track version changes with dates, authors, and change summaries. -->

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-04-30 | GitCmurf | Initial draft |
