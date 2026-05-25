"""Deterministic fake ports for golden-master testing (REVREM-TASK-003 A2).

Plain duck-typed classes (not Protocol subclasses); the port formalization is
B0's job. Promoted here from the A1 seam test so every later snapshot case can
share them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from code_review_loop.core.ports import CommandResult

FIXED_MOMENT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
FIXED_ISO = "2026-01-02T03:04:05Z"
FIXED_RUN_ID = "deadbeefcafe0000deadbeefcafe0000"


class FakeClock:
    """A clock frozen at a fixed instant with a fixed monotonic reading."""

    def __init__(self, moment: datetime = FIXED_MOMENT, monotonic: float = 1000.0):
        self._moment = moment
        self._monotonic = monotonic

    def now(self) -> datetime:
        return self._moment

    def monotonic(self) -> float:
        return self._monotonic


class FakeRunIdentity:
    """Mints a fixed run identifier so ``run_id`` is deterministic."""

    def __init__(self, value: str = FIXED_RUN_ID):
        self._value = value

    def new_run_id(self) -> str:
        return self._value


class FakeRunner:
    """A subprocess runner that maps a phase (``args[1]``) to a canned result.

    Records each call so tests can assert on the phase sequence. Construct with
    a mapping of phase name -> ``CommandResult`` (returned) or ``BaseException``
    (raised, e.g. ``KeyboardInterrupt`` to drive the cancel path); an unmapped
    phase raises ``AssertionError``.
    """

    def __init__(self, responses: dict[str, CommandResult | BaseException]):
        self._responses = responses
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(
        self,
        args: Sequence[str],
        cwd,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        argv = list(args)
        self.calls.append((argv, input_text))
        phase = argv[1] if len(argv) > 1 else ""
        try:
            template = self._responses[phase]
        except KeyError:
            raise AssertionError(f"FakeRunner: no response for phase {phase!r} (args={argv})") from None
        if isinstance(template, BaseException):
            raise template
        # Rebuild with the real call args so artifacts/events reflect the actual invocation.
        return CommandResult(
            argv,
            template.returncode,
            stdout=template.stdout,
            stderr=template.stderr,
            tokens=template.tokens,
            usd=template.usd,
        )
