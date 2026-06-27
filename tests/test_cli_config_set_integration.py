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


def test_config_set_accepts_float_timeout(tmp_path, monkeypatch):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "review.timeout_seconds", "0.5"])
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["timeout_seconds"] == 0.5


def test_config_set_accepts_integer_field(tmp_path, monkeypatch):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "pipeline.max_iterations", "11"])
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["pipeline"]["max_iterations"] == 11


def test_config_set_accepts_non_timeout_float_field(tmp_path, monkeypatch):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "budgets.max_wall_seconds", "7200.5"])
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["budgets"]["max_wall_seconds"] == 7200.5


def test_config_set_does_not_materialize_inherited_defaults(tmp_path, monkeypatch):
    _write(
        tmp_path / ".revrem.toml",
        '[defaults]\n'
        '[defaults.triage]\n'
        'enabled = true\n'
        '[defaults.triage.routing]\n'
        'default_route = "security"\n\n'
        '[profiles.demo]\n'
        'review.model = "old"\n',
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "review.timeout_seconds", "0.5"])
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["model"] == "old"
    assert reloaded["review"]["timeout_seconds"] == 0.5
    assert "triage" not in reloaded


def test_config_set_can_clear_inherited_description_with_empty_string(tmp_path, monkeypatch):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        '[defaults]\n'
        'description = "Global description"\n',
    )
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "description", ""])
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["description"] == ""
    assert profiles.resolve_profile("demo", cwd=tmp_path, home=tmp_path).description == ""


def test_config_set_does_not_materialize_nested_routing_inheritance(tmp_path, monkeypatch):
    _write(
        tmp_path / ".revrem.toml",
        '[defaults]\n'
        '[defaults.triage]\n'
        'enabled = true\n'
        'contract = "v2"\n'
        '[defaults.triage.routing]\n'
        'enabled = true\n'
        'mode = "first-match"\n'
        'strict_on_unavailable_route = false\n'
        'allow_model_escalation = false\n'
        'default_route = "codex-midi"\n'
        '[defaults.triage.routes.codex-midi]\n'
        'harness = "codex"\n'
        '[defaults.triage.routes.midtier-coder]\n'
        'harness = "codex"\n'
        '[profiles.demo]\n'
        'review.model = "old"\n',
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(
        ["set", "demo", "triage.routing.default_route", "codex-midi"]
    )
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["model"] == "old"
    assert reloaded["triage"]["routing"]["default_route"] == "codex-midi"
    assert "enabled" not in reloaded["triage"]["routing"]
    assert "mode" not in reloaded["triage"]["routing"]
    assert "strict_on_unavailable_route" not in reloaded["triage"]["routing"]
    assert "allow_model_escalation" not in reloaded["triage"]["routing"]
    assert "rule" not in reloaded["triage"]["routing"]
    assert "routes" not in reloaded["triage"]


def test_config_set_does_not_materialize_inherited_named_profile_fields(tmp_path, monkeypatch):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[profiles.demo]\n"
        "[profiles.demo.runtime]\n"
        'harness_executables = { codex = "/tmp/user-codex" }\n',
    )
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "review.timeout_seconds", "0.5"])
    assert code == 0

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["model"] == "old"
    assert reloaded["review"]["timeout_seconds"] == 0.5
    assert "runtime" not in reloaded


def test_config_set_rejects_unknown_route_with_inherited_user_defaults(tmp_path, monkeypatch):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[defaults]\n"
        "[defaults.triage]\n"
        "[defaults.triage.routing]\n"
        'default_route = "codex-midi"\n'
        "[defaults.triage.routes.codex-midi]\n"
        'harness = "codex"\n',
    )
    _write(
        tmp_path / ".revrem.toml",
        "[profiles.demo]\nreview.model = \"old\"\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main([
        "set",
        "demo",
        "triage.routing.default_route",
        "missing-route",
    ])
    assert code != 0

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert "triage" not in reloaded


def test_config_set_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    code = config_cmd.main(["set", "ghost", "review.model", "x"])
    assert code != 0
