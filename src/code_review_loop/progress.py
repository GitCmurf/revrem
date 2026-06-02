"""Progress rendering helpers for RevRem."""

from __future__ import annotations

import sys
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from typing import Any

_ACTIVE_LIVE: Any | None = None
_ACTIVE_LIVE_LINES: deque[Any] | None = None
RICH_LIVE_MAX_LINES = 7
RICH_TEXT_MAX_CHARS = 140


def rich_available() -> bool:
    try:
        import rich.console  # type: ignore[import-not-found]  # noqa: F401
        import rich.live  # type: ignore[import-not-found]  # noqa: F401
        import rich.panel  # type: ignore[import-not-found]  # noqa: F401
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


@contextmanager
def rich_live_progress(enabled: bool):
    """Render Rich progress in one in-place panel when Rich is available."""
    global _ACTIVE_LIVE, _ACTIVE_LIVE_LINES
    if not enabled:
        yield False
        return
    try:
        from rich.console import Console, Group  # type: ignore[import-not-found]
        from rich.live import Live  # type: ignore[import-not-found]
        from rich.panel import Panel  # type: ignore[import-not-found]
    except ImportError:
        yield False
        return

    console = Console(file=sys.stderr, force_terminal=sys.stderr.isatty())
    lines: deque[Any] = deque(maxlen=RICH_LIVE_MAX_LINES)
    live = Live(
        Panel("Starting RevRem...", title="RevRem", border_style="green"),
        console=console,
        refresh_per_second=4,
        transient=False,
        vertical_overflow="ellipsis",
    )
    previous_live = _ACTIVE_LIVE
    previous_lines = _ACTIVE_LIVE_LINES
    _ACTIVE_LIVE = (live, Panel, Group)
    _ACTIVE_LIVE_LINES = lines
    try:
        with live:
            yield True
    finally:
        _ACTIVE_LIVE = previous_live
        _ACTIVE_LIVE_LINES = previous_lines


def _update_live(text: Any) -> bool:
    if _ACTIVE_LIVE is None or _ACTIVE_LIVE_LINES is None:
        return False
    live, panel_type, group_type = _ACTIVE_LIVE
    _ACTIVE_LIVE_LINES.append(text)
    live.update(
        panel_type(
            group_type(*_ACTIVE_LIVE_LINES), title="RevRem", border_style="green"
        )
    )
    return True


def _clip(value: str) -> str:
    value = " ".join(value.split())
    if len(value) <= RICH_TEXT_MAX_CHARS:
        return value
    return f"{value[: RICH_TEXT_MAX_CHARS - 1]}…"


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
        (f": {_clip(detail)}" if detail else "", None),
    )
    if rendered is None:
        return False
    console, text = rendered
    if _update_live(text):
        return True
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
        (_clip(text), None),
    )
    if rendered is None:
        return False
    console, rendered_text = rendered
    if _update_live(rendered_text):
        return True
    console.print(rendered_text)
    return True


def print_rich_continuation(
    phase: str, label: str, text: str, *, indent: int = 2
) -> bool:
    rendered = _styled_text(
        _timestamp_part(),
        (" ", None),
        (f"{phase} {label}", "dim"),
        (" " * (indent + 1), None),
        (_clip(text), None),
    )
    if rendered is None:
        return False
    console, rendered_text = rendered
    if _update_live(rendered_text):
        return True
    console.print(rendered_text)
    return True
