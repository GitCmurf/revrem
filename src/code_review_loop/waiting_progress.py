"""Context-local waiting progress callbacks for subprocess-backed phases."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

WAITING_PROGRESS_INTERVAL_SECONDS = 300.0
_WAITING_PROGRESS_REPORTER: ContextVar[Callable[[float], None] | None] = ContextVar(
    "revrem_waiting_progress_reporter",
    default=None,
)


@contextmanager
def subprocess_waiting_reporter(
    reporter: Callable[[float], None] | None,
) -> Iterator[None]:
    token = _WAITING_PROGRESS_REPORTER.set(reporter)
    try:
        yield
    finally:
        _WAITING_PROGRESS_REPORTER.reset(token)


def current_reporter() -> Callable[[float], None] | None:
    return _WAITING_PROGRESS_REPORTER.get()
