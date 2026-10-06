---
document_id: REVREM-PLAN-013
type: PLAN
title: System-wide deployment readiness
status: Draft
version: '0.1'
last_updated: '2026-10-06'
owner: GitCmurf
area: planning
docops_version: '2.0'
template_type: plan-standard
template_version: '2.0'
description: Current model verification, installed-package acceptance, promotion and
  rollback evidence.
---

> **Document ID:** REVREM-PLAN-013
> **Owner:** GitCmurf
> **Status:** Draft
> **Version:** 0.1
> **Last Updated:** 2026-10-06
> **Type:** PLAN
> **Area:** planning
> **Description:** Current model verification, installed-package acceptance, promotion and rollback evidence.


<!-- MEMINIT_SECTION: title -->
<!-- AGENT: The title should be concise and descriptive of the plan. -->

# PLAN: System-wide deployment readiness

<!-- MEMINIT_SECTION: executive_summary -->
<!-- AGENT: Write a 2-3 sentence executive summary of the plan's objectives and timeline. -->

## 0. Executive Summary

Prepare the post-v0.5.0 checkout for use across local repositories on the
operator's account. Readiness means current Codex models execute, the installed
wheel works outside this checkout, and promotion has a verified rollback path.

<!-- MEMINIT_SECTION: current_state -->
<!-- AGENT: Describe the current state, baseline metrics, or existing gaps. -->

## 1. Current State

At the start of this review, `feat/tui-live-runs` was clean at `1d0b91b`, two
commits ahead of its tracking branch. The package still identifies as 0.5.0;
the repository contains later live-TUI, model-catalog and bounded final-review
remediation work. PLAN-007 records its implementation, while older roadmap
sections describe historical baselines. No new public release is implied.

The initial deployment path copied source into a shared interpreter and installed
only `tomli-w`, although package metadata also requires `jsonschema`. It did not
exercise an installed wheel or offer an activation/rollback transaction.
The development gate omitted import contracts and silently skipped missing mypy.
An editor test also assumed an unqualified `python` command was on PATH.

<!-- MEMINIT_SECTION: decision -->
<!-- AGENT: List the decisions, goals, or milestones established by this plan. -->

## 2. Plan and Milestones

1. Package the current Codex model family with validated effort ranges.
2. Prove account access with bounded live probes and a disposable review/fix loop.
3. Promote isolated wheel installations only after checks pass; retain rollback.
4. Exercise the installed CLI, resources, model catalog, doctor, reports and loops
   from an unrelated repository.
5. Commit local changes and prepare the exact deployment command. Public releases,
   tags, pushes, hooks and global profile changes remain separate operator actions.

<!-- MEMINIT_SECTION: workstreams -->
<!-- AGENT: Outline workstreams, tasks, or components that need execution. -->

## 3. Workstreams

- `catalog.toml` includes Astra, Sol 6.1, Sol 6 and Luna 6 without relying on a
  pre-existing Codex cache. Legacy selections remain available.
- `examples/current-codex` provides bounded Astra review, Luna v2 triage and
  Sol 6.1 remediation, with repository-native checks supplied by the operator.
- `promote-stable` builds the exact clean commit, installs dependencies into a
  per-release environment, verifies it and switches a shared launcher pointer.
  Manifests record wheel hashes and installed dependency versions. Failed builds
  preserve the active release. Rollback is offline and verifies the old release.
- Development checks require mypy and import-linter. The editor test invokes the
  running Python interpreter, independent of shell aliases.
- Live v1 triage exposed contradictory fingerprint guidance when Codex supplies
  no stable `f1:` ID. The prompt now permits the same explicit comment-order
  fallback as v2; schema validation still rejects null confirmed fingerprints.
- Astra's explicit empty-diff response was classified as unknown after a
  successful repair. A full-response matcher now accepts that narrow form;
  mixed prose, failed review statements and explicit findings remain non-clear.

<!-- MEMINIT_SECTION: verification_matrix -->
<!-- AGENT: List verification criteria, verification steps, and exit gates. -->

## 4. Verification Plan

Verification record (2026-10-06; update with final results before handoff):

| Check | Evidence |
| --- | --- |
| Codex CLI | 0.160.1 |
| `gpt-6-astra` | Live read-only exec returned the expected marker |
| `gpt-6.1-sol` | Live read-only exec returned the expected marker |
| `gpt-6-luna` | Live read-only exec returned the expected marker |
| `gpt-6.1-luna` | HTTP 400: not supported with this ChatGPT account |
| Model metadata | Codex local cache: Astra/Sol low through ultra; Luna low through max |
| Promotion regressions | Activation, rollback, failed build, dirty tree, lock and quoted paths tested |
| Full gates | Pending final run |
| Installed acceptance | Pending final run |

The [official model guide](https://developers.openai.com/api/docs/guides/latest-model)
lists Astra 6, Sol 6.1 and Luna 6. API effort settings and Codex's local model
metadata are different interfaces; the packaged effort ranges target Codex.
Re-run account checks with
`REVREM_LIVE_CURRENT_MODELS=1 ./.venv/bin/python -m pytest tests/test_live_current_models.py -q`.
Raw model transcripts and local generated artifacts must remain outside Git.

The first three-model loop detected and fixed an injected `a - b` regression,
and its arithmetic checks passed. Its overall run did not clear: v1 triage first
returned a null fingerprint, and the fixture left setup files untracked, which
correctly failed the built-in cleanliness gate. The installed v2 acceptance with a fully tracked baseline passed review, triage,
remediation and both checks. It exposed the empty-diff final-status gap above;
repeat acceptance follows that regression fix.

<!-- MEMINIT_SECTION: risk_management -->
<!-- AGENT: Identify risks, impact, and mitigation strategies. -->

## 5. Risks and Mitigations

- Model access is account-specific and time-sensitive. A catalog entry is not
  proof of access; live probes are opt-in and bounded.
- Installations need package-index access unless dependencies and build tools
  are cached. Activation occurs only after successful installation and checks.
- First migration preserves legacy launcher backups; automatic managed rollback
  becomes available after a second promotion. Old environments are not deleted.
- Public versioning, branch merge, release provenance/Scorecard follow-ups and
  secondary-provider live certification remain distinct from local Codex use.
- Host sandbox restrictions can prevent socket/TUI tests. Record the execution
  context and run those gates with suitable permissions; do not skip them to
  claim a pass.

<!-- MEMINIT_SECTION: version_history -->
<!-- AGENT: Track version changes with dates, authors, and change summaries. -->

## 6. Version History

| Version | Date     | Author    | Changes       |
| ------- | -------- | --------- | ------------- |
| 0.1     | 2026-10-06 | GitCmurf | Initial draft |
