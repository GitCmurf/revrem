from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import profiles
from code_review_loop.tui_loop_model import LoopEditModel


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

