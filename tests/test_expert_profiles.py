from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import expert_profiles, profiles
from code_review_loop.cli.commands import config as config_command


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def test_builtin_profiles_validate_and_enable_no_default_checks(tmp_path):
    names = expert_profiles.list_builtin_profiles()
    assert {"security", "performance", "refactor", "test-gap", "docs"} <= set(names)
    home = tmp_path / "home"
    repo = _repo(tmp_path)
    for name in names:
        resolved = profiles.resolve_profile(
            name, cwd=repo, home=home, require_implemented=False
        )
        assert resolved.source == profiles.BUILTIN_PROFILE_SOURCE
        assert resolved.pipeline.checks == ()


def test_builtin_profile_resolves_without_user_or_project_config(tmp_path):
    repo = _repo(tmp_path)
    home = tmp_path / "home"

    resolved = profiles.resolve_profile(
        "security", cwd=repo, home=home, require_implemented=False
    )

    assert resolved.name == "security"
    assert resolved.source == profiles.BUILTIN_PROFILE_SOURCE
    assert "Security lens" in resolved.description


def test_user_profile_shadows_builtin_profile(tmp_path):
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    user_path = profiles.user_config_path(home)
    user_path.parent.mkdir(parents=True)
    user_path.write_text(
        """
[profiles.security]
description = "User security override"

[profiles.security.review]
model = "user-model"
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_profile(
        "security", cwd=repo, home=home, require_implemented=False
    )

    assert resolved.description == "User security override"
    assert resolved.review.model == "user-model"
    assert resolved.source == str(user_path)


def test_project_profile_shadows_user_and_builtin_profile(tmp_path):
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    user_path = profiles.user_config_path(home)
    user_path.parent.mkdir(parents=True)
    user_path.write_text(
        """
[profiles.security]
description = "User security override"

[profiles.security.review]
model = "user-model"
""",
        encoding="utf-8",
    )
    profiles.project_config_path(repo).write_text(
        """
[profiles.security]
description = "Project security override"

[profiles.security.review]
model = "project-model"
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_profile(
        "security", cwd=repo, home=home, require_implemented=False
    )

    assert resolved.description == "Project security override"
    assert resolved.review.model == "project-model"
    assert resolved.source == str(profiles.project_config_path(repo))


def test_config_list_includes_builtin_source(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(home))

    assert config_command.main(["list", "--format", "json"]) == 0
    payload = {item["name"]: item for item in json.loads(capsys.readouterr().out)}

    assert payload["security"]["source"] == profiles.BUILTIN_PROFILE_SOURCE


def test_config_edit_and_delete_builtin_are_read_only(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("EDITOR", "true")

    assert config_command.main(["edit", "security"]) == 1
    assert "built-in profile 'security' is read-only" in capsys.readouterr().err

    assert config_command.main(["delete", "security", "--yes"]) == 1
    assert "built-in profile 'security' is read-only" in capsys.readouterr().err


def test_clone_builtin_profile_writes_editable_copy(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(home))

    assert config_command.main(["clone", "security", "security-local"]) == 0

    resolved = profiles.resolve_profile(
        "security-local", cwd=repo, home=home, require_implemented=False
    )
    assert resolved.source == str(profiles.user_config_path(home))
    assert "Security lens" in resolved.description
