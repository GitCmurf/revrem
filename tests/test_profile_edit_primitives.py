from __future__ import annotations

import pytest

from code_review_loop import profiles


def test_deep_set_raw_sets_nested_scalar_and_copies():
    raw = {"review": {"model": "old"}}
    out = profiles.deep_set_raw(raw, "review.model", "gpt-5.5")
    assert out["review"]["model"] == "gpt-5.5"
    assert raw["review"]["model"] == "old"  # input not mutated


def test_deep_set_raw_creates_missing_intermediate_tables():
    out = profiles.deep_set_raw({}, "commit.message_model", "haiku-4.5")
    assert out == {"commit": {"message_model": "haiku-4.5"}}


def test_deep_set_raw_coerces_int_and_bool():
    out = profiles.deep_set_raw({}, "pipeline.max_iterations", "11")
    assert out["pipeline"]["max_iterations"] == 11
    assert isinstance(out["pipeline"]["max_iterations"], int)

    out2 = profiles.deep_set_raw({}, "triage.enabled", "false")
    assert out2["triage"]["enabled"] is False

    out3 = profiles.deep_set_raw({}, "runtime.inner_check_retries", "2")
    assert out3["runtime"]["inner_check_retries"] == 2


def test_deep_set_raw_coerces_timeout_float():
    out = profiles.deep_set_raw({}, "review.timeout_seconds", "0.5")
    assert out["review"]["timeout_seconds"] == 0.5
    assert isinstance(out["review"]["timeout_seconds"], float)


def test_deep_set_raw_coerces_additional_numeric_fields():
    out = profiles.deep_set_raw({}, "pipeline.check_timeout_seconds", "42")
    assert out["pipeline"]["check_timeout_seconds"] == 42.0
    assert isinstance(out["pipeline"]["check_timeout_seconds"], float)

    out2 = profiles.deep_set_raw({}, "budgets.max_tokens", "500")
    assert out2["budgets"]["max_tokens"] == 500
    assert isinstance(out2["budgets"]["max_tokens"], int)

    out3 = profiles.deep_set_raw({}, "runtime.provider_retry_attempts", "3")
    assert out3["runtime"]["provider_retry_attempts"] == 3
    assert isinstance(out3["runtime"]["provider_retry_attempts"], int)


def test_deep_set_raw_routing_default_route_stays_string():
    # default_route is a string; only strict_*/allow_* under routing are bools.
    out = profiles.deep_set_raw({}, "triage.routing.default_route", "remediation")
    assert out["triage"]["routing"]["default_route"] == "remediation"

    out2 = profiles.deep_set_raw({}, "triage.routing.allow_model_escalation", "off")
    assert out2["triage"]["routing"]["allow_model_escalation"] is False


def test_deep_set_raw_rejects_bad_int():
    with pytest.raises(ValueError):
        profiles.deep_set_raw({}, "pipeline.max_iterations", "lots")


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_profile_owner_path_prefers_project(tmp_path):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "x"\n')
    got = profiles.profile_owner_path("demo", cwd=tmp_path, home=tmp_path)
    assert got == profiles.project_config_path(tmp_path)


def test_profile_owner_path_falls_back_to_user(tmp_path):
    user = tmp_path / ".config" / "revrem" / "profiles.toml"
    _write(user, '[profiles.demo]\nreview.model = "x"\n')
    got = profiles.profile_owner_path("demo", cwd=tmp_path, home=tmp_path)
    assert got == profiles.user_config_path(tmp_path)


def test_profile_owner_path_unknown_requires_allow_new(tmp_path):
    with pytest.raises(FileNotFoundError):
        profiles.profile_owner_path("nope", cwd=tmp_path, home=tmp_path)
    got = profiles.profile_owner_path("nope", cwd=tmp_path, home=tmp_path, allow_new=True)
    assert got == profiles.user_config_path(tmp_path)


def test_profile_owner_path_rejects_builtin(tmp_path):
    name = next(p.name for p in profiles.list_profiles(cwd=tmp_path, include_builtins=True)
                if profiles.is_builtin_profile(p.name))
    with pytest.raises(RuntimeError):
        profiles.profile_owner_path(name, cwd=tmp_path, home=tmp_path)


def test_save_profile_raw_round_trips_minimal_toml(tmp_path):
    _write(tmp_path / ".revrem.toml",
           '[profiles.demo]\nreview.model = "old"\npipeline.max_iterations = 3\n')
    raw = dict(profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"])
    raw = profiles.deep_set_raw(raw, "review.model", "gpt-5.5")
    path = profiles.save_profile_raw("demo", raw, cwd=tmp_path, home=tmp_path)
    assert path == profiles.project_config_path(tmp_path)

    reloaded = profiles.load_profile_file(path).raw_profiles["demo"]
    assert reloaded["review"]["model"] == "gpt-5.5"
    assert reloaded["pipeline"]["max_iterations"] == 3  # preserved
    assert "remediation" not in reloaded  # stays minimal, no resolved-default bloat


def test_save_profile_raw_validates(tmp_path):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    bad = profiles.deep_set_raw({}, "pipeline.max_iterations", "5")
    bad["review"] = {"model": 123}  # wrong type for a model
    with pytest.raises(ValueError):
        profiles.save_profile_raw("demo", bad, cwd=tmp_path, home=tmp_path)


def test_save_profile_raw_preserves_sibling_profiles(tmp_path):
    # The real .revrem.toml holds multiple project profiles; editing one must
    # not drop the others (data-loss guard).
    _write(
        tmp_path / ".revrem.toml",
        '[profiles.default]\nreview.model = "old"\n\n'
        '[profiles.dogfood]\nreview.model = "keep"\npipeline.max_iterations = 5\n',
    )
    raw = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["default"]
    raw = profiles.deep_set_raw(raw, "review.model", "gpt-5.5")
    profiles.save_profile_raw("default", raw, cwd=tmp_path, home=tmp_path)

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles
    assert reloaded["default"]["review"]["model"] == "gpt-5.5"
    assert reloaded["dogfood"]["review"]["model"] == "keep"
    assert reloaded["dogfood"]["pipeline"]["max_iterations"] == 5


def test_set_profile_field_persists_single_field(tmp_path):
    _write(tmp_path / ".revrem.toml",
           '[profiles.demo]\nreview.model = "old"\npipeline.max_iterations = 3\n')
    profiles.set_profile_field("demo", "pipeline.max_iterations", "11",
                               cwd=tmp_path, home=tmp_path)
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["pipeline"]["max_iterations"] == 11
    assert reloaded["review"]["model"] == "old"


def test_set_profile_field_preserves_inherited_defaults(tmp_path):
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

    profiles.set_profile_field(
        "demo", "review.timeout_seconds", "0.5", cwd=tmp_path, home=tmp_path
    )
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["model"] == "old"
    assert reloaded["review"]["timeout_seconds"] == 0.5
    assert "triage" not in reloaded


def test_set_profile_field_validates_against_inherited_project_defaults(tmp_path):
    _write(
        tmp_path / ".config" / "revrem" / "profiles.toml",
        "[defaults]\n"
        "[defaults.triage]\n"
        "[defaults.triage.routing]\n"
        'default_route = "codex-midi"\n'
        "[defaults.triage.routes.codex-midi]\n"
        'harness = "codex"\n',
    )
    _write(tmp_path / ".revrem.toml", "[profiles.demo]\nreview.model = \"old\"\n")

    with pytest.raises(
        ValueError,
        match="triage.routing.default_route refers to unknown route: missing-route",
    ):
        profiles.set_profile_field(
            "demo",
            "triage.routing.default_route",
            "missing-route",
            cwd=tmp_path,
            home=tmp_path,
        )

    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["model"] == "old"
    assert "triage" not in reloaded


def test_set_profile_field_persists_float_timeout(tmp_path):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    profiles.set_profile_field(
        "demo", "review.timeout_seconds", "0.5", cwd=tmp_path, home=tmp_path
    )
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["timeout_seconds"] == 0.5


def test_set_profile_field_unknown_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        profiles.set_profile_field("ghost", "review.model", "x", cwd=tmp_path, home=tmp_path)


def test_set_profile_field_coerces_boolean_fields(tmp_path):
    _write(tmp_path / ".revrem.toml", "[profiles.demo]\n")
    profiles.set_profile_field("demo", "output.no_tty", "off", cwd=tmp_path, home=tmp_path)
    profiles.set_profile_field("demo", "runtime.full_auto", "on", cwd=tmp_path, home=tmp_path)
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["output"]["no_tty"] is False
    assert reloaded["runtime"]["full_auto"] is True


# ── Regression tests for REVREM-PLAN-009 final review ────────────────────────

def test_profile_owner_path_local_shadows_builtin(tmp_path):
    """A LOCAL profile whose name collides with a builtin must remain editable.

    Fix 1 regression lock: profile_owner_path must check project/user files
    BEFORE raising for a builtin name, so a shadowing local profile wins.
    """
    name = next(
        p.name
        for p in profiles.list_profiles(cwd=tmp_path, include_builtins=True)
        if profiles.is_builtin_profile(p.name)
    )
    _write(tmp_path / ".revrem.toml", f'[profiles.{name}]\nreview.model = "x"\n')
    # Must NOT raise; must return the project config path, not the user path
    got = profiles.profile_owner_path(name, cwd=tmp_path, home=tmp_path)
    assert got == profiles.project_config_path(tmp_path)


def test_deep_set_raw_coerces_allow_model_deescalation():
    """allow_model_deescalation must be coerced to bool by deep_set_raw.

    Fix 2 regression lock: .allow_model_deescalation must appear in
    _BOOL_SUFFIXES so string "off" becomes False, not the string "off".
    """
    result = profiles.deep_set_raw({}, "triage.routing.allow_model_deescalation", "off")
    assert result["triage"]["routing"]["allow_model_deescalation"] is False
