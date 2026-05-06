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
Per-run artifacts are written under `.revrem/runs/<timestamp>/` by default.
RevRem adds `.revrem/runs/` to the repository-local `.git/info/exclude` on the
first default-artifact run, falling back to `.revrem/.gitignore` outside Git
repositories. The ignore file is scoped to the workspace path rather than
crossing into unrelated parent checkouts, so local transcripts stay out of
commits without editing tracked ignore files. Existing ignore files are checked
by exact line match so longer paths like `work/.revrem/runs/` do not suppress
the root `.revrem/runs/` entry.
History-backed artifact pointers are resolved against the recorded run `cwd`,
so the TUI can still show existing artifacts when you inspect a run from a
different checkout.
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
When importing profiles from another TOML file, RevRem folds that file's
defaults into each imported profile so the imported behavior does not depend on
the destination config's defaults. The import path must point to an existing
TOML file; missing paths fail fast instead of being treated as empty imports.
Profile loading rejects unknown keys in the profile table and nested sections,
so typos fail fast instead of silently falling back to built-in defaults.
`revrem config show`, `export`, and `doctor` accept reserved future harnesses
as configuration syntax. The executable path currently supports Codex for
review, optional read-only triage, and remediation, and rejects unimplemented
backends before the loop starts.

True-by-default booleans also have positive CLI overrides. Use `--full-auto`,
`--output-last-message`, or `--final-review` to restore the built-in `true`
behavior for a one-off run when a profile disables one of those settings; use
the `--no-*` or `--skip-final-review` forms to force them off.
Profile-controlled `--exec-json`, `--debug-status-detection`,
`--quiet-progress`, and `--terminal-title` settings also have matching
`--no-*` flags so one-off invocations can override shared profile defaults in
either direction.

```bash
revrem config new final-pr --description "Full PR readiness check"
revrem config edit final-pr
revrem config show final-pr
revrem config clone final-pr final-pr-copy
revrem --profile final-pr
```

In an interactive terminal, `revrem config new final-pr` opens a small prompt
flow for the common fields: description, harness, review model, remediation
model, reasoning effort, timeout, and first check command. Use
`--no-interactive` from scripts, or pass `--description` for a quick minimal
profile.

If a one-off command has the settings you want to keep for this repository,
save it as a project-local profile:

```bash
revrem --base main --max-iterations 11 --check "git diff --check" --save-profile final-pr
```

`--save-profile` writes `.revrem.toml` at the repository root and exits without
running the loop. It refuses to overwrite an existing project profile unless
`--save-profile-force` is supplied.

For richer watched-terminal output, install the optional progress extra and
request Rich rendering. The TUI extra includes Rich too:

```bash
./.venv/bin/pip install -e ".[progress]"
revrem --profile final-pr --progress-style rich
```

The optional TUI entry point is dependency-gated so the default CLI stays
dependency-light:

```bash
./.venv/bin/pip install -e ".[tui]"
./.venv/bin/revrem ui
./.venv/bin/revrem ui --profile final-pr
```

The TUI renders Home, Profiles, Pipeline, Run Monitor, and Controls views. Use
`--profile NAME` to choose the initial profile. Key bindings shell through the
same CLI command plans as normal terminal use: `d` dry-runs the selected
profile, `s` shows it, `e` edits it, `n` creates a profile, `c` clones, `x`
exports, `i` imports from the path field, and `delete` removes a profile with
the non-interactive `revrem config delete --yes` path.
When `code_review_loop.tui.main()` is used as a module entry point, it honors
the current process argv in the same way as `revrem ui`.

## Development

```bash
./scripts/install-dev
./scripts/dev-check
```

The development extra installs `ruff`, `mypy`, `pytest`, Rich, Textual, and build tooling.
Ruff is a required local and CI gate for this project.

## Stable Local Install

Use the repo-local `.venv` for development and testing in this checkout. Promote
a known-good version for use from other repositories with:

```bash
./scripts/promote-stable
```

The promotion script runs `./scripts/dev-check`, copies a source snapshot under
`~/.local/share/revrem/releases/`, creates a stable interpreter at
`~/.local/share/revrem/stable-venv`, recreating an older or missing stable
venv before updating:

```text
~/.local/bin/code-review-loop
~/.local/bin/revrem
```

That keeps active development changes isolated until they are deliberately
promoted.

Use checks that match the target repository. Python repositories can use
`--check "pytest -q"`; TypeScript-only repositories should usually use their
native checks, for example `--check "pnpm test"` and
`--check "pnpm run typecheck"`. If a shared profile still includes pytest,
RevRem skips it for repositories that look like Node/TypeScript projects and
have no recognized Python project/test surface, so a stray helper `.py` file
does not keep pytest active and pytest exit codes `2`, `4`, or `5` do not block
an otherwise clear review in a non-Python repo.

For the next release, use this sequence from this repository:

```bash
# 1. Bump the package version in pyproject.toml and src/code_review_loop/__init__.py.
./scripts/dev-check
git diff --check
git add pyproject.toml src/code_review_loop/__init__.py
git commit -m "chore: bump version to <version>"
git tag v<version>
./scripts/promote-stable
revrem --version
```

The promotion script performs its own `./scripts/dev-check` before updating
`~/.local/bin`. In sandboxed agent sessions, creating tags may require an
approved `git tag` escalation because tag refs and annotated tag objects are
written inside `.git`.

Meminit DocOps gates:

```bash
meminit doctor --format json
meminit check --format json
```

See `REVREM-DEVEX-001` for operator usage and `REVREM-ADR-001` for
the packaging decision.
