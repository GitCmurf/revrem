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


def test_catalog_cache_invalidates_when_project_layer_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    project = tmp_path / ".revrem-catalog.toml"
    project.write_text(
        '[[model]]\nid="local-model"\nharness="codex"\nefforts=["low"]\n',
        encoding="utf-8",
    )
    first = model_catalog.load_catalog(tmp_path, home=tmp_path)
    project.write_text(
        '[[model]]\nid="local-model"\nharness="codex"\nefforts=["low","high"]\n',
        encoding="utf-8",
    )

    second = model_catalog.load_catalog(tmp_path, home=tmp_path)

    assert first.model("codex", "local-model").efforts == ("low",)
    assert second.model("codex", "local-model").efforts == ("low", "high")


def test_project_catalog_uses_repo_root_for_subdirectory_invocations(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()
    subdirectory = repo_root / "nested"
    subdirectory.mkdir()
    (repo_root / ".revrem-catalog.toml").write_text(
        '[[model]]\nid="gpt-5.6-luna"\nharness="codex"\nefforts=["low"]\n',
        encoding="utf-8",
    )

    assert model_catalog.load_catalog(subdirectory, home=tmp_path).model(
        "codex", "gpt-5.6-luna"
    ).efforts == ("low",)


def test_project_catalog_requires_harness_name(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\ndriver="gemini"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="harness entry in .* is missing required field 'name'"):
        model_catalog.load_catalog(tmp_path, home=tmp_path)


def test_project_catalog_rejects_alias_that_collides_with_built_in_harness(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\nname="codex"\ndriver="gemini"\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="collides with a built-in harness name"):
        model_catalog.load_catalog(tmp_path, home=tmp_path)


def test_project_catalog_requires_model_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[model]]\nharness="codex"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="model entry in .* is missing required field 'id'"):
        model_catalog.load_catalog(tmp_path, home=tmp_path)


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


@pytest.mark.parametrize("contents", ["", "{not-json", '{"models": null}'])
def test_incomplete_codex_cache_fails_open_to_packaged_catalog(
    tmp_path, monkeypatch, contents
):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(contents, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    model = model_catalog.load_catalog(tmp_path, home=tmp_path).model(
        "codex", "gpt-5.6-sol"
    )

    assert model.efforts == ("low", "medium", "high", "xhigh", "max", "ultra")


def test_non_utf8_codex_cache_fails_open_to_packaged_catalog(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_bytes(b"\xff\xfe")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    model = model_catalog.load_catalog(tmp_path, home=tmp_path).model(
        "codex", "gpt-5.6-sol"
    )

    assert model.efforts == ("low", "medium", "high", "xhigh", "max", "ultra")


@pytest.mark.parametrize(
    ("identifier_key", "identifier"),
    [("slug", 42), ("id", ["gpt-5.6-sol"]), ("model", {"id": "gpt-5.6-sol"})],
)
def test_malformed_codex_cache_identifiers_are_skipped(
    tmp_path, monkeypatch, identifier_key, identifier
):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        json.dumps({"models": [{identifier_key: identifier}]}), encoding="utf-8"
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    model = model_catalog.load_catalog(tmp_path, home=tmp_path).model(
        "codex", "gpt-5.6-sol"
    )

    assert model.efforts == ("low", "medium", "high", "xhigh", "max", "ultra")


def test_project_catalog_rejects_scalar_efforts_with_its_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    catalog_path = tmp_path / ".revrem-catalog.toml"
    catalog_path.write_text(
        '[[model]]\nid="local-model"\nefforts="high"\n', encoding="utf-8"
    )

    with pytest.raises(
        ValueError,
        match=rf"catalog model 'local-model' in {catalog_path} field 'efforts' must be a list or tuple",
    ):
        model_catalog.load_catalog(tmp_path, home=tmp_path)


def test_catalog_effort_tuples_remain_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    project = tmp_path / ".revrem-catalog.toml"
    project.write_text('[[model]]\nid="local-model"\n', encoding="utf-8")
    original_read_toml = model_catalog._read_toml

    def read_toml(path):
        if path == project:
            return {
                "model": [{"id": "local-model", "efforts": ("low", "high")}]
            }
        return original_read_toml(path)

    monkeypatch.setattr(model_catalog, "_read_toml", read_toml)

    assert model_catalog.load_catalog(tmp_path, home=tmp_path).model(
        "codex", "local-model"
    ).efforts == ("low", "high")


def test_known_invalid_selection_rejects_but_unknown_passes_with_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    with pytest.raises(ValueError, match="not supported"):
        model_catalog.validate_selection("codex", "gpt-5.6-luna", "ultra", cwd=tmp_path)
    assert "passing it through" in model_catalog.validate_selection(
        "codex", "future-model", "low", cwd=tmp_path
    )


def test_alias_harness_selection_validates_against_selected_driver(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\nname="team-codex"\ndriver="codex"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not supported"):
        model_catalog.validate_selection("team-codex", "gpt-5.6-luna", "ultra", cwd=tmp_path)


def test_catalog_models_for_alias_returns_driver_models(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\nname="team-codex"\ndriver="codex"\n',
        encoding="utf-8",
    )

    catalog = model_catalog.load_catalog(tmp_path, home=tmp_path)
    models = catalog.models_for("team-codex")

    assert any(item.harness == "codex" for item in models)


def test_codex_cache_scalar_reasoning_levels_are_ignored(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.6-sol",
                        "supported_reasoning_levels": "high",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    model = model_catalog.load_catalog(tmp_path, home=tmp_path).model("codex", "gpt-5.6-sol")
    assert model.efforts == ("low", "medium", "high", "xhigh", "max", "ultra")


def test_global_effort_vocab_validation_happens_before_catalog_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    with pytest.raises(ValueError, match="is not one of"):
        model_catalog.validate_selection("codex", "future-model", "quantum", cwd=tmp_path)


def test_project_harness_catalog_uses_catalog_executable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\nname="team-codex"\ndriver="codex"\nexecutable="/tmp/untrusted"\n',
        encoding="utf-8",
    )

    assert harnesses.resolve_executable("team-codex", {}, "codex") == "/tmp/untrusted"
    assert harnesses.resolve_executable(
        "team-codex", {"team-codex": "/opt/team-codex"}, "codex"
    ) == "/opt/team-codex"


def test_project_catalog_rejects_reserved_driver(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\nname="team-reserved"\ndriver="reserved"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown built-in driver 'reserved'"):
        model_catalog.load_catalog(tmp_path, home=tmp_path)


def test_codex_cache_list_json_shape(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        json.dumps(
            [
                {
                    "slug": "gpt-5.6-sol",
                    "default_reasoning_level": "high",
                    "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    model = model_catalog.load_catalog(tmp_path, home=tmp_path).model("codex", "gpt-5.6-sol")
    assert model.default_effort == "high"
    assert model.efforts == ("low", "high")


def test_models_list_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    assert models.main(["list", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(row["id"] == "gpt-5.6-sol" and "xhigh" in row["efforts"] for row in payload)


def test_models_list_reports_catalog_validation_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-codex"))
    (tmp_path / ".revrem-catalog.toml").write_text(
        '[[harness]]\ndriver="codex"\n',
        encoding="utf-8",
    )

    assert models.main(["list"]) == 1
    assert "ERROR:" in capsys.readouterr().err
