"""Clock seam for deterministic time (REVREM-TASK-003 Contract C6).

Pre-core placement: this module lives at the package root pending the ``core/``
package introduced in Wave B0, which re-homes ``Clock`` as a declared port. The
default adapter reads the real clocks; tests inject a deterministic fake so the
review loop's machine-contract output (summary JSON, ``events.jsonl``) can be
pinned by the golden-master suite (A2).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    """Default adapter: reads the real wall and monotonic clocks."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


SYSTEM_CLOCK: Clock = SystemClock()


def utc_iso(moment: datetime) -> str:
    """Render an aware datetime as the canonical Zulu ISO-8601 string."""
    return moment.isoformat().replace("+00:00", "Z")
