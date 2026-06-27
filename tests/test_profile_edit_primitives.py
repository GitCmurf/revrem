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
