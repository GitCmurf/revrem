"""Minimal local JSON Schema support for the repo test suite."""

from __future__ import annotations

from .validators import Draft202012Validator


def validate(instance, schema) -> None:
    Draft202012Validator(schema).validate(instance)
