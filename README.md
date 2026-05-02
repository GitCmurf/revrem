# code-review-loop

`code-review-loop` runs a bounded Codex review -> remediation -> re-review loop
against a git base branch. It is intended for local pre-merge use when an
operator wants Codex to review a branch, apply valid actionable findings, run
verification commands, and leave review/remediation artifacts behind.

## Quick Start

```bash
revrem \
  --base main \
  --max-iterations 2 \
  --review-model gpt-5.5 \
  --remediation-model gpt-5.4-mini \
  --reasoning-effort medium \
  --timeout-seconds 1800 \
  --summary-format text \
  --debug-status-detection \
  --terminal-title \
  --check "pytest -q" \
  --check "git diff --check"
```

`revrem` and `code-review-loop` are equivalent entry points. Use `revrem` for
human-facing usage and keep `code-review-loop` for existing scripts.
Use `--summary-format json` or `--summary-format both` only when a caller needs
machine-readable stdout.

The command exits `0` only when the final loop status is clear. It exits `2`
when the bounded loop finishes with findings or unresolved check failures.
Non-dry-run invocations append compact metadata to
`~/.local/share/revrem/runs.jsonl`, including failed terminal runs once their
summary is written; use `revrem history list` to inspect recent runs. Pass
`--no-run-history` for one-off runs that should leave only the workspace-local
artifact directory.
Progress timestamps use local terminal time. Persisted history timestamps remain
UTC ISO-8601 values for stable machine processing.

Use `--commit-after-remediation` when each verified remediation pass should be
captured as a git commit, and `--no-commit-after-remediation` when a profile
enables commits by default but a one-off run should stay dry. RevRem stages the
workspace with `git add -A` only after checks pass, excludes the configured
artifact directory from staging, skips the commit when there are no staged
changes, and runs `git commit` itself. Auto-commit requires a clean worktree
before the loop starts so unrelated local edits cannot be captured
accidentally. `--commit-message-model` controls the optional read-only Codex
call that drafts the commit subject; profile
configuration defaults that message model to `gpt-5.3-codex-spark`. By
default commit subjects are normalized to Conventional Commit syntax and end
with ` (RevRem)`. Use `--commit-message-prompt` only when a run intentionally
needs a different commit-subject policy.

Named profiles can hold the same settings in `~/.config/revrem/profiles.toml`.
That file can also carry a shared `[defaults]` table for user-wide model and
operator preferences. Bare `revrem` invocations load those defaults too, and
`revrem config` preserves existing profiles verbatim when it rewrites the
file, so omitted fields keep inheriting shared defaults. If a profile
intentionally resets a field back to the built-in default, the rewrite keeps
that field when the file's `[defaults]` table would otherwise change behavior.
Profile loading rejects unknown keys in the profile table and nested sections,
so typos fail fast instead of silently falling back to built-in defaults.
`revrem config show`, `export`, and `doctor` accept reserved future harnesses
as configuration syntax. The executable path currently supports Codex for
review, optional read-only triage, and remediation, and rejects unimplemented
backends before the loop starts.

```bash
revrem config new final-pr --description "Full PR readiness check"
revrem config edit final-pr
revrem config show final-pr
revrem --profile final-pr
```

For richer watched-terminal output, install the optional progress extra and
request Rich rendering:

```bash
./.venv/bin/pip install -e ".[progress]"
revrem --profile final-pr --progress-style rich
```

## Development

```bash
./scripts/install-dev
./scripts/dev-check
```

The development extra installs `ruff`, `mypy`, `pytest`, and build tooling.
Ruff is a required local and CI gate for this project.

## Stable Local Install

Use the repo-local `.venv` for development and testing in this checkout. Promote
a known-good version for use from other repositories with:

```bash
./scripts/promote-stable
```

The promotion script runs `./scripts/dev-check`, copies a source snapshot under
`~/.local/share/revrem/releases/`, creates a stable interpreter at
`~/.local/share/revrem/stable-venv`, and updates:

```text
~/.local/bin/code-review-loop
~/.local/bin/revrem
```

That keeps active development changes isolated until they are deliberately
promoted.

Meminit DocOps gates:

```bash
meminit doctor --format json
meminit check --format json
```

See `REVREM-DEVEX-001` for operator usage and `REVREM-ADR-001` for
the packaging decision.
