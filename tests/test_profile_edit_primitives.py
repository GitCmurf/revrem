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
