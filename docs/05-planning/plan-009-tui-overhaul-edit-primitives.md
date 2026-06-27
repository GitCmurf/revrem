---
document_id: REVREM-PLAN-009
type: PLAN
title: TUI Overhaul Plan 1 — Non-Interactive Profile Edit Primitives
status: Draft
version: '0.1'
last_updated: '2026-06-27'
owner: GitCmurf
docops_version: '2.0'
area: planning
description: 'Foundation for the loop-first TUI overhaul (REVREM-DESIGN-001): add the
  non-interactive profile write/edit primitives the TUI working-copy + explicit-save
  model needs, exposed both as a library API and a scriptable `revrem config set`
  CLI surface. No TUI code yet.'
keywords:
- tui
- profiles
- config-set
- working-copy
- edit-primitives
- design-001
related_ids:
- REVREM-DESIGN-001
- REVREM-PRD-001
- REVREM-PLAN-007
---

# TUI Overhaul Plan 1 — Non-Interactive Profile Edit Primitives

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RevRem a non-interactive way to set individual profile fields and persist a whole profile to its owner config file, so the upcoming TUI can implement working-copy + explicit-save editing — and so the same edits are scriptable from the CLI.

**Architecture:** All edits operate on the *minimal authored* `raw_profiles[name]` dict (not the fully-resolved `Profile`), so written TOML stays minimal. A field set = load owner file → deep-set a dotted key into the raw dict → validate by re-parsing → write back through the existing `profiles` write machinery. A thin `revrem config set` subcommand wraps the library API. Builtins stay read-only.

**Tech Stack:** Python 3.12, `argparse` CLI (`code_review_loop/cli`), `tomllib` read + `_compat_tomli_w` write, `pytest`.

## Plan sequence (this is Plan 1 of 4)

1. **Plan 1 (this doc):** edit primitives — library + `config set`. *No TUI code.*
2. Plan 2: loop screen — working-copy state model + `LoopDiagram`/`PhaseCard`/`TriageRoutesTable` widgets + Save→profile.
3. Plan 3: run/monitor live mode (loop diagram in run mode + event log).
4. Plan 4: profiles picker + prompts library / in-loop picking.

Each later plan is written after its predecessor lands, since widget detail depends on the proven foundation.

## Global Constraints

Copied verbatim from REVREM-DESIGN-001 — every task implicitly includes these:

- Edits go through the **shared `profiles` write machinery** (validation, atomic writes, error handling stay in one place).
- **Builtins are read-only** — reject with `profiles.builtin_profile_readonly_message(name)`; the caller must clone first.
- **CLI-equivalence preserved**: `tests/test_tui_cli_equivalence.py` / `assert_equivalent_run_artifacts` must continue to pass; runs still launch as `revrem --profile NAME`.
- **Minimal TOML**: edits mutate `raw_profiles[name]` (the minimal authored form), never the fully-resolved profile.
- **New profiles** are created in the **user** config (`profiles.user_config_path`). Existing profiles are written back to **their owner file** (project `.revrem.toml` or user `profiles.toml`).
- No loop reordering / topology editing.

## Reference facts (verified against the codebase)

- Project config: `<repo_root>/.revrem.toml` (`profiles.PROJECT_CONFIG_NAME`). User config: `<home>/.config/revrem/profiles.toml` (`profiles.USER_CONFIG_RELATIVE`).
- `profiles.load_profile_file(path: Path) -> ProfileFile` — `ProfileFile.raw_profiles: dict[str, dict]` is the minimal authored TOML per profile.
- `profiles.parse_profile(name: str, raw: dict, *, source: str|None) -> Profile` — validates and builds a resolved profile; raises `ValueError` on bad input.
- `profiles.write_profile_to_path(path, profile, *, force=False, raw_profile=None) -> Path` — writes one profile; pass `raw_profile=` the minimal dict to keep TOML minimal.
- `profiles.is_builtin_profile(name) -> bool`, `profiles.builtin_profile_readonly_message(name) -> str`.
- Owner-path logic already exists privately as `_profile_config_owner_path(name, cwd, home)` in `cli/commands/config.py:148` (project file if name there, else user file, else `FileNotFoundError`; builtins raise readonly). Task 2 lifts a public version into `profiles`.
- `config` subcommands are registered in `cli/args.py:build_config_parser()`; handlers dispatch in `cli/commands/config.py:main()`.

---

### Task 1: `deep_set_raw` — set a dotted key in a raw profile dict, with type coercion

**Files:**
- Modify: `src/code_review_loop/profiles.py` (add `deep_set_raw` + `_coerce_field_value`)
- Test: `tests/test_profile_edit_primitives.py` (new)

**Interfaces:**
- Produces: `deep_set_raw(raw: dict[str, Any], dotted_key: str, value: str) -> dict[str, Any]` — returns a **new** dict (deep-copied) with `dotted_key` (e.g. `"review.model"`, `"pipeline.max_iterations"`) set, coercing the string `value` to the field's type.
- Produces: `_coerce_field_value(dotted_key: str, value: str) -> Any` — `int` for keys ending `.max_iterations`, `.inner_check_retries`, `.timeout_seconds`; `bool` for keys ending `.enabled`, `.final_review`, `.strict_on_unavailable_route`, `.allow_model_escalation`; otherwise `str`. (NB: `triage.routing.default_route` is a **string**, so bool keys are enumerated explicitly — a `triage.routing.` prefix match would wrongly coerce `default_route`.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_edit_primitives.py
from __future__ import annotations

import pytest

from code_review_loop import profiles


def test_deep_set_raw_sets_nested_scalar_and_copies():
    raw = {"review": {"model": "old"}}
    out = profiles.deep_set_raw(raw, "review.model", "gpt-5.5")
    assert out["review"]["model"] == "gpt-5.5"
    assert raw["review"]["model"] == "old"  # input not mutated


def test_deep_set_raw_creates_missing_intermediate_tables():
    out = profiles.deep_set_raw({}, "commit.message_model", "haiku-4.5")
    assert out == {"commit": {"message_model": "haiku-4.5"}}


def test_deep_set_raw_coerces_int_and_bool():
    out = profiles.deep_set_raw({}, "pipeline.max_iterations", "11")
    assert out["pipeline"]["max_iterations"] == 11
    assert isinstance(out["pipeline"]["max_iterations"], int)

    out2 = profiles.deep_set_raw({}, "triage.enabled", "false")
    assert out2["triage"]["enabled"] is False

    out3 = profiles.deep_set_raw({}, "runtime.inner_check_retries", "2")
    assert out3["runtime"]["inner_check_retries"] == 2


def test_deep_set_raw_routing_default_route_stays_string():
    # default_route is a string; only strict_*/allow_* under routing are bools.
    out = profiles.deep_set_raw({}, "triage.routing.default_route", "remediation")
    assert out["triage"]["routing"]["default_route"] == "remediation"

    out2 = profiles.deep_set_raw({}, "triage.routing.allow_model_escalation", "off")
    assert out2["triage"]["routing"]["allow_model_escalation"] is False


def test_deep_set_raw_rejects_bad_int():
    with pytest.raises(ValueError):
        profiles.deep_set_raw({}, "pipeline.max_iterations", "lots")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_profile_edit_primitives.py -v`
Expected: FAIL with `AttributeError: module 'code_review_loop.profiles' has no attribute 'deep_set_raw'`.

- [ ] **Step 3: Implement `deep_set_raw` + `_coerce_field_value`**

```python
# src/code_review_loop/profiles.py  (add near the other write helpers)
import copy as _copy

_INT_SUFFIXES = (".max_iterations", ".inner_check_retries", ".timeout_seconds")
# Enumerate bool keys explicitly: triage.routing.default_route is a STRING, so a
# "triage.routing." prefix match would wrongly coerce it to bool.
_BOOL_SUFFIXES = (
    ".enabled",
    ".final_review",
    ".strict_on_unavailable_route",
    ".allow_model_escalation",
)


def _coerce_field_value(dotted_key: str, value: str) -> Any:
    if dotted_key.endswith(_INT_SUFFIXES):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{dotted_key} must be an integer, got {value!r}") from exc
    if dotted_key.endswith(_BOOL_SUFFIXES):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{dotted_key} must be a boolean, got {value!r}")
    return value


def deep_set_raw(raw: dict[str, Any], dotted_key: str, value: str) -> dict[str, Any]:
    if not dotted_key:
        raise ValueError("dotted_key must be non-empty")
    coerced = _coerce_field_value(dotted_key, value)
    result = _copy.deepcopy(raw)
    cursor = result
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = coerced
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_profile_edit_primitives.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/profiles.py tests/test_profile_edit_primitives.py
git commit -m "feat(profiles): add deep_set_raw for dotted-key profile edits

REVREM-PLAN-009 T1.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm"
```

---

### Task 2: `profile_owner_path` — resolve the file a profile is written back to

**Files:**
- Modify: `src/code_review_loop/profiles.py` (add `profile_owner_path`)
- Modify: `src/code_review_loop/cli/commands/config.py` (re-point `_profile_config_owner_path` at the new public helper to avoid duplication)
- Test: `tests/test_profile_edit_primitives.py`

**Interfaces:**
- Consumes: `profiles.is_builtin_profile`, `profiles.builtin_profile_readonly_message`, `profiles.project_config_path`, `profiles.user_config_path`, `profiles.load_profile_file`.
- Produces: `profile_owner_path(name: str, *, cwd: Path, home: Path | None = None, allow_new: bool = False) -> Path`. Returns the project file if `name` is defined there, else the user file if defined there. Builtins raise `RuntimeError(builtin_profile_readonly_message(name))`. Unknown name: returns `user_config_path(home)` when `allow_new=True`, else raises `FileNotFoundError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_profile_edit_primitives.py  (append)
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_profile_owner_path_prefers_project(tmp_path):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "x"\n')
    got = profiles.profile_owner_path("demo", cwd=tmp_path, home=tmp_path)
    assert got == profiles.project_config_path(tmp_path)


def test_profile_owner_path_falls_back_to_user(tmp_path):
    user = tmp_path / ".config" / "revrem" / "profiles.toml"
    _write(user, '[profiles.demo]\nreview.model = "x"\n')
    got = profiles.profile_owner_path("demo", cwd=tmp_path, home=tmp_path)
    assert got == profiles.user_config_path(tmp_path)


def test_profile_owner_path_unknown_requires_allow_new(tmp_path):
    with pytest.raises(FileNotFoundError):
        profiles.profile_owner_path("nope", cwd=tmp_path, home=tmp_path)
    got = profiles.profile_owner_path("nope", cwd=tmp_path, home=tmp_path, allow_new=True)
    assert got == profiles.user_config_path(tmp_path)


def test_profile_owner_path_rejects_builtin(tmp_path):
    name = next(p.name for p in profiles.list_profiles(cwd=tmp_path, include_builtins=True)
                if profiles.is_builtin_profile(p.name))
    with pytest.raises(RuntimeError):
        profiles.profile_owner_path(name, cwd=tmp_path, home=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_profile_edit_primitives.py -k owner_path -v`
Expected: FAIL with `AttributeError: ... has no attribute 'profile_owner_path'`.

- [ ] **Step 3: Implement `profile_owner_path`**

```python
# src/code_review_loop/profiles.py
def profile_owner_path(
    name: str,
    *,
    cwd: Path,
    home: Path | None = None,
    allow_new: bool = False,
) -> Path:
    if is_builtin_profile(name):
        raise RuntimeError(builtin_profile_readonly_message(name))
    project_path = project_config_path(cwd)
    if name in load_profile_file(project_path).profiles:
        return project_path
    user_path = user_config_path(home)
    if name in load_profile_file(user_path).profiles:
        return user_path
    if allow_new:
        return user_path
    raise FileNotFoundError(f"profile not found: {name}")
```

- [ ] **Step 4: Re-point the private CLI helper at the public one**

In `src/code_review_loop/cli/commands/config.py`, replace the body of `_profile_config_owner_path` so the duplication is gone:

```python
def _profile_config_owner_path(name: str, cwd: Path, home: Path | None = None) -> Path:
    return profiles.profile_owner_path(name, cwd=cwd, home=home)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_profile_edit_primitives.py -k owner_path -v && pytest tests/ -k config -q`
Expected: new owner_path tests PASS; existing config tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add src/code_review_loop/profiles.py src/code_review_loop/cli/commands/config.py tests/test_profile_edit_primitives.py
git commit -m "feat(profiles): public profile_owner_path; dedupe CLI helper

REVREM-PLAN-009 T2.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm"
```

---

### Task 3: `save_profile_raw` — persist a whole raw profile to its owner file

**Files:**
- Modify: `src/code_review_loop/profiles.py` (add `save_profile_raw`)
- Test: `tests/test_profile_edit_primitives.py`

**Interfaces:**
- Consumes: `profile_owner_path` (T2), `parse_profile`, `write_profile_to_path`.
- Produces: `save_profile_raw(name: str, raw_profile: dict[str, Any], *, cwd: Path, home: Path | None = None) -> Path`. Validates by `parse_profile(name, raw_profile, source="<edit>")` (raises `ValueError` on invalid), resolves the owner file with `allow_new=True`, then `write_profile_to_path(owner, parsed, force=True, raw_profile=raw_profile)`. Returns the written path. This is the primitive the TUI "Save → profile" calls in-process.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_edit_primitives.py  (append)
def test_save_profile_raw_round_trips_minimal_toml(tmp_path):
    _write(tmp_path / ".revrem.toml",
           '[profiles.demo]\nreview.model = "old"\npipeline.max_iterations = 3\n')
    raw = dict(load := profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"])
    raw = profiles.deep_set_raw(raw, "review.model", "gpt-5.5")
    path = profiles.save_profile_raw("demo", raw, cwd=tmp_path, home=tmp_path)
    assert path == profiles.project_config_path(tmp_path)

    reloaded = profiles.load_profile_file(path).raw_profiles["demo"]
    assert reloaded["review"]["model"] == "gpt-5.5"
    assert reloaded["pipeline"]["max_iterations"] == 3  # preserved
    assert "remediation" not in reloaded  # stays minimal, no resolved-default bloat


def test_save_profile_raw_validates(tmp_path):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    bad = profiles.deep_set_raw({}, "pipeline.max_iterations", "5")
    bad["review"] = {"model": 123}  # wrong type for a model
    with pytest.raises(ValueError):
        profiles.save_profile_raw("demo", bad, cwd=tmp_path, home=tmp_path)


def test_save_profile_raw_preserves_sibling_profiles(tmp_path):
    # The real .revrem.toml holds multiple project profiles; editing one must
    # not drop the others (data-loss guard).
    _write(
        tmp_path / ".revrem.toml",
        '[profiles.default]\nreview.model = "old"\n\n'
        '[profiles.dogfood]\nreview.model = "keep"\npipeline.max_iterations = 5\n',
    )
    raw = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["default"]
    raw = profiles.deep_set_raw(raw, "review.model", "gpt-5.5")
    profiles.save_profile_raw("default", raw, cwd=tmp_path, home=tmp_path)

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles
    assert reloaded["default"]["review"]["model"] == "gpt-5.5"
    assert reloaded["dogfood"]["review"]["model"] == "keep"
    assert reloaded["dogfood"]["pipeline"]["max_iterations"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_profile_edit_primitives.py -k save_profile_raw -v`
Expected: FAIL with `AttributeError: ... has no attribute 'save_profile_raw'`.

- [ ] **Step 3: Implement `save_profile_raw`**

```python
# src/code_review_loop/profiles.py
def save_profile_raw(
    name: str,
    raw_profile: dict[str, Any],
    *,
    cwd: Path,
    home: Path | None = None,
) -> Path:
    parsed = parse_profile(name, raw_profile, source="<edit>")
    owner = profile_owner_path(name, cwd=cwd, home=home, allow_new=True)
    return write_profile_to_path(owner, parsed, force=True, raw_profile=raw_profile)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_profile_edit_primitives.py -k save_profile_raw -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/profiles.py tests/test_profile_edit_primitives.py
git commit -m "feat(profiles): save_profile_raw whole-profile persist to owner file

REVREM-PLAN-009 T3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm"
```

---

### Task 4: `set_profile_field` — load, set one field, persist

**Files:**
- Modify: `src/code_review_loop/profiles.py` (add `set_profile_field`)
- Test: `tests/test_profile_edit_primitives.py`

**Interfaces:**
- Consumes: `profile_owner_path` (T2), `load_profile_file`, `deep_set_raw` (T1), `save_profile_raw` (T3).
- Produces: `set_profile_field(name: str, dotted_key: str, value: str, *, cwd: Path, home: Path | None = None) -> Path`. Loads the owner file's minimal raw for `name`, applies `deep_set_raw`, persists via `save_profile_raw`, returns the path. Raises `FileNotFoundError` for an unknown profile, `RuntimeError` for a builtin, `ValueError` for an invalid value.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_edit_primitives.py  (append)
def test_set_profile_field_persists_single_field(tmp_path):
    _write(tmp_path / ".revrem.toml",
           '[profiles.demo]\nreview.model = "old"\npipeline.max_iterations = 3\n')
    profiles.set_profile_field("demo", "pipeline.max_iterations", "11",
                               cwd=tmp_path, home=tmp_path)
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["pipeline"]["max_iterations"] == 11
    assert reloaded["review"]["model"] == "old"


def test_set_profile_field_unknown_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        profiles.set_profile_field("ghost", "review.model", "x", cwd=tmp_path, home=tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_profile_edit_primitives.py -k set_profile_field -v`
Expected: FAIL with `AttributeError: ... has no attribute 'set_profile_field'`.

- [ ] **Step 3: Implement `set_profile_field`**

```python
# src/code_review_loop/profiles.py
def set_profile_field(
    name: str,
    dotted_key: str,
    value: str,
    *,
    cwd: Path,
    home: Path | None = None,
) -> Path:
    owner = profile_owner_path(name, cwd=cwd, home=home)  # raises for builtin/unknown
    current = load_profile_file(owner).raw_profiles.get(name, {})
    updated = deep_set_raw(current, dotted_key, value)
    return save_profile_raw(name, updated, cwd=cwd, home=home)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_profile_edit_primitives.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/code_review_loop/profiles.py tests/test_profile_edit_primitives.py
git commit -m "feat(profiles): set_profile_field one-shot field edit

REVREM-PLAN-009 T4.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm"
```

---

### Task 5: `revrem config set <name> <key> <value>` CLI subcommand

**Files:**
- Modify: `src/code_review_loop/cli/args.py` (register the `set` subparser in `build_config_parser`)
- Modify: `src/code_review_loop/cli/commands/config.py` (dispatch `set` in `main`)
- Test: `tests/test_cli_config_set_integration.py` (new)

**Interfaces:**
- Consumes: `profiles.set_profile_field` (T4).
- Produces: CLI `revrem config set NAME KEY VALUE` — exits `0` and prints `set KEY on NAME in <path>` on success; non-zero on error (unknown profile, builtin, bad value), surfacing the exception message. Honors the existing `--format {text,json}` flag on `config`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_config_set_integration.py
from __future__ import annotations

from pathlib import Path

from code_review_loop import profiles
from code_review_loop.cli.commands import config as config_cmd


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_config_set_updates_field(tmp_path, monkeypatch):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "review.model", "gpt-5.5"])
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["model"] == "gpt-5.5"


def test_config_set_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    code = config_cmd.main(["set", "ghost", "review.model", "x"])
    assert code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_config_set_integration.py -v`
Expected: FAIL — argparse rejects unknown subcommand `set` (SystemExit / non-zero) or `KeyError`.

- [ ] **Step 3: Register the subparser**

In `src/code_review_loop/cli/args.py`, inside `build_config_parser`, after the `edit` subparser block:

```python
    set_parser = subparsers.add_parser(
        "set",
        help="Set a single profile field non-interactively (e.g. review.model gpt-5.5).",
    )
    set_parser.add_argument("name")
    set_parser.add_argument("key", help="Dotted field path, e.g. pipeline.max_iterations.")
    set_parser.add_argument("value")
```

- [ ] **Step 4: Dispatch it in the command handler**

In `src/code_review_loop/cli/commands/config.py`, inside `main`, alongside the other `if args.command == ...` branches:

```python
        if args.command == "set":
            path = profiles.set_profile_field(
                args.name, args.key, args.value, cwd=Path.cwd()
            )
            print(f"set {args.key} on {args.name} in {path}")
            return CommandOk().exit_code
```

This matches the file's verified convention exactly: every branch ends `return CommandOk().exit_code` (see the `new`/`import` branches), and the `main` body is wrapped in `except (OSError, RuntimeError, ValueError) as exc: print(f"ERROR: {exc}", ...); return CommandFailed(...).exit_code`. `set_profile_field` raises `FileNotFoundError` (⊂ `OSError`) for unknown profiles, `RuntimeError` for builtins, and `ValueError` for bad values — all caught by that wrapper and mapped to a non-zero exit, satisfying `test_config_set_rejects_unknown`. No new error handling needed.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cli_config_set_integration.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full guard suite**

Run: `pytest tests/test_tui_cli_equivalence.py tests/test_profiles.py tests/test_profile_edit_primitives.py -q`
Expected: PASS — CLI-equivalence and existing profile behavior intact.

- [ ] **Step 7: Commit**

```bash
git add src/code_review_loop/cli/args.py src/code_review_loop/cli/commands/config.py tests/test_cli_config_set_integration.py
git commit -m "feat(cli): add non-interactive 'revrem config set'

REVREM-PLAN-009 T5.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm"
```

---

### Task 6: Document the new surface

**Files:**
- Modify: `docs/70-devex/devex-001-using-code-review-loop.md` (add a `config set` example)
- Modify: `CHANGELOG.md` (Unreleased → Added)

**Interfaces:** none (docs only).

- [ ] **Step 1: Add a devex example**

Under the profile-management section, add:

```markdown
### Set a single profile field

Edit one field without opening `$EDITOR`:

    revrem config set default pipeline.max_iterations 11
    revrem config set default review.model gpt-5.5

Builtins are read-only — clone first (`revrem config clone <builtin> mine`).
This is the same write path the TUI's working-copy save uses.
```

- [ ] **Step 2: Add a CHANGELOG entry**

Under `## [Unreleased]` → `### Added`:

```markdown
- `revrem config set <profile> <key> <value>` — non-interactive single-field profile edits (foundation for the loop-first TUI, REVREM-DESIGN-001 / PLAN-009).
```

- [ ] **Step 3: Commit**

```bash
git add docs/70-devex/devex-001-using-code-review-loop.md CHANGELOG.md
git commit -m "docs: document 'revrem config set'

REVREM-PLAN-009 T6.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TQ6JtXbH9nrt9DhcXHrKvm"
```

---

## Self-review

**Spec coverage (REVREM-DESIGN-001 §4.2):** the working-copy + explicit-save model needs (a) a whole-profile non-interactive persist → `save_profile_raw` (T3); (b) per-field edits → `deep_set_raw`/`set_profile_field` (T1, T4); (c) owner-file correctness (project vs user, builtins read-only) → `profile_owner_path` (T2); (d) CLI parity / "everything in the CLI" → `config set` (T5). The TUI consumes T3 in-process for Save→profile and may use T4/T5 for granular edits — delivered in Plan 2. ✔

**Out of scope (deferred to Plan 2):** nested `triage.routes.<name>.*` editing (the routes table needs add/remove semantics, not just scalar set) — `deep_set_raw` already supports the dotted path, but route add/remove and the routes-table widget land with the loop screen.

**Placeholder scan:** none — every code step contains complete, verified code. T5's return is the exact `return CommandOk().exit_code` convention (confirmed against `cli/outcome.py` and every existing branch in `config.py:main`), not a directive-to-self.

**Runtime-behavior verification (not just plan-internal consistency):**
- `_str`/`_optional_str` raise `ValueError` on non-str, so T3's "validate by re-parse" is genuinely strict (verified `profiles.py:1402`).
- Bool routing keys are `strict_on_unavailable_route` / `allow_model_escalation`; `default_route` is a string — `_BOOL_SUFFIXES` enumerates the bools explicitly (T1 covers it).
- `write_profile_to_path` writes the union of existing + edited profiles, so siblings survive — guarded by `test_save_profile_raw_preserves_sibling_profiles` (T3) against data loss on the user's real multi-profile `.revrem.toml`.

**Type consistency:** `deep_set_raw(raw, dotted_key, value) -> dict`, `profile_owner_path(name, *, cwd, home, allow_new) -> Path`, `save_profile_raw(name, raw_profile, *, cwd, home) -> Path`, `set_profile_field(name, dotted_key, value, *, cwd, home) -> Path` are used consistently across T1–T5. ✔
