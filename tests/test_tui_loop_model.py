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
