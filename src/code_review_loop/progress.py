"""Progress rendering helpers for RevRem."""

from __future__ import annotations

import sys


def rich_available() -> bool:
    try:
        import rich.console  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def print_rich_event(phase: str, label: str, status: str, detail: str = "") -> bool:
    try:
        from rich.console import Console  # type: ignore[import-not-found]
    except ImportError:
        return False
    console = Console(file=sys.stderr, force_terminal=sys.stderr.isatty())
    title = f"[bold]{phase}[/bold] [cyan]{label}[/cyan] [green]{status}[/green]"
    console.print(f"{title}: {detail}" if detail else title)
    return True


def print_rich_message(phase: str, label: str, text: str, *, head: str = "") -> bool:
    try:
        from rich.console import Console  # type: ignore[import-not-found]
    except ImportError:
        return False
    console = Console(file=sys.stderr, force_terminal=sys.stderr.isatty())
    prefix = f"[bold]{phase}[/bold] [cyan]{label}[/cyan]"
    console.print(f"{prefix} {head}{text}")
    return True


def print_rich_continuation(phase: str, label: str, text: str, *, indent: int = 2) -> bool:
    try:
        from rich.console import Console  # type: ignore[import-not-found]
    except ImportError:
        return False
    console = Console(file=sys.stderr, force_terminal=sys.stderr.isatty())
    console.print(f"[dim]{phase} {label}[/dim] {' ' * indent}{text}")
    return True
