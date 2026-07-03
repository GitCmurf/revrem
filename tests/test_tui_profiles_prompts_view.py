from __future__ import annotations

from pathlib import Path

from code_review_loop import (
    profiles,
    tui_loop_state,
    tui_profiles_state,
    tui_prompts_state,
    tui_state,
)
from code_review_loop.tui_loop_model import LoopEditModel


def _snapshot(tmp_path: Path) -> tui_state.HomeSnapshot:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.dogfood]\n"
        "[profiles.dogfood.pipeline]\n"
        'base = "main"\n'
        "max_iterations = 3\n",
        encoding="utf-8",
    )
    return tui_state.build_home_snapshot(cwd=repo, home=tmp_path / "home")


def test_picker_groups_yours_before_presets(tmp_path: Path) -> None:
    rows = tui_profiles_state.profile_picker_groups(_snapshot(tmp_path))
    assert rows
    groups = [row.group for row in rows]
    if "presets" in groups and "yours" in groups:
        assert groups.index("yours") < groups.index("presets")
    dogfood = next(row for row in rows if row.name == "dogfood")
    assert dogfood.group == "yours"
    assert dogfood.source_label == "project"
    assert "main" in dogfood.summary and "3" in dogfood.summary


def test_picker_classifies_builtins_as_presets(tmp_path: Path) -> None:
    rows = tui_profiles_state.profile_picker_groups(_snapshot(tmp_path))
    builtins = [row for row in rows if row.source_label == "builtin"]
    assert builtins
    assert all(row.group == "presets" for row in builtins)


def test_prompt_inventory_lists_builtin_fragments_and_contracts() -> None:
    assets = tui_prompts_state.prompt_inventory()
    names = {asset.name for asset in assets}
    assert "security-checklist" in names
    assert {"triage_v1", "triage_v2"} <= names
    security = next(asset for asset in assets if asset.name == "security-checklist")
    assert security.kind == "fragment"
    assert security.trust == "builtin"
    assert security.preview


def test_prompt_inventory_is_sorted_and_stable() -> None:
    first = tui_prompts_state.prompt_inventory()
    second = tui_prompts_state.prompt_inventory()
    assert first == second
    fragment_names = [asset.name for asset in first if asset.kind == "fragment"]
    assert fragment_names == sorted(fragment_names)


def test_prompt_asset_text_loads_fragment_and_contract(tmp_path: Path) -> None:
    assets = tui_prompts_state.prompt_inventory()
    fragment = next(asset for asset in assets if asset.name == "security-checklist")
    contract = next(asset for asset in assets if asset.name == "triage_v2")
    assert (
        "security"
        in tui_prompts_state.prompt_asset_text(fragment, cwd=tmp_path).lower()
    )
    assert "single JSON object" in tui_prompts_state.prompt_asset_text(
        contract, cwd=tmp_path
    )


def test_prompt_field_label_is_harness_aware() -> None:
    assert (
        tui_prompts_state.prompt_field_label("review", "codex", None)
        == "built-in review (codex)"
    )
    assert tui_prompts_state.prompt_field_label("triage", "codex", None) == "<default>"
    assert (
        tui_prompts_state.prompt_field_label("triage", "claude", "Focus on docs drift")
        == "Focus on docs drift"
    )


def test_triage_route_rows_overlay_edits_and_selection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.p]\n"
        "[profiles.p.pipeline]\n"
        'base = "main"\n'
        "[profiles.p.triage]\n"
        "enabled = true\n"
        'contract = "v2"\n'
        "[profiles.p.triage.routing]\n"
        "enabled = true\n"
        'default_route = "security"\n'
        "[profiles.p.triage.routes.security]\n"
        'harness = "codex"\n'
        'model = "gpt-5.4"\n'
        'sandbox = "read-only"\n',
        encoding="utf-8",
    )
    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.security.model", "gpt-9")

    rows = tui_loop_state.triage_route_rows(model, selected_route="security")

    assert rows[0].name == "security"
    assert rows[0].model == "gpt-9"
    assert rows[0].selected is True


def test_triage_route_rows_include_unsaved_new_route(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.p]\n"
        "[profiles.p.pipeline]\n"
        'base = "main"\n'
        "[profiles.p.triage]\n"
        "enabled = true\n"
        'contract = "v2"\n'
        "[profiles.p.triage.routing]\n"
        "enabled = true\n"
        'default_route = "security"\n'
        "[profiles.p.triage.routes.security]\n"
        'harness = "codex"\n'
        'sandbox = "read-only"\n',
        encoding="utf-8",
    )
    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.audit.harness", "codex")
    model.set_field("triage.routes.audit.sandbox", "workspace-write")

    rows = tui_loop_state.triage_route_rows(model, selected_route="audit")

    audit = next(row for row in rows if row.name == "audit")
    assert audit.harness == "codex"
    assert audit.sandbox == "workspace-write"
    assert audit.selected is True


def test_builtin_profile_save_is_readonly_until_cloned_from_picker_context(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    home = tmp_path / "home"
    name = next(
        item.name
        for item in profiles.list_profiles(cwd=repo, home=home, include_builtins=True)
        if item.source == profiles.BUILTIN_PROFILE_SOURCE
    )
    model = LoopEditModel.load(name, cwd=repo, home=home)
    model.set_field("review.model", "gpt-9")
    try:
        model.save()
    except RuntimeError as exc:
        assert "built-in profile" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("built-in profile save unexpectedly succeeded")
