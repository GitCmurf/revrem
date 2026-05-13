---
document_id: REVREM-ADR-005
type: ADR
title: Redaction defaults for bug report bundles
status: Draft
version: '0.1'
last_updated: '2026-05-11'
owner: __TBD__
docops_version: '2.0'
area: security
description: Decision record for default redaction behavior, raw transcript opt-ins,
  and no-redact risk acknowledgement
keywords:
- security
- redaction
- bundles
- privacy
related_ids:
- REVREM-TASK-002
- REVREM-PLAN-003
- REVREM-ADR-004
---

# ADR: Redaction defaults for bug report bundles

## Context

RevRem operators need a safe way to share failed-run diagnostics. Run
directories may contain local paths, usernames, API keys accidentally printed
by checks, authorization headers, model transcripts, suppression rationale, and
other proprietary context.

The support workflow must therefore default to privacy-preserving output while
still allowing an operator to opt into richer evidence when they intentionally
accept the risk.

## Content

Status: Accepted.

`revrem bundle-bug-report` redacts by default. The built-in redaction pass in
`src/code_review_loop/redaction.py` covers:

- authorization headers;
- PEM private key blocks;
- AWS access key IDs;
- GitHub tokens;
- OpenAI and Anthropic API keys;
- generic long hexadecimal tokens;
- sensitive environment assignments whose names include key, token, secret,
  password, pass, or credential;
- the current home path;
- the current username as a standalone token.

Default bundles include schema-backed run metadata and sanitized check output.
Raw review/remediation/triage transcripts are excluded unless the operator
passes `--include-raw-transcripts`. When raw transcripts are included they are
still redacted by default.

Failure diagnostics carry stable `f1:` fingerprints derived from the shared F4
fingerprint module. Diagnostic fingerprints use the diagnostic code as the rule
id, `.` as the synthetic path, the human diagnostic message as the message stem,
and a severity bucket mapped from diagnostic severity. They intentionally avoid
embedding absolute worktree paths or usernames so the same failure class is
searchable across machines and temporary directories.

Disabling redaction requires both `--no-redact` and
`--i-understand-the-risks`. This two-flag gate is intentional: a single
negative flag is too easy to cargo-cult into scripts.

Bundle archives are deterministic for the same run directory on the same
machine. Tar member order, metadata, and gzip `mtime` are fixed so tests and
support workflows can compare artifacts byte-for-byte.

Consequences:

- Support bundles are safer to attach to public issues than raw run
  directories, but they are not a proof that every secret has been removed.
- Operators remain responsible for inspecting bundles before publishing them.
- Future integration with `detect-secrets` can add another scanning layer, but
  the built-in regex pass remains mandatory so the default workflow works
  without optional tooling.
- Suppression audit logs are not raw-bundled by default; future suppression
  summaries must be redacted before inclusion.
