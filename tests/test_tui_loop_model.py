from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import profiles
from code_review_loop.tui_loop_model import LoopEditModel, _profile_to_raw, _read_dotted
from code_review_loop.tui_loop_state import LOOP_META_DOTTED, PHASE_DOTTED


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project_profile(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(
        repo / ".revrem.toml",
        "\n".join(
            (
                "[profiles.dogfood]",
                "[profiles.dogfood.pipeline]",
                'base = "main"',
                "max_iterations = 4",
                "final_review = true",
                "[profiles.dogfood.review]",
                'harness = "codex"',
                'model = "gpt-5.5"',
            )
        )
        + "\n",
    )
    return repo


def test_field_value_returns_fallback_when_unedited(tmp_path: Path) -> None:
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    assert model.field_value("review.model", model.profile.review.model) == "gpt-5.5"
    assert model.is_dirty is False


def test_set_field_overlays_and_coerces(tmp_path: Path) -> None:
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.set_field("pipeline.max_iterations", "9")
    model.set_field("pipeline.final_review", "false")
    assert model.field_value("review.model", "gpt-5.5") == "gpt-5.6"
    assert model.field_value("pipeline.max_iterations", 4) == 9
    assert model.field_value("pipeline.final_review", True) is False
    assert model.is_dirty is True


def test_setting_existing_value_or_reverting_clears_dirty(tmp_path: Path) -> None:
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.5")
    assert model.edits == {}
    model.set_field("review.model", "gpt-5.6")
    assert model.is_dirty is True
    model.set_field("review.model", "gpt-5.5")
    assert model.edits == {}
    assert model.is_dirty is False


def test_authored_delta_uses_raw_dotted_keys(tmp_path: Path) -> None:
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("pipeline.max_iterations", "9")
    model.set_field("review.timeout_seconds", "0.5")
    assert model.authored_delta() == {
        "pipeline": {"max_iterations": 9},
        "review": {"timeout_seconds": 0.5},
    }


def test_save_persists_delta_reloads_and_clears_dirty(tmp_path: Path) -> None:
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.model", "gpt-5.6")
    model.set_field("pipeline.max_iterations", "9")
    path = model.save()
    assert path == repo / ".revrem.toml"
    assert model.is_dirty is False
    assert model.profile.review.model == "gpt-5.6"
    assert model.profile.pipeline.max_iterations == 9
    raw = profiles.load_profile_file(path).raw_profiles["dogfood"]
    assert raw["review"]["model"] == "gpt-5.6"
    assert raw["pipeline"]["max_iterations"] == 9


def test_route_row_clear_save_removes_cleared_route_field(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(
        repo / ".revrem.toml",
        "\n".join(
            (
                "[profiles.p]",
                "[profiles.p.pipeline]",
                'base = "main"',
                "[profiles.p.triage]",
                "enabled = true",
                'contract = "v2"',
                "[profiles.p.triage.routing]",
                "enabled = true",
                'default_route = "security"',
                "[profiles.p.triage.routes.security]",
                'harness = "codex"',
                'model = "gpt-5.4"',
                'fallback = "backup"',
                "[profiles.p.triage.routes.backup]",
                'harness = "codex"',
            )
        )
        + "\n",
    )

    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.security.model", None)
    model.save()

    raw = profiles.load_profile_file(repo / ".revrem.toml").raw_profiles["p"]
    assert raw["triage"]["routes"]["security"]["harness"] == "codex"
    assert "model" not in raw["triage"]["routes"]["security"]
    assert "fallback" in raw["triage"]["routes"]["security"]
    resolved = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert resolved.triage.routes["security"].model is None


def test_route_row_clear_inherited_optional_fields_persists_empty_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(
        repo / ".revrem.toml",
        "\n".join(
            (
                "[defaults.triage.routing]",
                'default_route = "security"',
                "[defaults.triage]",
                'contract = "v2"',
                "[defaults.triage.routes.security]",
                'harness = "codex"',
                'model = "gpt-5.4"',
                'fallback = "backup"',
                "[defaults.triage.routes.backup]",
                'harness = "codex"',
                "[profiles.p]",
                "[profiles.p.pipeline]",
                'base = "main"',
                "[profiles.p.triage]",
                "enabled = true",
            )
        )
        + "\n",
    )

    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.security.model", None)
    model.set_field("triage.routes.security.fallback", None)
    model.save()

    raw = profiles.load_profile_file(repo / ".revrem.toml").raw_profiles["p"]
    assert raw["triage"]["routes"]["security"]["model"] == ""
    assert raw["triage"]["routes"]["security"]["fallback"] == ""
    resolved = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert resolved.triage.routes["security"].model == ""
    assert resolved.triage.routes["security"].fallback == ""


def test_route_row_clear_inherited_reasoning_effort_and_timeout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(
        repo / ".revrem.toml",
        "\n".join(
            (
                "[defaults.triage.routing]",
                'default_route = "security"',
                "[defaults.triage.routes.security]",
                'harness = "codex"',
                'reasoning_effort = "medium"',
                "timeout_seconds = 300",
                "[defaults.triage.routes.backup]",
                'harness = "codex"',
                "[profiles.p]",
                "[profiles.p.pipeline]",
                'base = "main"',
                "[profiles.p.triage]",
                "enabled = true",
            )
        )
        + "\n",
    )

    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.security.reasoning_effort", None)
    model.set_field("triage.routes.security.timeout_seconds", None)
    model.save()

    raw = profiles.load_profile_file(repo / ".revrem.toml").raw_profiles["p"]
    assert raw["triage"]["routes"]["security"]["reasoning_effort"] == ""
    assert "timeout_seconds" not in raw["triage"]["routes"]["security"]
    resolved = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert resolved.triage.routes["security"].reasoning_effort == ""
    assert resolved.triage.routes["security"].timeout_seconds == 300


def test_invalid_save_keeps_dirty_edits(tmp_path: Path) -> None:
    repo = _project_profile(tmp_path)
    model = LoopEditModel.load("dogfood", cwd=repo)
    model.set_field("review.timeout_seconds", "not-a-number")
    with pytest.raises(ValueError):
        model.save()
    assert model.is_dirty is True
    assert model.edits == {"review.timeout_seconds": "not-a-number"}


def test_baseline_projection_covers_every_editable_dotted_key(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(
        repo / ".revrem.toml",
        "\n".join(
            (
                "[profiles.full]",
                "[profiles.full.pipeline]",
                'base = "main"',
                "max_iterations = 6",
                "final_review = true",
                'checks = ["pytest -q"]',
                "[profiles.full.review]",
                'harness = "codex"',
                'model = "gpt-5.5"',
                'reasoning_effort = "high"',
                "timeout_seconds = 600",
                "[profiles.full.triage]",
                "enabled = true",
                'harness = "codex"',
                'model = "gpt-5.3-codex-spark"',
                'reasoning_effort = "medium"',
                "timeout_seconds = 300",
                'contract = "v2"',
                "[profiles.full.triage.routing]",
                "enabled = true",
                'default_route = "codex-midi"',
                "strict_on_unavailable_route = true",
                "allow_model_escalation = true",
                "[profiles.full.triage.routes.codex-midi]",
                'harness = "codex"',
                'model = "gpt-5.4-mini"',
                "[profiles.full.remediation]",
                'harness = "codex"',
                'model = "gpt-5.4-mini"',
                'reasoning_effort = "medium"',
                "timeout_seconds = 700",
                "[profiles.full.commit]",
                "enabled = true",
                'harness = "codex"',
                'message_model = "gpt-5.3-codex-spark"',
                'reasoning_effort = "low"',
                "timeout_seconds = 120",
                "[profiles.full.runtime]",
                "inner_check_retries = 2",
            )
        )
        + "\n",
    )
    model = LoopEditModel.load("full", cwd=repo)
    raw = _profile_to_raw(model.profile)
    dotted_keys = {
        dotted_key
        for phase_keys in PHASE_DOTTED.values()
        for dotted_key in phase_keys.values()
    } | set(LOOP_META_DOTTED.values())
    for dotted_key in sorted(dotted_keys):
        baseline = _read_dotted(raw, dotted_key)
        assert model.field_value(dotted_key, baseline) == baseline


def test_builtin_profile_save_is_readonly_until_cloned(tmp_path: Path) -> None:
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
    with pytest.raises(RuntimeError, match="built-in profile .* is read-only"):
        model.save()


def test_route_cell_edit_save_materializes_inherited_route_like_config_set(
    tmp_path: Path,
) -> None:
    body = "\n".join(
        (
            "[defaults.triage.routing]",
            "enabled = true",
            'default_route = "security"',
            "[defaults.triage]",
            'contract = "v2"',
            "[defaults.triage.routes.security]",
            'harness = "codex"',
            'model = "gpt-5.4"',
            'reasoning_effort = "high"',
            'sandbox = "read-only"',
            "[profiles.p]",
            "[profiles.p.pipeline]",
            'base = "main"',
            "[profiles.p.triage]",
            "enabled = true",
        )
    )
    repo_model = tmp_path / "via_model" / "repo"
    repo_set = tmp_path / "via_set" / "repo"
    for repo in (repo_model, repo_set):
        (repo / ".git").mkdir(parents=True)
        _write(repo / ".revrem.toml", body + "\n")

    model = LoopEditModel.load("p", cwd=repo_model)
    model.set_field("triage.routes.security.model", "gpt-9")
    model.save()
    profiles.set_profile_field("p", "triage.routes.security.model", "gpt-9", cwd=repo_set)

    assert (repo_model / ".revrem.toml").read_text(encoding="utf-8") == (
        repo_set / ".revrem.toml"
    ).read_text(encoding="utf-8")


def test_route_cell_edit_save_materializes_fallback_closure(tmp_path: Path) -> None:
    body = "\n".join(
        (
            "[defaults.triage.routing]",
            "enabled = true",
            'default_route = "foo"',
            "[defaults.triage]",
            'contract = "v2"',
            "[defaults.triage.routes.foo]",
            'harness = "codex"',
            'fallback = "bar"',
            'sandbox = "read-only"',
            "[defaults.triage.routes.bar]",
            'harness = "codex"',
            'sandbox = "workspace-write"',
            "[profiles.p]",
            "[profiles.p.pipeline]",
            'base = "main"',
            "[profiles.p.triage]",
            "enabled = true",
        )
    )
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(repo / ".revrem.toml", body + "\n")

    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.routes.foo.model", "gpt-9")
    model.save()

    reloaded = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert reloaded.triage.routes["foo"].fallback == "bar"
    assert "bar" in reloaded.triage.routes


def test_route_add_from_disabled_routing_creates_saveable_v2_context(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _write(
        repo / ".revrem.toml",
        "[profiles.p]\n"
        "[profiles.p.pipeline]\n"
        'base = "main"\n'
        "[profiles.p.triage]\n"
        "enabled = true\n",
    )

    model = LoopEditModel.load("p", cwd=repo)
    model.set_field("triage.contract", "v2")
    model.set_field("triage.routing.enabled", "true")
    model.set_field("triage.routing.default_route", "audit")
    model.set_field("triage.routes.audit.harness", "codex")
    model.set_field("triage.routes.audit.sandbox", "workspace-write")
    model.save()

    reloaded = profiles.resolve_profile("p", cwd=repo, require_implemented=False)
    assert reloaded.triage.contract == "v2"
    assert reloaded.triage.routing.enabled is True
    assert reloaded.triage.routing.default_route == "audit"
    assert reloaded.triage.routes["audit"].harness == "codex"
    assert reloaded.triage.routes["audit"].sandbox == "workspace-write"
