---
document_id: REVREM-GUIDE-001
type: GUIDE
title: Failure Diagnostics Guide
status: Draft
version: '0.1'
last_updated: '2026-06-23'
owner: GitCmurf
docops_version: '2.0'
area: devex
description: Operator guide for RevRem diagnostic and exit-code remediation.
keywords:
- diagnostics
- troubleshooting
related_ids:
- REVREM-PLAN-005
---

# GUIDE: Failure Diagnostics Guide

## Context

RevRem is watched local automation. A failure should leave enough evidence for
an operator to decide whether to fix local setup, raise a budget, resume a run,
or file a bug without reading source code or raw model transcripts.

The primary evidence sources are:

- `summary.json` for final status, stopped reason, exit-code mapping, budgets,
  phase failures, and artifact paths.
- `events.jsonl` for ordered phase/timeline evidence.
- `diagnostics.json` and `diagnostics-*.json` for setup, triage, and phase
  failure details.
- `review-*-status.json` for review-status classification evidence.
- `revrem report <run-dir>` for the redacted HTML and JSON summary surfaces.

## Content

## Exit Codes

| Code | Meaning | Operator action |
|---|---|---|
| `0` | Clear. | No action required; archive or publish the report if useful. |
| `1` | Utility or typed run error. | Open the report first. If `summary.phase_failures` is present, inspect the failure reason, bounded stderr/stdout excerpt, retry command, and diagnostic artifact. |
| `2` | Findings remain or verification checks failed. | Read top findings and check failures in the report. Remediate manually, resume if appropriate, or rerun with a narrower profile/check set. |
| `3` | Budget ceiling reached before the next model call. | Inspect `summary.budgets`; increase `--max-wall-seconds`, `--max-tokens`, `--max-usd`, or resume with a larger budget if the partial run is still useful. |
| `4` | Setup or resume precondition failed before useful execution. | Inspect `diagnostics.json`; fix local Git/base/check/tool/profile issues before rerunning. |
| `5` | Operator cancellation. | Resume only if the run boundary is resumable and remaining budget exists. Otherwise rerun. |
| `6` | `revrem doctor --strict` promoted warnings to failure. | Resolve warning-level doctor diagnostics or rerun doctor without `--strict` when warnings are acceptable. |

## Diagnostic Families

| Family | Where to look | Typical fix |
|---|---|---|
| Preflight setup | `diagnostics.json`, terminal summary, `summary.stopped_reason=setup_failed` | Install missing tools, fix `--base`, run inside a Git repo, adjust artifact dir, or remove invalid check commands. |
| Resume precondition | `revrem resume --format json`, `diagnostics.json` | Resume only from max-iteration, budget, or cancellation boundaries; preserve matching repo/head/base; provide fresh budget headroom. |
| Triage parse or routing | `summary.triage_diagnostics`, `diagnostics-<iteration>.json` | Treat warning diagnostics as degraded routing evidence; fix malformed profile/routing config for blocking diagnostics. |
| Provider subprocess failure | `summary.phase_failures`, `diagnostics-*-failure.json`, HTML Phase failures section | Fix credentials, quota, provider CLI install, model name, sandbox, or retry after transient provider service failures. |
| Provider quota/billing | `failure.reason=provider_quota_exhausted` | Fix provider account billing/quota/credentials before rerunning; increasing RevRem budgets will not help. |
| Budget ceiling | `summary.budgets`, `cost_charge` / `cost_ceiling_hit` events | Raise the relevant ceiling only after confirming scope still justifies more model spend. |
| Check failure | `summary.iterations[].checks`, check artifacts, HTML Checks section | Run the failing command locally, fix the product issue or update the profile if the check is no longer valid. |
| Review status ambiguity | `review-*-status.json`, `summary.phase_observations` | Inspect the classifier evidence; if the model output is ambiguous, tighten the prompt/profile or rerun with a stronger review model. |

## Triage Order

1. Read the terminal summary and note the exit code.
2. Open `summary.json` and confirm `final_status`, `stopped_reason`, and
   `artifact_paths`.
3. If `phase_failures` exists, inspect that before raw transcripts.
4. If setup failed, read `diagnostics.json`; do not rerun models until setup is
   fixed.
5. If findings remain, use `revrem report <run-dir>` and inspect top findings,
   suppressed findings, and check results.
6. If budget stopped the run, check whether the partial result is useful before
   increasing ceilings.
7. When filing a RevRem bug, attach a redacted bug bundle or the redacted HTML
   report plus `summary.json`; never paste raw prompts or secrets.

## CI Notes

The reference GitHub Action runs `revrem --no-tty --progress-style compact
--summary-format json` and maps the exit code only after report rendering,
artifact upload, and PR commenting. For failures in CI:

- Prefer the uploaded HTML report over raw workflow logs.
- Exit code `2` may pass or fail depending on `fail-on-findings`.
- Exit code `3` always fails the job because review evidence is partial.
- Fork PRs skip comments but still produce artifacts when upload is enabled.
- Raw run-directory upload is opt-in because it is not redacted.
