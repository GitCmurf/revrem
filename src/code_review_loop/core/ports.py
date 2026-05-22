"""The ports the review-loop core declares (REVREM-TASK-003 B0a).

This module is the canonical *import surface* for the hexagon's ports and the
port-adjacent value types. The core depends on these interfaces; adapters at the
edge implement them; drivers wire concrete adapters into a `RunContext` and call
the core.

Scope discipline (B0a):

- `CommandResult` is **homed here** (moved out of `cli.py`); `cli.py` re-exports
  it so existing imports keep working. It is the one value type the runner port
  forces into the core, so it cannot live in the driver.
- `Clock`, `RunIdentity`, and `EventSink` Protocols are **re-exported** from
  their current modules (`clock.py`, `identity.py`, `events.py`) rather than
  physically moved. Physically inverting those definitions into the core would
  create an import cycle today (`events` imports `clock`); the dependency
  *inversion* is deferred to B2 when the layered import-linter contract lands and
  the adapter package exists to receive them.
- `ProcessRunner` is a new Protocol formalizing the `cli.Runner` callable.
- `RunContext` bundles the injected **collaborators only** — not config. C7's
  literal "config + ports" collides with the dependency rule because
  `LoopConfig` lives in `cli.py` and pulls in `profiles` (an edge module). Until
  `LoopConfig` is core-homed (post-B1), phases take `config` and `ctx`
  separately; config folds onto `RunContext` then.
- `ProgressReporter` is **defined here** (B4) — it decouples the engine from
  the terminal; `TerminalProgressReporter` in `adapters/terminal.py` implements it.
- `Harness`, `ArtifactStore`, and `GitGateway` are **deliberately not defined
  yet** — they gain consumers in B2+, and writing protocols with no implementation
  is the "hexagonal cosplay" the plan declines.

The core imports only the standard library and these ports (Contract C4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from code_review_loop.budgets import BudgetState
from code_review_loop.clock import Clock as Clock
from code_review_loop.events import EventSink as EventSink
from code_review_loop.identity import RunIdentity as RunIdentity


@dataclass(frozen=True)
class CommandResult:
    """The result of running one subprocess: the runner port's return type."""

    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    tokens: int | None = None
    usd: Decimal | None = None


class ProgressReporter(Protocol):
    """Renders loop progress to the terminal (semantic, not raw escape codes).

    Separates rendering from the event-sink (machine output) contract so that
    core phase functions never import terminal or progress modules (Contract C4).
    The driver creates a concrete adapter and injects it via RunContext.
    """

    def phase(self, phase: str, label: str, status: str, detail: str = "") -> None:
        """Render one phase progress line."""
        ...


class ProcessRunner(Protocol):
    """Runs one subprocess and returns its captured result."""

    def __call__(
        self,
        args: Sequence[str],
        cwd: Path,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult: ...


@dataclass(frozen=True)
class RunContext:
    """Immutable bundle of injected collaborators handed to the loop.

    The *reference* to each collaborator is immutable; the objects need not be —
    `budget_state` accumulates token/usd charges in place during a run, which is
    intentional and not a violation of the frozen container.

    Config is **not** a field here (see the module docstring): phases consume
    `config` alongside `ctx` until `LoopConfig` is core-homed.
    """

    clock: Clock
    identity: RunIdentity
    runner: ProcessRunner
    event_sink: EventSink | None = None
    budget_state: BudgetState | None = None
    progress_reporter: ProgressReporter | None = None
