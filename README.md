# code-review-loop

`code-review-loop` runs a bounded Codex review -> remediation -> re-review loop
against a git base branch. It is intended for local pre-merge use when an
operator wants Codex to review a branch, apply valid actionable findings, run
verification commands, and leave review/remediation artifacts behind.

## Quick Start

```bash
code-review-loop \
  --base main \
  --max-iterations 2 \
  --review-model gpt-5.5 \
  --remediation-model gpt-5.4-mini \
  --reasoning-effort medium \
  --timeout-seconds 1800 \
  --summary-format both \
  --check "pytest -q" \
  --check "git diff --check"
```

The command exits `0` only when the final loop status is clear. It exits `2`
when the bounded loop finishes with findings or unresolved check failures.

## Development

```bash
python -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
./scripts/dev-check
```

The development extra installs `ruff`, `mypy`, `pytest`, and build tooling.
Ruff is a required local and CI gate for this project.

Meminit DocOps gates:

```bash
meminit doctor --format json
meminit check --format json
```

See `REVREM-DEVEX-001` for operator usage and `REVREM-ADR-001` for
the packaging decision.
