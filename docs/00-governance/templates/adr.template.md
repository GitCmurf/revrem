---
document_id: {{document_id}}
type: {{type}}
title: {{title}}
status: {{status}}
version: "0.1"
last_updated: {{date}}
owner: {{owner}}
area: {{area}}
docops_version: "2.0"
template_type: adr-standard
template_version: "2.0"
---

<!-- MEMINIT_METADATA_BLOCK -->

> **Document ID:** {{document_id}}
> **Owner:** {{owner}}
> **Status:** {{status}}
> **Version:** 0.1
> **Last Updated:** {{date}}
> **Type:** {{type}}

# {{document_id}}: {{title}}

<!-- MEMINIT_SECTION: title -->

<!-- AGENT: The title should be concise and descriptive of the decision being made. -->

- **Date decided:** {{date}}
- **Status:** {{status}}
- **Deciders:** [names/roles]
- **Consulted:** [stakeholders consulted]
- **Informed:** [who must be notified]
- **References:** [issues/PRs/spikes/incidents/benchmarks]

## 1. Context & Problem Statement

<!-- MEMINIT_SECTION: context -->

<!-- AGENT: Describe the motivating problem, constraints, and forces. State the scope and what is explicitly out of scope. -->

[Describe the problem here.]

## 2. Decision Drivers

<!-- MEMINIT_SECTION: decision_drivers -->

<!-- AGENT: List the key forces that influence the decision (e.g., latency, cost, safety, operability, compliance, UX, delivery risk). -->

[List drivers here.]

## 3. Options Considered

<!-- MEMINIT_SECTION: options -->

<!-- AGENT: For each option, capture summary, evidence, pros, cons, and risks. Present options fairly. -->

- **Option A:** [name]
  - Pros:
  - Cons:
  - Evidence / benchmarks:
  - Risks / unknowns:
- **Option B:** [name]
  - Pros:
  - Cons:
  - Evidence / benchmarks:
  - Risks / unknowns:
- **Option C:** [name]
  - Pros:
  - Cons:
  - Evidence / benchmarks:
  - Risks / unknowns:

## 4. Decision Outcome

<!-- MEMINIT_SECTION: decision -->

<!-- AGENT: Clearly state the chosen option with rationale tied to decision drivers. Define scope/applicability and status gates. -->

- **Chosen option:** [Option A/B/C]
- **Why this option:** [brief rationale tied to drivers]
- **Scope/Applicability:** [where this applies; boundaries]
- **Status gates:** [what must be true to move from Draft -> In Review -> Approved]

## 5. Consequences

<!-- MEMINIT_SECTION: consequences -->

<!-- AGENT: Document positive outcomes, negative trade-offs, and any follow-up work needed. -->

- Positive:
- Negative / trade-offs:
- Follow-up migrations / cleanups:

## 6. Implementation Notes

<!-- MEMINIT_SECTION: implementation -->

<!-- AGENT: Include implementation plan, owners, rollout strategy, and monitoring needs. -->

- Plan / milestones:
- Owners:
- Backward compatibility / rollout strategy:
- Telemetry / monitoring to add:

## 7. Validation & Compliance

<!-- MEMINIT_SECTION: validation -->

<!-- AGENT: Specify tests, tooling checks, operational checks, and success metrics. -->

- Tests required (unit/integration/e2e):
- Tooling checks (lint/format/static analysis):
- Operational checks (dashboards/alerts/runbooks):
- Success metrics or acceptance criteria:

## 8. Alternatives Rejected

<!-- MEMINIT_SECTION: alternatives -->

<!-- AGENT: List rejected options with one-line reason each. -->

[List rejected options here.]

## 9. Supersession

<!-- MEMINIT_SECTION: supersession -->

<!-- AGENT: Track what this ADR supersedes and what supersedes it. -->

- Supersedes: [ID or none]
- Superseded by: [ID or none]

## 10. Notes for Agents

<!-- MEMINIT_SECTION: agent_notes -->

<!-- AGENT: Include key entities/terms for RAG, code anchors this ADR governs, and known gaps/TODOs. -->

- Key entities/terms for RAG:
- Code anchors (paths, modules, APIs) this ADR governs:
- Known gaps / TODOs:

## 11. Version History

<!-- MEMINIT_SECTION: version_history -->

<!-- AGENT: Track version changes with dates, authors, and change summaries. -->

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | {{date}} | {{owner}} | Initial draft |
