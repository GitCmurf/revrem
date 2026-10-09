---
document_id: REVREM-PLAN-013
type: PLAN
title: System-wide deployment readiness
status: Draft
version: '0.2'
last_updated: '2026-10-09'
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
> **Version:** 0.2
> **Last Updated:** 2026-10-09
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

At the initial 2026-10-06 check, the account-wide command resolved to uv's
`revrem` environment and reported **0.4.0**. Initial readiness work used isolated
rehearsal destinations under `/tmp`. On 2026-10-09, the operator promoted commit
`1d90958` account-wide with TUI support and development checks enabled. Both PATH
aliases now report 0.5.0; the wheel hash and doctor from an unrelated repository
were verified. Legacy launcher backups are present; this first managed install
has no previous managed release for automatic rollback. The local
`origin/main` tracking ref predates 142 commits on
this branch at the first implementation commit; integration into the public
release branch still needs an explicit decision.

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
  successful repair. No-changes claims now require fresh Git confirmation of
  HEAD, the index and working tree against the merge base, plus no non-artifact
  untracked files. Unknown prose alone cannot clear a run; evidence is retained.
- The cancellation integration test waited for an events file created before
  controlled cancellation begins. It now waits for a phase-start event. No
  timeout was increased and early interruption remains a distinct result.

<!-- MEMINIT_SECTION: verification_matrix -->
<!-- AGENT: List verification criteria, verification steps, and exit gates. -->

## 4. Verification Plan

Verification record (2026-10-06, Linux / Python 3.12):

| Check | Evidence |
| --- | --- |
| Codex CLI | 0.160.1 |
| `gpt-6-astra` | Live read-only exec returned the expected marker |
| `gpt-6.1-sol` | Live read-only exec returned the expected marker |
| `gpt-6-luna` | Live read-only exec returned the expected marker |
| `gpt-6.1-luna` | HTTP 400: not supported with this ChatGPT account |
| Model metadata | Codex local cache: Astra/Sol low through ultra; Luna low through max |
| Promotion regressions | Activation, rollback, failed build, dirty tree, lock and quoted paths tested |
| Full regression suite | 2,007 passed, 10 opt-in provider cases skipped; 256.85 seconds |
| Static and governance gates | Ruff, mypy (117 source files), 10 import contracts and DocOps pass |
| DocOps | 46 documents pass; one pre-existing filename warning in PLAN-005 |
| Installed acceptance | Minimal and TUI wheel installs pass models, doctor, clear/findings loops, reports and expert profiles |
| Live installed loop | Astra review, Luna v2 triage, Sol 6.1 repair, checks and final audit: clear in 92.70 seconds |
| Empty final comparison | Diagnostic confirms HEAD, index and worktree against the merge base, with zero non-artifact untracked files |
| Installed TUI | All four workspaces navigate at 80x24 and 120x40 |
| Promotion and rollback | TUI promotion, minimal upgrade and offline rollback all pass in `/tmp` |
| Repeatable account probes | Three opt-in tests pass in 48.26 seconds |

The [official model guide](https://developers.openai.com/api/docs/guides/latest-model)
lists Astra 6, Sol 6.1 and Luna 6. API effort settings and Codex's local model
metadata are different interfaces; the packaged effort ranges target Codex.
Re-run account checks with
`REVREM_LIVE_CURRENT_MODELS=1 ./.venv/bin/python -m pytest tests/test_live_current_models.py -q`.
Raw model transcripts and local generated artifacts must remain outside Git.
The final pytest hook passed all tests but pre-commit noticed documentation
updates made while it ran. The non-test hooks were rerun after those updates;
pytest was not repeated for documentation-only changes.

The operator explicitly authorised CodeRabbit review on 2026-10-09, resolving
the earlier disclosure approval block. CodeRabbit CLI 0.9.0 reviewed the 23
changed files in `1d0b91b..a177cc1` with `--committed --fresh --deep`. It exited
successfully with one minor finding and no reported uncovered files. Its
completion message was "Review completed with unverified findings". Local
regressions reproduced the finding: Python optimization disabled four acceptance
assertions. Those checks now raise explicit errors, including under `-O`.

Local review also reproduced a false clear when running from a subdirectory:
`git ls-files` omitted untracked files elsewhere and returned paths incompatible
with root-relative artifact exclusions. Confirmation now scans the whole
repository with root-relative names. Regressions cover outside files, a nested
directory named `.revrem`, and legitimate root-level run artifacts.

The fresh verification review covered all 24 changed files, including the new
acceptance regression tests. It exited successfully with one major finding:
remove `ultra` because the public API guide lists `max` as the highest effort.
This finding was rejected after checking the exact runtime. Codex CLI 0.162.0's
model metadata, fetched on 2026-10-09, advertises `ultra` for Astra, Sol 6.1 and
Sol 6. Three bounded, read-only live calls through RevRem's Codex adapter at
`ultra` each returned the required marker and exit 0. The catalog describes
Codex settings, not the public API parameter contract. Both review passes
reported no uncovered files; the verification pass raised no further issues
with the acceptance checks or Git confirmation fix. No actionable external
findings remain. Raw review output stays outside Git.

The 2026-10-09 development gate passed: 2,015 tests passed and 10 opt-in provider
cases were skipped in 217.80 seconds. Ruff, mypy (117 source files), all 10
import contracts, DocOps doctor and all 46 governed documents passed. The
existing PLAN-005 filename warning remains. The three `ultra` probes ran
separately from the default suite and passed.

The first three-model loop detected and fixed an injected `a - b` regression,
and its arithmetic checks passed. Its overall run did not clear: v1 triage first
returned a null fingerprint, and the fixture left setup files untracked, which
correctly failed the built-in cleanliness gate. The installed v2 acceptance with a fully tracked baseline passed review, triage,
remediation and both checks. It exposed the empty-diff final-status gap above;
repeat acceptance after Git confirmation finished `clear` with no check failures.
The recorded result is from the installed wheel, using real model calls, not the
source checkout or fake harness.

<!-- MEMINIT_SECTION: risk_management -->

### GitHub integration: PR #52

The full branch is open at <https://github.com/GitCmurf/revrem/pull/52>. Initial
hosted tests exposed personal-profile and Codex dependencies in TUI fixtures.
After isolating those fixtures and updating urllib3 to 2.8.0 and virtualenv to
21.7.12, commit `0bf22b4` passed both Python jobs, all four Linux/macOS package
jobs and the Action smoke job. These seven GitHub Actions checks are now
required on `main`, with an up-to-date base required. Local validation of that
commit passed 2,016 tests with 10 skipped.

CodeRabbit's hosted full review was skipped at its 100-file limit; its CLI full
review was rejected at 150 files. Both counted 177 reviewable files. Those
statuses do not establish a clean review. A scoped CLI review covered all 61
changed runtime files and returned seven minor findings and one major finding,
with an unverified-findings warning. Reproductions confirmed the wizard,
telemetry, process decoding, timeout editor and unsupported-effort issues. The
major request to change explicit `latest` semantics was rejected: the behavior
is intentional and tested; its stale CLI help was corrected. The suggestion to
advertise Spark capabilities was also rejected because current Codex metadata
does not establish them. Unknown Codex models continue to warn and pass through.

A second runtime CLI pass again covered all 61 files and returned eight minor
findings with the same unverified-findings warning. Regressions cover static
preset false positives, forced-cleanup timeout/output, split error references,
boolean token counts, recovery commit context, catalog parse diagnostics and
invalid effort persistence. The preset-cloning hint now names the Profiles
workspace. These fixes do not turn the scoped reviews into full-PR coverage.

Greptile also reviewed the PR and reported route-clear persistence, acceptance
isolation, saved-model effort cycling and live check-state defects. Regression
tests cover the reproduced failures. A follow-up finding showed wizard replay
could discard restored routes when preview and launch reloaded the disk profile.
Replay now preserves changed triage settings in a private `.revrem/tmp/wizard` profile
snapshot used by both paths, including when routing on disk has been disabled.
Acceptance now isolates operator settings,
including malformed personal configuration and Git overrides. The full local development gate passed 2,049 tests with 10 opt-in skips, Ruff,
mypy, all 10 import contracts and DocOps. The later wizard snapshot regression
also passed its focused wizard suite. Non-pytest pre-commit hooks passed.
Qodo review is blocked by an inactive subscription. Paid RevRem dogfooding remains disabled.
No merge, version bump, tag or public release has been performed. Subsequent PR
fixes do not automatically update the installed `1d90958` release.

<!-- AGENT: Identify risks, impact, and mitigation strategies. -->

## 5. Risks and Mitigations

- Model access is account-specific and time-sensitive. A catalog entry is not
  proof of access; live probes are opt-in and bounded.
- Installations need package-index access unless dependencies and build tools
  are cached. Activation occurs only after successful installation and checks.
- First migration preserves legacy launcher backups; automatic managed rollback
  becomes available after a second promotion. Old environments are not deleted.
- Public versioning, branch merge, release provenance/Scorecard follow-ups and
  fresh secondary-provider certification remain distinct from local Codex use.
  TASK-006 already records historical Gemini proof; the other provider probes
  were not requested or run in this pass.
- Host sandbox restrictions can prevent socket/TUI tests. Record the execution
  context and run those gates with suitable permissions; do not skip them to
  claim a pass.

<!-- MEMINIT_SECTION: version_history -->
<!-- AGENT: Track version changes with dates, authors, and change summaries. -->

## Deployment sequence

1. Activate the verified clean commit
   with `./scripts/promote-stable --extras tui`. This replaces both account-wide
   launchers, retaining the old uv symlinks as `*.before-managed-install` backups.
   Use the promotion script for subsequent updates; uv still owns the retained
   old environment and its upgrade/uninstall commands can overwrite or remove
   these command paths. Do not run both update mechanisms for RevRem.
2. Confirm `./scripts/promote-stable --status`, `revrem --version`, and
   `revrem doctor` from the target repository with its actual test command.
3. Merge the example current-Codex profile into existing user or project
   profiles only if desired. Do not replace established profile configuration.
4. Complete branch integration through PR #52 and decide public versioning
   separately. No tag, release, Git hook or global profile mutation was performed.
5. For broader provider adoption, refresh provider-specific live evidence and
   resolve the documented external-prompt truncation coverage work (TD-008).
   The remaining ANSI-state refactor (TD-009) and release provenance/Scorecard
   follow-ups are recorded maintenance work, not assertions of failed Codex
   installation acceptance.

## 6. Version History

| Version | Date     | Author    | Changes       |
| ------- | -------- | --------- | ------------- |
| 0.2     | 2026-10-09 | GitCmurf | Authorised external review; fixed optimized acceptance and subdirectory confirmation |
| 0.1     | 2026-10-06 | GitCmurf | Initial draft |
