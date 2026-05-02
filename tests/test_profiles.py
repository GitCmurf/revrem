from __future__ import annotations

import json

import pytest

from code_review_loop import profiles


def test_resolve_profile_merges_user_project_and_defaults(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    user_path = profiles.user_config_path(home)
    user_path.parent.mkdir(parents=True)
    user_path.write_text(
        """
[profiles.final-pr]
description = "User profile"

[profiles.final-pr.pipeline]
base = "main"
max_iterations = 2
checks = ["pytest -q"]

[profiles.final-pr.review]
model = "gpt-5.5"

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"

[profiles.final-pr.output]
summary_format = "text"
debug_status_detection = true
""",
        encoding="utf-8",
    )
    profiles.project_config_path(cwd).write_text(
        """
[defaults.pipeline]
checks = ["pytest -q", "git diff --check"]

[profiles.final-pr.pipeline]
base = "trunk"

[profiles.final-pr.output]
terminal_title = true
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_profile("final-pr", cwd=cwd, home=home)

    assert resolved.description == "User profile"
    assert resolved.pipeline.base == "trunk"
    assert resolved.pipeline.max_iterations == 2
    assert resolved.pipeline.checks == ("pytest -q", "git diff --check")
    assert resolved.review.model == "gpt-5.5"
    assert resolved.remediation.model == "gpt-5.4-mini"
    assert resolved.output.debug_status_detection is True
    assert resolved.output.terminal_title is True


def test_resolve_profile_allows_project_to_override_boolean_to_false(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    user_path = profiles.user_config_path(home)
    user_path.parent.mkdir(parents=True)
    user_path.write_text(
        """
[profiles.final-pr.output]
debug_status_detection = true
terminal_title = true
""",
        encoding="utf-8",
    )
    profiles.project_config_path(cwd).write_text(
        """
[profiles.final-pr.output]
debug_status_detection = false
terminal_title = false
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_profile("final-pr", cwd=cwd, home=home)

    assert resolved.output.debug_status_detection is False
    assert resolved.output.terminal_title is False


def test_profile_rejects_unknown_harness(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.bad.review]
harness = "not-real"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="review.harness"):
        profiles.load_profile_file(path)


def test_resolved_profile_rejects_unimplemented_harness(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.user_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[profiles.future.review]
harness = "claude"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only the codex backend is implemented"):
        profiles.resolve_profile("future", cwd=cwd, home=home)


def test_write_delete_and_import_user_profiles(tmp_path):
    home = tmp_path / "home"
    profile = profiles.minimal_profile("smoke", description="Smoke test")

    path = profiles.write_user_profile(profile, home=home)
    assert path == profiles.user_config_path(home)
    assert profiles.resolve_profile("smoke", cwd=tmp_path, home=home).description == "Smoke test"

    exported = tmp_path / "export.toml"
    exported.write_text(
        profiles.profile_to_toml(profiles.minimal_profile("imported"), include_wrapper=True),
        encoding="utf-8",
    )
    profiles.import_user_profiles(exported, home=home)
    assert profiles.resolve_profile("imported", cwd=tmp_path, home=home).name == "imported"

    profiles.delete_user_profile("smoke", home=home)
    with pytest.raises(FileNotFoundError):
        profiles.resolve_profile("smoke", cwd=tmp_path, home=home)


def test_profile_json_is_stable():
    data = json.loads(profiles.profile_to_json(profiles.minimal_profile("demo")))

    assert data["name"] == "demo"
    assert data["pipeline"]["base"] == "main"
    assert data["review"]["harness"] == "codex"
    assert data["triage"]["enabled"] is False
