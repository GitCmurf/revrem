---
name: meminit-docops
description: Retrofit Meminit into an existing repo, enforce DocOps compliance, create governed documents, or troubleshoot Meminit violations. Use for brownfield migration, scan/check/fix workflows, `meminit new`, CI/pre-commit setup, and index/resolve/identify/link tasks, with safety-first defaults and JSON-first agent guidance.
---

# Meminit DocOps Skill

## Purpose

This skill teaches Codex _how_ to use `meminit` to:

- retrofit Meminit into an existing repository (brownfield migration), and
- keep documentation compliant over time (local + CI gates).

It does **not** decide _when_ your repo should adopt DocOps; that policy belongs in `AGENTS.md` and CI settings.

## When to Use

Activate this skill when the user asks to:

- **Retrofit Meminit** into an existing repo (brownfield migration).
- **Enforce DocOps compliance** — check, fix, or audit governed documents.
- **Create governed documents** — e.g. ADRs, PRDs, specs, runbooks via `meminit new`.
- **Troubleshoot documentation violations** — diagnose and resolve `meminit check` failures.
- **Set up CI gates or pre-commit hooks** for DocOps enforcement.
- **Resolve or look up document IDs** using the Meminit index.

## Safety rules (non-negotiable)

1. Prefer read-only commands first: `scan`, `doctor`, `check`.
2. Never run a write operation (`fix --no-dry-run`, `fix --plan <PLAN_PATH> --no-dry-run`, `migrate-ids --no-dry-run`, `migrate-ids --rewrite-references`, `protocol sync --no-dry-run`, or any rename/rewrite) without:
   - showing a dry-run preview, and
   - explicit user confirmation.
3. Never attempt to “fix” semantic governance manually (ownership, approvals, status promotion) without asking.
4. Do not introduce fake Markdown links like `[text](path)` unless the target exists.
5. Prefer `--format json` for automation, treat STDOUT as machine output, and keep verbose reasoning on STDERR only.
6. For brownfield repos, prefer plan-driven changes (`scan --plan` then `fix --plan`) over ad hoc write operations.

## Quick command map

- Initialization: `meminit init`
- Repo readiness: `meminit doctor --format json`
- Repo discovery: `meminit context --format json` (add `--deep` for per-namespace document counts)
- Compliance: `meminit check --format json` (add `--strict` to promote warnings to errors)
- Generate migration plan: `meminit scan --plan <PLAN_PATH> --format json`
- Safe preview: `meminit fix --dry-run --format json`
- Safe preview from plan: `meminit fix --plan <PLAN_PATH> --format json` (add `--namespace <NS>` for monorepo safety)
- Apply mechanical fixes: `meminit fix --no-dry-run --format json`
- Apply plan: `meminit fix --plan <PLAN_PATH> --no-dry-run --format json` (add `--namespace <NS>` for monorepo safety)
- Migration planning: `meminit scan --format json`
- Create governed doc: `meminit new <TYPE> <TITLE> --format json` (key flags: `--owner`, `--area`, `--description`, `--status`, `--keywords`, `--related-ids`, `--id`, `--dry-run`, `--namespace`)
- Type discovery: `meminit new --list-types --format json`
- ADR shortcut: `meminit adr new <TITLE> --format json`
- Migrate legacy IDs: `meminit migrate-ids --dry-run --format json` (add `--rewrite-references` to update cross-refs)
- Pre-commit hook: `meminit install-precommit --root .`
- Org profile helpers (optional): `meminit org status --format json`, `meminit org vendor --format json`
- Index + resolution:
  - `meminit index --format json`
  - `meminit resolve <DOCUMENT_ID> --format json`
  - `meminit identify <PATH> --format json`
  - `meminit link <DOCUMENT_ID> --format json`
- Protocol governance:
  - `meminit protocol check --format json` (drift detection for governed assets)
  - `meminit protocol sync --format json` (preview-only by default; add `--no-dry-run` to apply)

> [!TIP]
> Use `--output <path>` to capture JSON artifacts for CI or downstream tools. All commands support `--include-timestamp` if timing data is needed in the envelope.
> For monorepo safety, use `--namespace <NS>` on `fix` and `new` to scope operations to a single namespace.

## How to Use

Default flow:

1. Run `meminit context --format json` to discover repo shape and avoid hardcoded assumptions.
2. Prefer read-only analysis first (`scan`, `doctor`, `check`).
3. For brownfield migration, generate a deterministic plan artifact with `scan --plan`.
4. Preview changes with `fix` dry-run before any write.
5. Apply changes only after user approval, then re-run `check`.
6. Build or refresh the index once the repo is green (or close to green).

If you want a quick brownfield bootstrap, use the bundled helper script:

```bash
bash .agents/skills/meminit-docops/scripts/meminit_brownfield_plan.sh . /tmp/meminit-migration-plan.json
```

## Decision tree (brownfield migration)

### Step 0 — Safety checkpoint

Before any write operations:

1. Create a dedicated branch for the migration.
2. Make a safety commit (or tag) so you can revert cleanly.

### Step 1 — Confirm boundaries

Run:

```bash
meminit context --format json
```

Determine if the repo is initialized and what namespaces exist. If not initialized, recommend `meminit init`.

### Step 2 — Scan (read-only)

Run:

```bash
meminit scan --root . --plan /tmp/meminit-migration-plan.json --format json
```

Interpret the outputs:

- `stdout.data.report.suggested_type_directories` → propose `docops.config.yaml` overrides.
- `stdout.data.report.ambiguous_types` → ask the user to pick the intended mapping (do not guess).
- `plan.data.plan.actions` → deterministic mechanical changes that `fix --plan` can preview or apply.

### Step 3 — Align `docops.config.yaml` to reality

Edit config only after user agrees. Typical edits:

- `docs_root`
- `docops_version`
- `schema_path`
- `type_directories`
- `excluded_paths` / `excluded_filename_prefixes`

### Step 4 — Ensure baseline scaffolding exists

If required files are missing, either:

- create or edit `docops.config.yaml` manually, or
- run `meminit init --root . --format json` to scaffold the baseline DocOps structure.

Use `meminit init` carefully in brownfield repos because it may create directories or templates you do not want yet.

### Step 5 — Doctor (repo-level readiness)

Run:

```bash
meminit doctor --root . --format json
```

If doctor reports schema missing/invalid, fix that before continuing.

### Step 6 — Check (authoritative violations)

Run:

```bash
meminit check --root . --format json
```

Do not apply fixes yet; first categorize:

- Mechanical: filenames, missing frontmatter, date normalization.
- Manual: duplicate IDs, missing ownership, status promotion/approval.

### Step 7 — Fix (dry-run, then apply)

Run:

```bash
meminit fix --root . --plan /tmp/meminit-migration-plan.json --namespace <NS> --format json
```

Show the user the proposed actions. If approved:

```bash
meminit fix --root . --plan /tmp/meminit-migration-plan.json --namespace <NS> --no-dry-run --format json
```

If no plan was generated or the task is small, the fallback path is:

```bash
meminit fix --root . --dry-run --namespace <NS> --format json
meminit fix --root . --no-dry-run --namespace <NS> --format json
```

Omit `--namespace <NS>` in single-repo mode. Prefer it in monorepos to keep the blast radius small.

### Step 8 — Migrate legacy IDs (if applicable)

If the repo has legacy document IDs that need migrating:

```bash
meminit migrate-ids --root . --dry-run --format json
```

Show the user the proposed ID migrations. If approved:

```bash
meminit migrate-ids --root . --no-dry-run --format json
```

Add `--rewrite-references` to also update cross-references in other documents.

### Step 9 — Re-check until green

Run:

```bash
meminit check --root . --format json
```

If still failing, enumerate remaining violations and identify which are manual.

### Step 10 — Index (optional but recommended)

Once green (or close), build the index:

```bash
meminit index --root . --format json
```

Use `resolve/identify/link` for stable references in docs and tooling.

## Decision tree (ongoing enforcement)

- Local:
  - `meminit install-precommit --root .`
  - Encourage “fix locally” before PR.
- CI:
  - Run `meminit doctor --format json` and `meminit check --format json` on PRs only.
  - Use least privilege (workflow `permissions: read-all`).
  - Avoid secrets in DocOps workflows.

## Creating governed documents

To create a new governed document:

```bash
meminit new <TYPE> <TITLE> --format json --owner <OWNER> --area <AREA>
```

Then validate the created file:

```bash
meminit check <PATH_TO_NEW_FILE> --format json
```

Use `meminit new --list-types --format json` to discover available document types. Add `--dry-run` to preview without writing.

Agent-safe example:

```bash
meminit new ADR "Caching Strategy" \
  --root . \
  --format json \
  --owner platform-team \
  --area backend \
  --description "Adopt Redis-backed cache invalidation" \
  --status Draft \
  --keywords cache \
  --keywords redis \
  --related-ids MEMINIT-PRD-002 \
  --dry-run
```

Important compatibility rules:

- `--interactive` is human-only and must not be combined with `--format json`.
- `--edit` must not be combined with `--dry-run` or `--format json`.

## Agent Interface (JSON output contract)

All `meminit` commands support `--format json`. When used, the CLI emits a single JSON object on STDOUT with this envelope structure:

| Field                   | Description                                                         |
| ----------------------- | ------------------------------------------------------------------- |
| `output_schema_version` | `"3.0"`                                                             |
| `success`               | `true` on success; `false` on operational errors or gating failures |
| `command`               | Canonical subcommand name                                           |
| `run_id`                | UUIDv4 correlation token                                            |
| `timestamp`             | ISO 8601 UTC timestamp when `--include-timestamp` is used           |
| `root`                  | Absolute path to repo root (repo-aware commands only)               |
| `data`                  | Command-specific payload (`{}` when empty)                          |
| `warnings`              | Structured warning array                                            |
| `violations`            | Structured violation array                                          |
| `advice`                | Structured advice array                                             |
| `error`                 | Structured operational error object when the command cannot run     |

Optional top-level fields:

- `timestamp` when `--include-timestamp` is passed
- `error` for operational failures
- command-specific counters for `check` (for example `files_checked`, `violations_count`)

For `check`, agents should expect additional top-level counters such as:

- `files_checked`, `files_passed`, `files_failed`
- `checked_paths_count`, `missing_paths_count`, `schema_failures_count`
- `warnings_count`, `violations_count`
- `files_with_warnings`, `files_outside_docs_root_count`

### Error handling

Two distinct failure modes:

1. **Operational error** — `success: false` with an `error` object (e.g. missing config, invalid schema). The command could not run.
2. **Gating failure** — `success: false` with a populated `violations` array and no `error` object. The command ran but found blocking issues. This is common for `check`, and may also appear in other enforcement-oriented commands such as `doctor` or `fix`.

Always check `success` first, then inspect `error` vs. `violations` to determine the failure type.

Use the live CLI behavior and tests as the source of truth when docs lag. `MEMINIT-SPEC-008` is the normative v3 output contract (superseding MEMINIT-SPEC-004).

## Project State Queue

Phase 4 adds a repo-local work queue layered on `project-state.yaml`.
Agents should use it for deterministic task selection instead of inventing
their own planner.

### Queue commands

```bash
meminit state next --root . --format json
meminit state blockers --root . --format json
meminit state list --root . --format json
```

### Recommended agent loop

1. Run `meminit state next --root . --format json`.
2. If `data.reason == "queue_empty"`, stop.
3. If `data.entry` exists, do exactly that work item.
4. Persist the mutation with `meminit state set`.
5. Repeat until the queue is empty.

### Safety rules

- Queue commands require an initialized repo config.
- Missing `project-state.yaml` is an empty queue, not an error.
- Malformed `project-state.yaml` is fatal and must be corrected before use.

## References (in this repo)

- Brownfield migration runbook: `docs/60-runbooks/runbook-005-brownfield-repo-migration.md`
- CI/CD enforcement runbook: `docs/60-runbooks/runbook-004-ci-cd-enforcement.md`
- Agent output contract: `docs/20-specs/spec-008-agent-output-contract-v2.md`
- Agent interface v2 PRD: `docs/10-prd/prd-005-agent-interface-v2.md`
