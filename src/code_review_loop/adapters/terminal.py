"""Terminal adapter for ProgressReporter (REVREM-TASK-003 B4).

Implements ProgressReporter via the progress module (rich) and compact
text output. Only constructed when config.progress=True and style is
'rich' or 'compact'; the verbose path stays in the cli layer.
"""
from __future__ import annotations

from code_review_loop import progress as _progress


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
                from code_review_loop.loop import print_compact_progress
                print_compact_progress(phase, label, "rich progress unavailable; using compact output", head="warn: ")
            self._print_compact(phase, label, status, detail)
            return
        self._print_compact(phase, label, status, detail)

    def _print_compact(self, phase: str, label: str, status: str, detail: str) -> None:
        from code_review_loop.loop import print_compact_progress
        if detail:
            print_compact_progress(phase, label, detail, head=f"{status}: ")
        else:
            print_compact_progress(phase, label, status)
