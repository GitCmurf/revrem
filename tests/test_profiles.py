from __future__ import annotations

import json
from pathlib import Path

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
[defaults.review]
model = "gpt-5.4-mini"
reasoning_effort = "low"

[defaults.runtime]
output_last_message = false

[profiles.final-pr]
description = "User profile"

[profiles.final-pr.pipeline]
base = "main"
max_iterations = 2
checks = ["pytest -q"]

[profiles.final-pr.review]
reasoning_effort = "medium"

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
    assert resolved.review.model == "gpt-5.4-mini"
    assert resolved.review.reasoning_effort == "medium"
    assert resolved.remediation.model == "gpt-5.4-mini"
    assert resolved.runtime.output_last_message is False
    assert resolved.output.debug_status_detection is True
    assert resolved.output.terminal_title is True


def test_profile_accepts_budget_defaults(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.demo.budgets]
max_wall_seconds = 120
max_tokens = 10000
max_usd = "1.25"
soft_warn_fraction = 0.5
""",
        encoding="utf-8",
    )

    loaded = profiles.load_profile_file(path)

    assert loaded.profiles["demo"].budgets.max_wall_seconds == 120
    assert loaded.profiles["demo"].budgets.max_tokens == 10000
    assert str(loaded.profiles["demo"].budgets.max_usd) == "1.25"
    assert loaded.profiles["demo"].budgets.soft_warn_fraction == 0.5


def test_profile_rejects_invalid_budget_values(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.demo.budgets]
soft_warn_fraction = 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="budgets.soft_warn_fraction"):
        profiles.load_profile_file(path)


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


def test_project_config_path_discovers_repo_root_from_subdirectory(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    nested = repo / "one" / "two"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / ".revrem.toml").write_text(
        """
[profiles.final-pr.pipeline]
base = "trunk"
""",
        encoding="utf-8",
    )

    assert profiles.project_config_path(nested) == repo / ".revrem.toml"
    resolved = profiles.resolve_profile("final-pr", cwd=nested, home=home)

    assert resolved.pipeline.base == "trunk"


def test_resolve_defaults_allows_project_defaults_to_reset_user_defaults(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    user_path = profiles.user_config_path(home)
    user_path.parent.mkdir(parents=True)
    user_path.write_text(
        """
[defaults.pipeline]
max_iterations = 4

[defaults.review]
model = "gpt-5.5"

[defaults.output]
debug_status_detection = true
""",
        encoding="utf-8",
    )
    profiles.project_config_path(cwd).write_text(
        """
[defaults.pipeline]
max_iterations = 2

[defaults.output]
debug_status_detection = false
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_defaults(cwd=cwd, home=home)

    assert resolved.name == "<defaults>"
    assert resolved.pipeline.max_iterations == 2
    assert resolved.review.model == "gpt-5.5"
    assert resolved.output.debug_status_detection is False


def test_resolve_defaults_rejects_unimplemented_harness(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.project_config_path(cwd)
    path.write_text(
        """
[defaults.review]
harness = "claude"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only the codex backend is implemented"):
        profiles.resolve_defaults(cwd=cwd, home=home)


def test_resolve_profile_rejects_unknown_profile_when_only_defaults_exist(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    config_path = profiles.project_config_path(cwd)
    config_path.write_text(
        """
[defaults.pipeline]
checks = ["pytest -q"]
""",
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="profile not found: typo"):
        profiles.resolve_profile("typo", cwd=cwd, home=home)


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


def test_resolve_profile_allows_reserved_harnesses_for_management_commands(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.user_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[profiles.future.review]
harness = "claude"

[profiles.future.triage]
enabled = true
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_profile(
        "future",
        cwd=cwd,
        home=home,
        require_implemented=False,
    )

    assert resolved.review.harness == "claude"
    assert resolved.triage.enabled is True


def test_resolve_profile_allows_executable_codex_triage(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.user_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[profiles.triaged.triage]
enabled = true
model = "gpt-5.4-mini"
reasoning_effort = "low"
timeout_seconds = 60
prompt = "Break down the findings."
on_invalid = "stop"
""",
        encoding="utf-8",
    )

    resolved = profiles.resolve_profile("triaged", cwd=cwd, home=home)

    assert resolved.triage.enabled is True
    assert resolved.triage.harness == "codex"
    assert resolved.triage.model == "gpt-5.4-mini"
    assert resolved.triage.reasoning_effort == "low"
    assert resolved.triage.timeout_seconds == 60
    assert resolved.triage.prompt == "Break down the findings."
    assert resolved.triage.on_invalid == "stop"


def test_profile_rejects_invalid_triage_on_invalid_policy(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.user_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[profiles.triaged.triage]
on_invalid = "hide-findings"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="triage.on_invalid must be one of continue, stop"):
        profiles.resolve_profile("triaged", cwd=cwd, home=home)


def test_profile_commit_defaults_to_spark_message_model(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.demo.commit]
enabled = true
""",
        encoding="utf-8",
    )

    loaded = profiles.load_profile_file(path)

    assert loaded.profiles["demo"].commit.enabled is True
    assert loaded.profiles["demo"].commit.message_model == "gpt-5.3-codex-spark"
    assert loaded.profiles["demo"].commit.on_hook_failure == "remediate"


def test_profile_accepts_explicit_commit_message_model_and_prompt(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.demo.commit]
enabled = true
harness = "claude"
message_model = "gpt-test-commit"
message_prompt = "Write a subject."
on_hook_failure = "stop"
""",
        encoding="utf-8",
    )

    loaded = profiles.load_profile_file(path)

    assert loaded.profiles["demo"].commit.harness == "claude"
    assert loaded.profiles["demo"].commit.message_model == "gpt-test-commit"
    assert loaded.profiles["demo"].commit.message_prompt == "Write a subject."
    assert loaded.profiles["demo"].commit.on_hook_failure == "stop"


def test_profile_rejects_invalid_commit_hook_failure_policy(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.bad.commit]
on_hook_failure = "maybe"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="commit.on_hook_failure must be one of"):
        profiles.load_profile_file(path)


def test_profile_rejects_unknown_commit_keys(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.bad.commit]
enabled = true
model = "gpt-test"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="commit contains unknown keys: model"):
        profiles.load_profile_file(path)


def test_profile_accepts_rich_progress_style(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.demo.output]
progress_style = "rich"
""",
        encoding="utf-8",
    )

    loaded = profiles.load_profile_file(path)

    assert loaded.profiles["demo"].output.progress_style == "rich"


def test_resolve_profile_rejects_unimplemented_executable_triage_harness(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.user_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[profiles.future.triage]
enabled = true
harness = "gemini"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only the codex backend is implemented"):
        profiles.resolve_profile("future", cwd=cwd, home=home)


def test_resolve_profile_rejects_unimplemented_executable_commit_harness(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    path = profiles.user_config_path(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        """
[profiles.future.commit]
enabled = true
harness = "gemini"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only the codex backend is implemented"):
        profiles.resolve_profile("future", cwd=cwd, home=home)


def test_profile_rejects_boolean_timeout_seconds(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.bad.review]
timeout_seconds = false
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="bad.review.timeout_seconds must be a number"):
        profiles.load_profile_file(path)


def test_profile_rejects_negative_timeout_seconds(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.bad.review]
timeout_seconds = -1

[profiles.bad.remediation]
timeout_seconds = 30
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="review.timeout_seconds must be 0 or greater"):
        profiles.load_profile_file(path)


@pytest.mark.parametrize(
    ("section", "value"),
    [
        ("review", "ultra"),
        ("remediation", "urgent"),
    ],
)
def test_profile_rejects_invalid_reasoning_effort_values(tmp_path, section, value):
    path = tmp_path / "profiles.toml"
    path.write_text(
        f"""
[profiles.bad.{section}]
reasoning_effort = "{value}"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=f"bad\\.{section}\\.reasoning_effort must be one of"):
        profiles.load_profile_file(path)


@pytest.mark.parametrize(
    ("section", "field", "message"),
    [
        ("pipeline", "max_iterations", "pipeline.max_iterations must be an integer"),
        (
            "runtime",
            "max_remediation_input_chars",
            "runtime.max_remediation_input_chars must be an integer",
        ),
    ],
)
def test_profile_rejects_boolean_integer_fields(tmp_path, section, field, message):
    path = tmp_path / "profiles.toml"
    path.write_text(
        f"""
[profiles.bad.{section}]
{field} = true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        profiles.load_profile_file(path)


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("exec_sandbox", "workspace", "runtime.exec_sandbox must be one of"),
        ("exec_color", "bright", "runtime.exec_color must be one of"),
    ],
)
def test_profile_rejects_invalid_runtime_enum_values(tmp_path, setting, value, message):
    path = tmp_path / "profiles.toml"
    path.write_text(
        f"""
[profiles.bad.runtime]
{setting} = "{value}"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        profiles.load_profile_file(path)


def test_profile_rejects_unknown_keys_in_profile_and_nested_sections(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profiles.bad]
description = "Bad profile"
unexpected = true

[profiles.good.pipeline]
max_iteration = 3
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="bad contains unknown keys: unexpected"):
        profiles.load_profile_file(path)

    path.write_text(
        """
[profiles.good.pipeline]
max_iteration = 3
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pipeline contains unknown keys: max_iteration"):
        profiles.load_profile_file(path)


def test_profile_rejects_unknown_top_level_keys(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text(
        """
[profile.bad.review]
harness = "codex"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"profile file .* contains unknown keys: profile"):
        profiles.load_profile_file(path)


def test_write_delete_and_import_user_profiles(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.review]
model = "gpt-5.5"

[profiles.existing]
description = "Existing profile"
""",
        encoding="utf-8",
    )
    profile = profiles.minimal_profile("smoke", description="Smoke test")

    path = profiles.write_user_profile(profile, home=home)
    assert path == profiles.user_config_path(home)
    assert "[defaults.review]" in path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in path.read_text(encoding="utf-8")
    assert "[profiles.smoke]" in path.read_text(encoding="utf-8")
    rendered = path.read_text(encoding="utf-8")
    assert 'base = "main"' not in rendered
    assert "max_iterations = 2" not in rendered
    assert "max_remediation_input_chars = 200000" not in rendered
    assert profiles.resolve_profile("smoke", cwd=tmp_path, home=home).description == "Smoke test"

    exported = tmp_path / "export.toml"
    exported.write_text(
        """
[profiles.imported]
description = "Imported profile"
""",
        encoding="utf-8",
    )

    def fail_write_text(self: Path, *_args, **_kwargs):
        raise AssertionError("Path.write_text should not be used for profile writes")

    monkeypatch.setattr(Path, "write_text", fail_write_text)
    profiles.write_user_profile(profile, home=home, force=True)
    assert "[defaults.review]" in config_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in config_path.read_text(encoding="utf-8")
    assert 'base = "main"' not in config_path.read_text(encoding="utf-8")
    profiles.import_user_profiles(exported, home=home)
    assert "[defaults.review]" in config_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in config_path.read_text(encoding="utf-8")
    assert 'base = "main"' not in config_path.read_text(encoding="utf-8")
    profiles.delete_user_profile("smoke", home=home)
    assert "[defaults.review]" in config_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in config_path.read_text(encoding="utf-8")
    assert 'base = "main"' not in config_path.read_text(encoding="utf-8")

    assert profiles.resolve_profile("imported", cwd=tmp_path, home=home).name == "imported"
    with pytest.raises(FileNotFoundError):
        profiles.resolve_profile("smoke", cwd=tmp_path, home=home)


def test_write_user_profile_round_trips_control_characters(tmp_path):
    home = tmp_path / "home"
    profile = profiles.Profile(name="smoke", description="before\x1bafter")

    path = profiles.write_user_profile(profile, home=home)
    loaded = profiles.load_profile_file(path)

    assert loaded.profiles["smoke"].description == "before\x1bafter"


def test_import_user_profiles_preserves_source_defaults(tmp_path):
    home = tmp_path / "home"
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.review]
model = "gpt-5.4-mini"
""",
        encoding="utf-8",
    )

    exported = tmp_path / "export.toml"
    exported.write_text(
        """
[defaults.review]
model = "gpt-5.5"
reasoning_effort = "low"

[defaults.pipeline]
max_iterations = 5

[profiles.imported.review]
reasoning_effort = "medium"

[profiles.imported.pipeline]
base = "trunk"
""",
        encoding="utf-8",
    )

    profiles.import_user_profiles(exported, home=home)

    rendered = config_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in rendered
    assert 'reasoning_effort = "medium"' in rendered
    assert 'max_iterations = 5' in rendered

    resolved = profiles.resolve_profile("imported", cwd=tmp_path, home=home)
    assert resolved.review.model == "gpt-5.5"
    assert resolved.review.reasoning_effort == "medium"
    assert resolved.pipeline.max_iterations == 5
    assert resolved.pipeline.base == "trunk"


def test_clone_user_profile_writes_resolved_profile_to_user_config(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    project_config = repo / ".revrem.toml"
    project_config.write_text(
        """
[defaults.review]
model = "gpt-5.5"

[profiles.source]
description = "Source profile"

[profiles.source.pipeline]
base = "trunk"
""",
        encoding="utf-8",
    )

    path = profiles.clone_user_profile("source", "copy", cwd=repo, home=home)

    assert path == profiles.user_config_path(home)
    rendered = path.read_text(encoding="utf-8")
    assert "[profiles.copy]" in rendered
    assert 'description = "Source profile"' in rendered
    cloned = profiles.resolve_profile("copy", cwd=repo, home=home)
    assert cloned.review.model == "gpt-5.5"
    assert cloned.pipeline.base == "trunk"


def test_clone_user_profile_preserves_explicit_builtin_override_over_project_defaults(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    project_config = repo / ".revrem.toml"
    project_config.write_text(
        """
[defaults.pipeline]
final_review = false

[profiles.source]
description = "Source profile"

[profiles.source.pipeline]
final_review = true
""",
        encoding="utf-8",
    )

    path = profiles.clone_user_profile("source", "copy", cwd=repo, home=home)

    rendered = path.read_text(encoding="utf-8")
    assert "[profiles.copy.pipeline]" in rendered
    assert "final_review = true" in rendered
    cloned = profiles.resolve_profile("copy", cwd=tmp_path, home=home)
    assert cloned.pipeline.final_review is True


def test_prompt_for_new_profile_collects_separate_review_and_remediation_models():
    answers = iter(
        [
            "Wizard profile",
            "codex",
            "gpt-5.5",
            "gpt-5.4-mini",
            "medium",
            "1800",
            "git diff --check",
        ]
    )

    profile = profiles.prompt_for_new_profile("wizard", input_fn=lambda _prompt: next(answers))

    assert profile.name == "wizard"
    assert profile.description == "Wizard profile"
    assert profile.review.model == "gpt-5.5"
    assert profile.remediation.model == "gpt-5.4-mini"
    assert profile.review.reasoning_effort == "medium"
    assert profile.remediation.reasoning_effort == "medium"
    assert profile.review.timeout_seconds == 1800
    assert profile.pipeline.checks == ("git diff --check",)


def test_rewrite_user_profiles_preserves_explicit_builtin_overrides(tmp_path):
    home = tmp_path / "home"
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.pipeline]
base = "trunk"

[profiles.main.pipeline]
base = "main"

[profiles.keep]
description = "Keep me"
""",
        encoding="utf-8",
    )

    profiles.write_user_profile(profiles.minimal_profile("smoke"), home=home)

    rendered = config_path.read_text(encoding="utf-8")
    assert '[profiles.main.pipeline]' in rendered
    assert 'base = "main"' in rendered
    assert profiles.resolve_profile("main", cwd=tmp_path, home=home).pipeline.base == "main"


def test_rewrite_user_profiles_preserves_implicit_shared_defaults(tmp_path):
    home = tmp_path / "home"
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.output]
terminal_title = true

[profiles.existing]
description = "Existing profile"
""",
        encoding="utf-8",
    )

    profiles.write_user_profile(profiles.minimal_profile("smoke"), home=home)

    rendered = config_path.read_text(encoding="utf-8")
    assert "[profiles.existing.output]" not in rendered
    assert "terminal_title = false" not in rendered
    assert profiles.resolve_profile("existing", cwd=tmp_path, home=home).output.terminal_title is True


def test_write_user_profile_quotes_profile_names_and_round_trips(tmp_path):
    home = tmp_path / "home"
    profile = profiles.minimal_profile("foo.bar baz", description="Quoted profile")

    path = profiles.write_user_profile(profile, home=home)
    rendered = path.read_text(encoding="utf-8")

    assert '[profiles."foo.bar baz"]' in rendered
    assert '[profiles."foo.bar baz".review]' not in rendered
    assert profiles.resolve_profile("foo.bar baz", cwd=tmp_path, home=home).description == "Quoted profile"


def test_write_user_profile_quotes_non_ascii_profile_names(tmp_path):
    home = tmp_path / "home"
    profile = profiles.minimal_profile("démo", description="Non-ASCII profile")

    path = profiles.write_user_profile(profile, home=home)
    rendered = path.read_text(encoding="utf-8")

    assert '[profiles."démo"]' in rendered
    assert "[profiles.démo]" not in rendered
    assert profiles.resolve_profile("démo", cwd=tmp_path, home=home).description == "Non-ASCII profile"


def test_profile_json_is_stable():
    data = json.loads(profiles.profile_to_json(profiles.minimal_profile("demo")))

    assert data["name"] == "demo"
    assert data["pipeline"]["base"] == "main"
    assert data["review"]["harness"] == "codex"
    assert data["triage"]["enabled"] is False
