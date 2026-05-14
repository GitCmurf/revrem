---
document_id: REVREM-ADR-002
type: ADR
title: Use revrem as the public package identity
status: Draft
version: '0.1'
last_updated: '2026-05-10'
owner: GitCmurf
docops_version: '2.0'
area: release
description: Decision to use revrem as the public distribution name while retaining
  code-review-loop as a compatibility command alias
keywords:
- packaging
- pypi
- identity
- release
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
- REVREM-ADR-001
---

# ADR: Use revrem as the public package identity

## Context

RevRem was originally packaged under the distribution name `code-review-loop`
while the operator-facing command and public repository identity converged on
`revrem`. That split was acceptable before public distribution, but it creates
unnecessary friction for PyPI, README installation instructions, package
badges, release artifacts, issue reports, and external search.

As of 2026-05-10, `https://pypi.org/project/revrem/` returns no project page.
The name therefore appears available for first publication, subject to the
normal risk that availability can change before the release workflow actually
publishes.

`REVREM-ADR-001` remains the broader decision to package the loop as a Python
CLI rather than a copied script or skill-only implementation. This ADR narrows
the public package identity for that CLI.

## Content

## Decision

Use `revrem` as the public Python distribution name and primary project
identity. Keep `code-review-loop` as a compatibility console-script alias for
existing local scripts during the 0.x series.

## Rationale

- The public repository, README title, and human-facing command already use
  `revrem`; PyPI should match the name a user sees and types.
- A single public identity reduces confusion in issue reports, CI logs, package
  badges, and install instructions.
- Retaining the `code-review-loop` command alias protects existing local
  workflows without forcing the distribution name to preserve pre-launch
  vocabulary.
- The import package can remain `code_review_loop`; Python import names often
  differ from distribution names, and changing imports would add churn without
  user value.

## Alternatives Considered

- **Keep `code-review-loop` as the distribution name.** Rejected because the
  README would need to explain a three-name split: repository `revrem`, command
  `revrem`, package `code-review-loop`.
- **Publish both names.** Deferred. It would increase release complexity and
  risk stale or confusing packages. A transitional metapackage can be revisited
  only if external usage of `code-review-loop` as a PyPI name materializes.
- **Rename the import package to `revrem`.** Rejected for this phase. It would
  touch every source and test module while providing little external benefit.

## Consequences

- `pyproject.toml` uses `project.name = "revrem"`.
- Release artifacts, SBOM filenames, badges, and install documentation should
  prefer `revrem`.
- Both console commands remain available:
  - `revrem`
  - `code-review-loop`
- Any future removal of `code-review-loop` as a console command must go through
  a deprecation release and changelog entry.

## Validation

- Packaging tests assert the distribution name, project URLs, and version
  consistency.
- Build and `twine check` must pass before any release tag is published.
- F2 must verify the public install path before README claims `pipx install
  revrem` as the normal user path.

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-05-10 | GitCmurf | Initial package identity decision |
