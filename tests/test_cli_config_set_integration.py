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


def test_config_set_preserves_shadowed_user_value(tmp_path, monkeypatch):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[profiles.demo]\n"
        "[profiles.demo.remediation]\n"
        'model = "user"\n',
    )
    _write(
        tmp_path / ".revrem.toml",
        "[defaults]\n"
        "[defaults.remediation]\n"
        'model = "repo"\n',
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "review.timeout_seconds", "0.5"])
    assert code == 0

    reloaded = profiles.load_profile_file(tmp_path / ".config" / "revrem" / "profiles.toml").raw_profiles["demo"]
    assert reloaded["remediation"]["model"] == "user"
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


def test_config_set_route_edit_materializes_required_default_route_rows(tmp_path, monkeypatch):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[defaults]\n"
        "[defaults.triage]\n"
        "[defaults.triage.routing]\n"
        'default_route = "codex-midi"\n'
        "[defaults.triage.routes.codex-midi]\n"
        'harness = "codex"\n'
        'model = "base-codex"\n'
        "[defaults.triage.routes.midtier-coder]\n"
        'harness = "codex"\n'
        'model = "base-open"\n',
    )
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "triage.routes.midtier-coder.model", "gpt-5.4-mini"])
    assert code == 0

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["triage"]["routing"]["default_route"] == "codex-midi"
    assert reloaded["triage"]["routes"]["midtier-coder"]["harness"] == "codex"
    assert reloaded["triage"]["routes"]["midtier-coder"]["model"] == "gpt-5.4-mini"
    assert reloaded["triage"]["routes"]["codex-midi"]["model"] == "base-codex"


def test_config_set_route_edit_materializes_inherited_fallback_rows(
    tmp_path, monkeypatch
):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[defaults]\n"
        "[defaults.triage]\n"
        "[defaults.triage.routing]\n"
        'default_route = "foo"\n'
        "[defaults.triage.routes.foo]\n"
        'harness = "codex"\n'
        'model = "base-foo"\n'
        'fallback = "bar"\n'
        "[defaults.triage.routes.bar]\n"
        'harness = "codex"\n'
        'model = "base-bar"\n',
    )
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "triage.routes.foo.model", "gpt-5.4-mini"])
    assert code == 0

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["triage"]["routing"]["default_route"] == "foo"
    assert reloaded["triage"]["routes"]["foo"]["fallback"] == "bar"
    assert reloaded["triage"]["routes"]["foo"]["model"] == "gpt-5.4-mini"
    assert reloaded["triage"]["routes"]["bar"]["harness"] == "codex"
    assert reloaded["triage"]["routes"]["bar"]["model"] == "base-bar"


def test_config_set_route_edit_uses_inherited_v2_contract_context(tmp_path, monkeypatch):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[defaults]\n"
        "[defaults.triage]\n"
        "enabled = true\n"
        'contract = "v2"\n'
        "[defaults.triage.routing]\n"
        'default_route = "codex-midi"\n'
        "enabled = true\n"
        "strict_on_unavailable_route = false\n"
        "allow_model_escalation = false\n"
        "[defaults.triage.routes.codex-midi]\n"
        'harness = "codex"\n'
        'model = "base-codex"\n',
    )
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "triage.routes.codex-midi.model", "gpt-5.4-mini"])
    assert code == 0

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["triage"]["routing"]["default_route"] == "codex-midi"
    assert reloaded["triage"]["routes"]["codex-midi"]["model"] == "gpt-5.4-mini"
    assert profiles.resolve_profile("demo", cwd=tmp_path, home=tmp_path).triage.contract == "v2"


def test_config_set_routing_default_route_preserves_owner_routing_metadata_over_project_default(
    tmp_path, monkeypatch
):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[profiles.demo]\n"
        "[profiles.demo.triage]\n"
        "[profiles.demo.triage.routing]\n"
        "strict_on_unavailable_route = true\n",
    )
    _write(
        tmp_path / ".revrem.toml",
        '[defaults]\n'
        '[defaults.triage]\n'
        '[defaults.triage.routing]\n'
        'default_route = "codex-midi"\n'
        'strict_on_unavailable_route = false\n'
        '[defaults.triage.routes.codex-midi]\n'
        'harness = "codex"\n'
        '[defaults.triage.routes.frontier]\n'
        'harness = "codex"\n',
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(
        ["set", "demo", "triage.routing.default_route", "frontier"]
    )
    assert code == 0

    reloaded = profiles.load_profile_file(
        tmp_path / ".config" / "revrem" / "profiles.toml"
    ).raw_profiles["demo"]
    assert reloaded["triage"]["routing"]["default_route"] == "frontier"
    assert reloaded["triage"]["routing"]["strict_on_unavailable_route"] is True


def test_config_set_routing_enabled_edit_uses_inherited_v2_contract_context(tmp_path, monkeypatch):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[defaults]\n"
        "[defaults.triage]\n"
        "enabled = true\n"
        'contract = "v2"\n'
        "[defaults.triage.routing]\n"
        'default_route = "codex-midi"\n'
        "enabled = true\n"
        "strict_on_unavailable_route = false\n"
        "allow_model_escalation = false\n"
        "[defaults.triage.routes.codex-midi]\n"
        'harness = "codex"\n',
    )
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "triage.routing.enabled", "true"])
    assert code == 0

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    resolved = profiles.resolve_profile("demo", cwd=tmp_path, home=tmp_path)
    assert reloaded["triage"]["routing"]["enabled"] is True
    assert reloaded["triage"]["routing"]["default_route"] == "codex-midi"
    assert reloaded["triage"]["routes"]["codex-midi"]["harness"] == "codex"
    assert resolved.triage.contract == "v2"


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
