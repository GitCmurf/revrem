"""Minimal local JSON Schema support for the repo test suite."""

from __future__ import annotations

from collections.abc import Iterator


def validate(instance, schema) -> None:
    Draft202012Validator(schema).validate(instance)


class Draft202012Validator:
    def __init__(self, schema):
        self.schema = schema

    @classmethod
    def check_schema(cls, schema) -> None:
        if not isinstance(schema, dict):
            raise TypeError("schema must be a mapping")

    def validate(self, instance) -> None:
        errors = list(self.iter_errors(instance))
        if errors:
            raise ValueError(errors[0])

    def iter_errors(self, instance) -> Iterator[str]:
        yield from _validate(instance, self.schema, path="$")


def _validate(instance, schema, *, path: str) -> Iterator[str]:
    if not isinstance(schema, dict):
        return

    expected = schema.get("type")
    if expected is not None and not _matches_type(instance, expected):
        yield f"{path}: expected type {expected!r}"
        return

    if "const" in schema and instance != schema["const"]:
        yield f"{path}: expected const {schema['const']!r}"
        return

    if "enum" in schema and instance not in schema["enum"]:
        yield f"{path}: expected one of {schema['enum']!r}"
        return

    if isinstance(instance, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(instance) < min_length:
            yield f"{path}: string shorter than {min_length}"
        return

    if isinstance(instance, list):
        items_schema = schema.get("items")
        if items_schema is not None:
            for index, item in enumerate(instance):
                yield from _validate(item, items_schema, path=f"{path}[{index}]")
        return

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)

        for key in required:
            if key not in instance:
                yield f"{path}: missing required property {key!r}"

        for key, value in instance.items():
            if key in properties:
                yield from _validate(value, properties[key], path=f"{path}.{key}")
            elif additional is False:
                yield f"{path}: unexpected property {key!r}"


def _matches_type(instance, expected) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(instance, item) for item in expected)
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    return True
