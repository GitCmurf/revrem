"""Minimal TOML writer used when the external `tomli-w` package is unavailable."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def dumps(data: Mapping[str, object]) -> str:
    lines: list[str] = []
    _write_table(lines, (), data)
    return "\n".join(lines)


def _write_table(lines: list[str], prefix: tuple[str, ...], table: Mapping[str, object]) -> None:
    scalars: list[tuple[str, object]] = []
    nested: list[tuple[str, Mapping[str, object]]] = []
    arrays: list[tuple[str, Sequence[object]]] = []

    for key, value in table.items():
        if isinstance(value, Mapping):
            nested.append((key, value))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            arrays.append((key, value))
        else:
            scalars.append((key, value))

    # Implicit table: a node with only nested sub-tables needs no [header] line;
    # its children emit their own fully-qualified [a.b.c] paths.
    container = not scalars and not arrays and nested
    if prefix and not container:
        lines.append(f"[{'.'.join(_format_key(part) for part in prefix)}]")

    for key, value in scalars:
        lines.append(f"{_format_key(key)} = {_format_value(value)}")

    for key, value in arrays:
        lines.append(f"{_format_key(key)} = {_format_array(value)}")

    for key, value in nested:
        if lines and (scalars or arrays or (prefix and not container)):
            lines.append("")
        _write_table(lines, (*prefix, key), value)


def _format_key(key: str) -> str:
    if key and all(_is_bare_key_char(ch) for ch in key):
        return key
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _is_bare_key_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch in {"-", "_"})


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if value is None:
        raise TypeError("TOML does not support null/None values")
    if isinstance(value, str):
        escaped = _escape_basic_string(value)
        return f'"{escaped}"'
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")


def _format_array(values: Sequence[object]) -> str:
    return "[" + ", ".join(_format_value(value) for value in values) + "]"


def _escape_basic_string(value: str) -> str:
    parts: list[str] = []
    for char in value:
        codepoint = ord(char)
        if char == "\\":
            parts.append("\\\\")
        elif char == '"':
            parts.append('\\"')
        elif char == "\b":
            parts.append("\\b")
        elif char == "\t":
            parts.append("\\t")
        elif char == "\n":
            parts.append("\\n")
        elif char == "\f":
            parts.append("\\f")
        elif char == "\r":
            parts.append("\\r")
        elif codepoint < 0x20 or codepoint == 0x7F:
            parts.append(f"\\u{codepoint:04x}")
        else:
            parts.append(char)
    return "".join(parts)
