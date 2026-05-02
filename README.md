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

Named profiles can hold the same settings in `~/.config/revrem/profiles.toml`
and can be managed with `revrem config`:

```bash
revrem config new final-pr --description "Full PR readiness check"
revrem config show final-pr
revrem --profile final-pr
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
