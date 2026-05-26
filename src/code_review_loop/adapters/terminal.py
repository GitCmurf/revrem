"""Terminal adapters for progress and terminal-state control (REVREM-TASK-003 B4).

Implements ProgressReporter via the progress module (rich) and compact
text output. Only constructed when config.progress=True and style is
'rich' or 'compact'; the verbose path stays in the cli layer.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from code_review_loop import progress as _progress
from code_review_loop.config import LoopConfig

# xterm-compatible title-stack controls use CSI, not OSC.
TERMINAL_TITLE_SAVE = "\033[22;0t"
TERMINAL_TITLE_RESTORE = "\033[23;0t"
TERMINAL_TITLE_REFRESH_SECONDS = 1.0
CURSOR_SHOW = "\033[?25h"

_CURRENT_TERMINAL_TITLE_SEQUENCE: str | None = None
_TERMINAL_TITLE_PREFER_TTY: bool | None = False


def terminal_title_supported(config: LoopConfig) -> bool:
    return config.terminal_title and (sys.stderr.isatty() or (os.name != "nt" and Path("/dev/tty").exists()))


def sanitize_terminal_title(value: str) -> str:
    return value.replace("\033", "").replace("\007", "").replace("\n", " ").replace("\r", " ")


def write_terminal_control(sequence: str, *, prefer_tty: bool = False) -> None:
    if prefer_tty and write_terminal_control_to_tty(sequence):
        return
    if sys.stderr.isatty():
        sys.stderr.write(sequence)
        sys.stderr.flush()
    elif not prefer_tty:
        write_terminal_control_to_tty(sequence)


def write_terminal_control_to_tty(sequence: str) -> bool:
    if os.name == "nt":
        return False
    try:
        with Path("/dev/tty").open("w", encoding="utf-8") as tty:
            tty.write(sequence)
            tty.flush()
            return True
    except OSError:
        return False


def restore_terminal_display() -> None:
    """Best-effort terminal recovery for interrupted Rich/title sessions."""
    write_terminal_control(CURSOR_SHOW, prefer_tty=bool(_TERMINAL_TITLE_PREFER_TTY))


def set_terminal_title(config: LoopConfig, title: str) -> None:
    global _CURRENT_TERMINAL_TITLE_SEQUENCE
    if not terminal_title_supported(config):
        return
    if config.progress_style == "rich":
        return
    safe_title = sanitize_terminal_title(title)
    # OSC 0 sets icon + window title. OSC 2 explicitly sets the window/tab
    # title. Emitting both is harmless and covers more terminal emulators.
    _CURRENT_TERMINAL_TITLE_SEQUENCE = f"\033]0;{safe_title}\007\033]2;{safe_title}\007"
    write_terminal_control(_CURRENT_TERMINAL_TITLE_SEQUENCE)


def refresh_terminal_title(*, prefer_tty: bool | None = None) -> None:
    if _CURRENT_TERMINAL_TITLE_SEQUENCE:
        if prefer_tty is None:
            prefer_tty = _TERMINAL_TITLE_PREFER_TTY
        if prefer_tty is None:
            return
        write_terminal_control(_CURRENT_TERMINAL_TITLE_SEQUENCE, prefer_tty=prefer_tty)


@contextmanager
def terminal_title_context(config: LoopConfig) -> Iterator[None]:
    global _CURRENT_TERMINAL_TITLE_SEQUENCE, _TERMINAL_TITLE_PREFER_TTY
    if not terminal_title_supported(config):
        yield
        return
    previous_prefer_tty = _TERMINAL_TITLE_PREFER_TTY
    _TERMINAL_TITLE_PREFER_TTY = None if config.progress_style == "rich" else False
    # There is no reliable cross-terminal way to read the current title. Xterm-
    # compatible terminals support a title stack, which gives the desired
    # save/restore behavior without querying terminal state.
    write_terminal_control(TERMINAL_TITLE_SAVE, prefer_tty=bool(_TERMINAL_TITLE_PREFER_TTY))
    try:
        yield
    finally:
        _CURRENT_TERMINAL_TITLE_SEQUENCE = None
        restore_terminal_display()
        write_terminal_control(TERMINAL_TITLE_RESTORE, prefer_tty=bool(_TERMINAL_TITLE_PREFER_TTY))
        _TERMINAL_TITLE_PREFER_TTY = previous_prefer_tty


def set_phase_terminal_title(config: LoopConfig, phase: str, label: str) -> None:
    if phase == "review":
        prefix = "rev"
    elif phase == "remediate":
        prefix = "rem"
    else:
        return
    from code_review_loop.adapters.phase_support import terminal_iteration_label

    set_terminal_title(config, f"{prefix} {terminal_iteration_label(label, config.max_iterations)} RevRem")


class TerminalProgressReporter:
    """ProgressReporter that renders to the terminal.

    Handles both rich (via Rich library) and compact (plain text) styles.
    Instance-level warn-once latch prevents repeated 'rich unavailable' messages
    within a single run.
    """

    def __init__(self, style: str) -> None:
        self._style = style  # "rich" or "compact"
        self._warned = False

    def phase(self, phase: str, label: str, status: str, detail: str = "") -> None:
        if self._style == "rich":
            if _progress.print_rich_event(phase, label, status, detail):
                return
            if not self._warned:
                self._warned = True
                from code_review_loop.adapters.phase_support import print_compact_progress
                print_compact_progress(phase, label, "rich progress unavailable; using compact output", head="warn: ")
            self._print_compact(phase, label, status, detail)
            return
        self._print_compact(phase, label, status, detail)

    def _print_compact(self, phase: str, label: str, status: str, detail: str) -> None:
        from code_review_loop.adapters.phase_support import print_compact_progress
        if detail:
            print_compact_progress(phase, label, detail, head=f"{status}: ")
        else:
            print_compact_progress(phase, label, status)
