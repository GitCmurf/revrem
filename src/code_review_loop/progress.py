"""Progress rendering helpers for RevRem."""

from __future__ import annotations

import os
import sys
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from typing import Any

_ACTIVE_LIVE: Any | None = None
_ACTIVE_LIVE_LINES: deque[Any] | None = None
#: Latched by :func:`rich_live_progress` when a run enters headless mode
#: (``--no-tty``). The fallback consoles built by ``_console_and_text`` for the
#: ``print_rich_*`` helpers do not receive ``no_tty`` directly, so they consult
#: this latch to stay ANSI-free under ``--no-tty`` even when no live panel is
#: active. This is a one-way floor: once forced off, it stays off for the run.
_NO_TTY_FORCED: bool = False
RICH_LIVE_MAX_LINES = 7
RICH_TEXT_MAX_CHARS = 140
#: Rich style applied to each " · "-separated value in a structured start
#: detail line. Index ``i`` styles value ``i``. Indices past the end render
#: unstyled, so adding fields (e.g. a new ``route=`` segment) does not drop
#: styling on the existing values.
RICH_DETAIL_STYLES: tuple[str | None, ...] = (
    "bold",
    "magenta",
    "cyan",
    "yellow",
    "yellow",
    "blue",
    "dim",
)


def rich_available() -> bool:
    try:
        import rich.console  # type: ignore[import-not-found]  # noqa: F401
        import rich.live  # type: ignore[import-not-found]  # noqa: F401
        import rich.panel  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def force_terminal(*, no_tty: bool = False) -> bool:
    """Whether Rich should emit ANSI escape sequences for the live panel.

    The single gate for headless suppression (Contract via PLAN-005 T3): Rich
    output, progress spinners, and terminal-title writes are suppressed when
    either an explicit ``--no-tty`` override is set, the run latched headless
    mode via :func:`rich_live_progress`, or the ``CI`` environment variable is
    present (set automatically by GitHub Actions, CircleCI, Travis, Jenkins,
    and most other providers). A standard CI run therefore requires no
    RevRem-specific flags.
    """
    return (
        sys.stderr.isatty()
        and not os.environ.get("CI")
        and not no_tty
        and not _NO_TTY_FORCED
    )


def _console_and_text(*, no_tty: bool = False):
    try:
        from rich.console import Console  # type: ignore[import-not-found]
        from rich.text import Text  # type: ignore[import-not-found]
    except ImportError:
        return None
    return Console(file=sys.stderr, force_terminal=force_terminal(no_tty=no_tty)), Text


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
def rich_live_progress(enabled: bool, *, no_tty: bool = False):
    """Render Rich progress in one in-place panel when Rich is available.

    ``no_tty`` (and the ``CI`` env var) suppress ANSI via :func:`force_terminal`
    so headless runs emit no escape sequences on stderr. Entering with
    ``no_tty`` also latches the module-level headless flag so the fallback
    consoles built by the ``print_rich_*`` helpers (which do not receive
    ``no_tty``) honor ``--no-tty`` even when their text does not route to the
    live panel. The latch is scoped to this context and restored on exit so
    test runs remain isolated.
    """
    global _ACTIVE_LIVE, _ACTIVE_LIVE_LINES, _NO_TTY_FORCED
    # Latch headless mode for the whole context *before* any early return, so the
    # fallback consoles built by print_rich_* (which take no no_tty arg) stay
    # ANSI-free even when the live panel is disabled — i.e. compact progress
    # (progress_style != "rich"), which enters here with enabled=False. Setting
    # the latch only on the enabled path left --no-tty broken for its documented
    # out-of-CI use in compact mode. One-way floor, restored on exit.
    previous_no_tty_forced = _NO_TTY_FORCED
    _NO_TTY_FORCED = _NO_TTY_FORCED or no_tty
    try:
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

        console = Console(file=sys.stderr, force_terminal=force_terminal(no_tty=no_tty))
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
    finally:
        _NO_TTY_FORCED = previous_no_tty_forced


def _update_live(text: Any) -> bool:
    if _ACTIVE_LIVE is None or _ACTIVE_LIVE_LINES is None:
        return False
    live, panel_type, group_type = _ACTIVE_LIVE
    _ACTIVE_LIVE_LINES.append(text)
    live.update(panel_type(group_type(*_ACTIVE_LIVE_LINES), title="RevRem", border_style="green"))
    return True


def _clip(value: str) -> str:
    value = " ".join(value.split())
    if len(value) <= RICH_TEXT_MAX_CHARS:
        return value
    return f"{value[: RICH_TEXT_MAX_CHARS - 1]}…"


def _timestamp_part() -> tuple[str, str]:
    return datetime.now().strftime("%H:%M:%S"), "dim"


def _detail_parts(status: str, detail: str) -> list[tuple[str, str | None]]:
    if not detail:
        return []
    clipped = _clip(detail)
    if status != "start" or " · " not in clipped:
        return [(f": {clipped}", None)]
    values = clipped.split(" · ")
    parts: list[tuple[str, str | None]] = [(": ", None)]
    for index, value in enumerate(values):
        if index:
            parts.append((" · ", "dim"))
        style = RICH_DETAIL_STYLES[index] if index < len(RICH_DETAIL_STYLES) else None
        parts.append((value, style))
    return parts


def print_rich_event(phase: str, label: str, status: str, detail: str = "") -> bool:
    rendered = _styled_text(
        _timestamp_part(),
        (" ", None),
        (phase, "bold green"),
        (" ", None),
        (label, "cyan"),
        (" ", None),
        (status, "green"),
        *_detail_parts(status, detail),
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


def print_rich_continuation(phase: str, label: str, text: str, *, indent: int = 2) -> bool:
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
