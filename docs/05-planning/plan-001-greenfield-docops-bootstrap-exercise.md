---
document_id: REVREM-PLAN-001
type: PLAN
title: Greenfield DocOps bootstrap exercise
status: Draft
version: '0.1'
last_updated: '2026-04-30'
owner: GitCmurf
docops_version: '2.0'
area: docops
description: Notes and follow-up improvements from bootstrapping this utility with
  Meminit
keywords:
- meminit
- greenfield
- docops
---

> **Document ID:** REVREM-PLAN-001
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 0.1
> **Last Updated:** 2026-04-30
> **Type:** PLAN
> **Area:** docops
> **Description:** Notes and follow-up improvements from bootstrapping this utility with Meminit

# PLAN: Greenfield DocOps bootstrap exercise

## Context

This repository was intentionally bootstrapped as a greenfield Meminit project
while extracting the review loop from Meminit into a standalone utility. The
exercise is both a real utility setup and a live check of Meminit greenfield
ergonomics.

## Content

### Completed bootstrap steps

- Ran `meminit init --root /tmp/code-review-loop-stage --format json`.
- Confirmed the generated skeleton includes `AGENTS.md`, `docops.config.yaml`,
  governance files, templates, and `docs/70-devex`.
- Added package scaffolding for a Python console utility.
- Added governed project docs with deterministic document IDs:
  `REVREM-DEVEX-001`, `REVREM-ADR-001`, `REVREM-PLAN-001`, and
  `REVREM-TEST-001`.
- Added local and CI verification commands for unit tests, linting, typing, and
  DocOps compliance.

### Greenfield observations

- `meminit init` used the staging directory name as `project_name`, so the
  generated value was `code-review-loop-stage`. This is understandable, but a
  greenfield command would benefit from a `--project-name` option.
- The generated `repo_prefix` was `REVREM`, which is acceptable for
  `code-review-loop`, but a `--repo-prefix` option would make first-run output
  deterministic without post-editing config.
- The generated config had `docs/70-devex` mapped as `REF`; it did not include
  a `DEVEX` document type even though this repository needs DevEx docs. The
  project config was amended to add `DEVEX`.
- `meminit context --format json` emitted duplicate `WIP-` entries in
  `excluded_filename_prefixes`. This is harmless for compliance but creates
  avoidable noise in machine-readable context.
- `meminit init` generated `docs/00-governance/DocOps_Constitution.md`, which
  `meminit check` immediately warned about because filenames are expected to be
  lowercase kebab-case. This project renamed it to
  `docs/00-governance/docops-constitution.md`.
- `meminit new --list-types` reflected the live config after editing, which
  made the issue easy to detect and correct.

### Candidate Meminit improvements

- Add `meminit init --project-name <NAME>`.
- Add `meminit init --repo-prefix <PREFIX>` with schema validation before
  writing files.
- Include `DEVEX` in the default generated `document_types` when
  `docs/70-devex` is scaffolded.
- Deduplicate `excluded_filename_prefixes` in context output.
- Generate `docops-constitution.md` instead of `DocOps_Constitution.md`, or
  make the checker explicitly exempt generated governance files if that casing
  is intentional.
- Consider a greenfield preset for utility repositories that scaffolds
  `.editorconfig`, `.gitignore`, README, CI, and a basic test strategy document.

### Closeout criteria

- `python -m pytest -q` passes.
- `python -m code_review_loop --help` works.
- `code-review-loop --dry-run --quiet-progress --summary-format json` works
  after editable installation.
- `meminit doctor --format json` passes.
- `meminit check --format json` passes.
- The final repository exists at `/home/cmf/code/code-review-loop`.
