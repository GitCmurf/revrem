from __future__ import annotations

import tomllib

import jsonschema
import tomli_w
from jsonschema.validators import Draft202012Validator


def test_local_tomli_w_round_trips_nested_tables():
    rendered = tomli_w.dumps(
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


def test_local_jsonschema_validator_handles_required_properties_and_constants():
    schema = {
        "type": "object",
        "required": ["schema_version"],
        "properties": {"schema_version": {"const": "1.0"}},
        "additionalProperties": False,
    }

    Draft202012Validator.check_schema(schema)
    jsonschema.validate({"schema_version": "1.0"}, schema)
    errors = list(Draft202012Validator(schema).iter_errors({"extra": True}))

    assert errors
