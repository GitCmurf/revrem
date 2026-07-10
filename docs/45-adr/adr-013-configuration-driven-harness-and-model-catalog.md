---
document_id: REVREM-ADR-013
type: ADR
title: Configuration Driven Harness and Model Catalog
status: Draft
version: '0.1'
last_updated: '2026-07-10'
owner: maintainers
docops_version: '2.0'
area: architecture
description: Move harness and model capability selection into layered configuration
  with local invocation telemetry
---

# ADR: Configuration Driven Harness and Model Catalog

## Context

Provider model families and reasoning-effort variants change faster than RevRem's
release cadence. The former implementation encoded effort choices in argparse,
profile parsing, the wizard, and the TUI. That duplication blocked valid provider
features such as GPT-5.5 `xhigh` and made adding GPT-5.6 a code change.

RevRem also knew the requested model only as command text. Operators could not
compare actual phase runtimes or token coverage across local runs.

## Content

Adopt a layered TOML catalog for harness and model metadata. Catalog entries may
select a built-in audited harness driver, but cannot define arbitrary command
templates. The precedence order is:

1. packaged RevRem catalog;
2. Codex's local `$CODEX_HOME/models_cache.json`;
3. `~/.config/revrem/catalog.toml`;
4. project `.revrem-catalog.toml`.

Known model/effort incompatibilities fail before provider execution. Unknown
models and efforts pass through with a warning, preserving forward compatibility.
The CLI exposes the effective metadata through `revrem models list`; the wizard
and TUI use the same catalog for discoverability and compatible effort cycling.

Each provider call emits a local `model_invocation` event containing phase,
harness, actual requested model, effort, duration, outcome, and token usage when
the harness reports it. Summaries retain those events and `revrem stats models`
aggregates per-run artifacts referenced by local run history. RevRem creates no
remote telemetry stream and does not infer prices.

The project dogfood profile moves to GPT-5.6 because it is controlled locally.
Shipped general-purpose and expert-profile defaults remain unchanged while the
family is in limited preview.

## Consequences

- Adding a model or effort is normally a catalog edit, not a parser/TUI edit.
- Harness grammar remains reviewed Python code and cannot be injected by config.
- Local stats remain reproducible from run artifacts without a second ledger.
- Unknown future provider values remain usable, while catalogued invalid pairs
  are rejected with an actionable message.

## Alternatives Considered

- Fully configurable argv templates were rejected because they turn config into
  executable command grammar and weaken the harness security boundary.
- A global telemetry database was rejected because it duplicates run artifacts
  and creates additional retention, migration, and privacy obligations.

## Verification

- Catalog precedence and GPT-5.6 effort matrices have unit coverage.
- CLI selection, wizard/TUI effort behavior, event schemas, and stats aggregation
  have regression coverage.
- `meminit check` and the standard repository quality gates remain required.
