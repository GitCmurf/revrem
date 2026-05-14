from __future__ import annotations

import tomllib

from code_review_loop._compat_jsonschema import Draft202012Validator, validate
from code_review_loop._compat_tomli_w import dumps


def test_local_tomli_w_round_trips_nested_tables():
    rendered = dumps(
        {
            "defaults": {
                "enabled": True,
                "labels": ["a", "b"],
                "nested": {"count": 2},
            }
        }
    )

    parsed = tomllib.loads(rendered)

    assert parsed["defaults"]["enabled"] is True
    assert parsed["defaults"]["labels"] == ["a", "b"]
    assert parsed["defaults"]["nested"]["count"] == 2


def test_local_tomli_w_escapes_newlines_in_basic_strings():
    rendered = dumps({"description": "first line\nsecond line"})

    parsed = tomllib.loads(rendered)

    assert parsed["description"] == "first line\nsecond line"


def test_local_tomli_w_escapes_control_characters_in_basic_strings():
    rendered = dumps({"description": "before\x1bafter"})

    parsed = tomllib.loads(rendered)

    assert parsed["description"] == "before\x1bafter"


def test_local_jsonschema_validator_handles_required_properties_and_constants():
    schema = {
        "type": "object",
        "required": ["schema_version"],
        "properties": {"schema_version": {"const": "1.0"}},
        "additionalProperties": False,
    }

    Draft202012Validator.check_schema(schema)
    validate({"schema_version": "1.0"}, schema)
    errors = list(Draft202012Validator(schema).iter_errors({"extra": True}))

    assert errors
