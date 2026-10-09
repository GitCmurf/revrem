---
document_id: REVREM-ADR-013
type: ADR
title: Configuration Driven Harness and Model Catalog
status: Draft
version: '0.5'
last_updated: '2026-09-02'
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

The Codex cache is an optional external overlay. Codex may replace it while
RevRem starts, so unreadable, empty, or malformed cache contents are ignored
for that load and packaged metadata remains authoritative. This keeps CLI and
TUI behavior deterministic during concurrent Codex activity.

Known model/effort incompatibilities fail before provider execution. Unknown
models and efforts pass through with a warning, preserving forward compatibility.
The CLI exposes the effective metadata through `revrem models list`; the wizard
and TUI use the same catalog for discoverability and compatible effort cycling.

Each provider call emits a local `model_invocation` event containing phase,
harness, actual requested model, effort, duration, outcome, and token usage when
the harness reports it. Routed remediation records the selected route's harness,
model, and effort rather than the global remediation defaults. Summaries retain
those events and `revrem stats models` aggregates per-run artifacts referenced
by local run history; malformed or non-finite local durations are normalized to
zero so one corrupted artifact cannot prevent best-effort reporting. RevRem
creates no remote telemetry stream and does not infer prices.

The project dogfood profile moves to GPT-5.6 because it is controlled locally.
Shipped general-purpose and expert-profile defaults remain unchanged while the
family is in limited preview.

Profile inheritance normally deep-merges map-valued settings. An editor that
removes an inherited route or harness executable persists the resulting full map
and records the owning profile's replacement intent explicitly:

```toml
[profiles.my-profile]
replace_inherited_maps = ["runtime.harness_executables", "triage.routes"]
```

Only those two audited paths are accepted. This keeps TOML portable (which has no
null value), avoids changing shared defaults, and makes save/reload idempotent.

## Consequences

- Adding a model or effort is normally a catalog edit, not a parser/TUI edit.
- Harness grammar remains reviewed Python code and cannot be injected by config.
- Local stats remain reproducible from run artifacts without a second ledger.
- Unknown future provider values remain usable, while catalogued invalid pairs
  are rejected with an actionable message.
- Relative pending-review artifact searches are resolved against the configured
  repository, never the caller process's ambient working directory.
- Catalog-backed harness aliases, executables, and drivers used for route
  capability checks, phase commands, and reasoning-effort reporting are
  resolved against that same configured repository.
- Catalog aliases cannot use a built-in harness name. This prevents one name
  from resolving to a catalog driver in one execution path and a built-in
  executable in another.
- Triage reasoning-effort selectors apply Codex restrictions to resolved
  catalog drivers, so aliases cannot offer or retain provider-incompatible
  effort values.
- Profile editing and validation use the selected repository's catalog rather
  than the process's ambient working directory.
- Optional external Codex cache entries are accepted only when their model
  identifiers are nonempty strings; malformed entries are skipped so packaged
  and project catalog operations remain available.
- Replayed TUI routing applies its triage contract before its enabled state,
  and loop harness cycling resolves aliases lazily from the edited workspace.
- Wizard previews treat stale persisted parser choices as non-previewable
  history rather than allowing them to terminate the interactive session.
- Structured last-run replay preserves remediation approval and sandbox
  settings; replay cannot silently replace a restrictive prior run with profile
  defaults.
- TUI resume replay also restores every explicit wall-time, token, and USD
  ceiling into its editable budget configuration. Profile snapshots retain
  model-aware defaults, and Gemini aliases select review context caps from
  their resolved driver rather than their display alias.
- Explicit map replacement markers preserve inherited route and executable
  deletions without mutating defaults shared by other profiles.

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
