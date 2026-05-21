"""Run-scoped identifier seam (REVREM-TASK-003 Contract C6).

Pre-core placement (see ``clock.py``): re-homed as a port in Wave B0. The
default adapter mints real UUIDs; tests inject a deterministic fake so the
``run_id`` and artifact-directory suffix can be pinned by the golden-master
suite (A2).
"""

from __future__ import annotations

import uuid
from typing import Protocol


class RunIdentity(Protocol):
    def new_run_id(self) -> str: ...


class SystemRunIdentity:
    """Default adapter: mints a fresh random run identifier."""

    def new_run_id(self) -> str:
        return uuid.uuid4().hex


SYSTEM_IDENTITY: RunIdentity = SystemRunIdentity()
