"""Progress rendering helpers for RevRem."""

from __future__ import annotations

import sys
from datetime import datetime


def rich_available() -> bool:
    try:
        import rich.console  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def _console_and_text():
    try:
        from rich.console import Console  # type: ignore[import-not-found]
        from rich.text import Text  # type: ignore[import-not-found]
    except ImportError:
        return None
    return Console(file=sys.stderr, force_terminal=sys.stderr.isatty()), Text


def _styled_text(*parts: tuple[str, str | None]):
    loaded = _console_and_text()
    if loaded is None:
        return None
    console, text_type = loaded
    text = text_type()
    for value, style in parts:
        text.append(value, style=style)
    return console, text


def _timestamp_part() -> tuple[str, str]:
    return datetime.now().strftime("%H:%M:%S"), "dim"


def print_rich_event(phase: str, label: str, status: str, detail: str = "") -> bool:
    rendered = _styled_text(
        _timestamp_part(),
        (" ", None),
        (phase, "bold green"),
        (" ", None),
        (label, "cyan"),
        (" ", None),
        (status, "green"),
        (f": {detail}" if detail else "", None),
    )
    if rendered is None:
        return False
    console, text = rendered
    console.print(text)
    return True


def print_rich_message(phase: str, label: str, text: str, *, head: str = "") -> bool:
    rendered = _styled_text(
        _timestamp_part(),
        (" ", None),
        (phase, "bold green"),
        (" ", None),
        (label, "cyan"),
        (" ", None),
        (head, "yellow" if head else None),
        (text, None),
    )
    if rendered is None:
        return False
    console, rendered_text = rendered
    console.print(rendered_text)
    return True


def print_rich_continuation(phase: str, label: str, text: str, *, indent: int = 2) -> bool:
    rendered = _styled_text(
        _timestamp_part(),
        (" ", None),
        (f"{phase} {label}", "dim"),
        (" " * (indent + 1), None),
        (text, None),
    )
    if rendered is None:
        return False
    console, rendered_text = rendered
    console.print(rendered_text)
    return True
