from __future__ import annotations

import json

import pytest

from code_review_loop import harnesses, model_catalog
from code_review_loop.cli.commands import models


def test_packaged_gpt_56_family_exposes_full_effort_matrix(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    catalog = model_catalog.load_catalog(tmp_path, home=tmp_path)

    assert catalog.model("codex", "gpt-5.6-sol").efforts == (
        "low", "medium", "high", "xhigh", "max", "ultra"
    )
    assert catalog.model("codex", "gpt-5.6-terra").efforts[-1] == "ultra"
    assert catalog.model("codex", "gpt-5.6-luna").efforts[-1] == "max"


def test_project_catalog_overrides_packaged_model(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[model]]\nid="gpt-5.6-luna"\nharness="codex"\nefforts=["low"]\n',
        encoding="utf-8",
    )
    assert model_catalog.load_catalog(tmp_path, home=tmp_path).model(
        "codex", "gpt-5.6-luna"
    ).efforts == ("low",)


def test_codex_cache_reasoning_level_shape_overlays_packaged_catalog(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        json.dumps({"models": [{
            "slug": "gpt-5.6-sol",
            "default_reasoning_level": "high",
            "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
        }]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    model = model_catalog.load_catalog(tmp_path, home=tmp_path).model("codex", "gpt-5.6-sol")
    assert model.default_effort == "high"
    assert model.efforts == ("low", "high")


def test_codex_cache_without_effort_metadata_preserves_packaged_capabilities(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        json.dumps({"models": [{"slug": "gpt-5.6-luna"}]}), encoding="utf-8"
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    model = model_catalog.load_catalog(tmp_path, home=tmp_path).model("codex", "gpt-5.6-luna")
    assert model.efforts == ("low", "medium", "high", "xhigh", "max")


def test_known_invalid_selection_rejects_but_unknown_passes_with_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    with pytest.raises(ValueError, match="not supported"):
        model_catalog.validate_selection("codex", "gpt-5.6-luna", "ultra", cwd=tmp_path)
    assert "passing it through" in model_catalog.validate_selection(
        "codex", "future-model", "quantum", cwd=tmp_path
    )


def test_project_harness_catalog_cannot_inject_executable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\nname="team-codex"\ndriver="codex"\nexecutable="/tmp/untrusted"\n',
        encoding="utf-8",
    )

    assert harnesses.resolve_executable("team-codex", {}, "codex") == "team-codex"
    assert harnesses.resolve_executable(
        "team-codex", {"team-codex": "/opt/team-codex"}, "codex"
    ) == "/opt/team-codex"


def test_models_list_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    assert models.main(["list", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(row["id"] == "gpt-5.6-sol" and "xhigh" in row["efforts"] for row in payload)
