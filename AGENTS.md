<!-- MEMINIT_PROTOCOL: begin id=agents-md version=1.0 sha256=7ddf8639341a6568fecb5a052be63cf36ad78038800108142fade6f026224446 -->
# Agentic Coding Rules

This repository (**code-review-loop**) uses **Meminit DocOps** for governance.

## Using Meminit

Run `meminit` commands to create and manage governed documents:

- `meminit init` — initialize DocOps (run once)
- `meminit new <TYPE> <TITLE>` — create a new governed document
- `meminit check` — verify compliance
- `meminit doctor` — diagnose repo readiness

Document IDs follow `REVREM-TYPE-SEQ` (e.g., `REVREM-ADR-001`).

## Project Rules

- The atomic unit of work is code + documentation + tests.
- Keep the runtime dependency-free unless a dependency removes clear operational risk. `tomli-w` is an accepted exception: it eliminates an entire class of TOML encoding bugs (surrogate escapes, escaping edge cases) that would be fragile to maintain by hand.
- Preserve operator-visible progress and artifact output; this tool is for watched local automation.
- Keep nested Codex execution bounded by default. Any unbounded mode must be explicit.
- Prefer portable POSIX/Linux behavior and avoid shell-specific assumptions in Python code.
- Never commit secrets, local Codex transcripts, or generated loop artifacts.

## Rules

- Never modify a `document_id` once set.
- Always use `meminit new` to create governed documents.
- All code changes must include documentation and tests.
- Never commit secrets or PII.
<!-- MEMINIT_PROTOCOL: end id=agents-md -->
