"""The ports the review-loop core declares (REVREM-TASK-003 B0a, B2a).

This module is the canonical *import surface* for the hexagon's ports and the
port-adjacent value types. The core depends on these interfaces; adapters at the
edge implement them; drivers wire concrete adapters into a `RunContext` and call
the core.

Scope discipline:

- `CommandResult` is the process-runner port result type.
- `Clock`, `RunIdentity`, and `EventSink` are imported through this canonical
  port surface so application code has one collaborator bundle to wire.
- `ProcessRunner` formalises subprocess execution.
- `ProgressReporter` decouples loop progress semantics from terminal rendering.

The phase request/outcome value types and per-phase `*Harness` Protocols are
the application-to-adapter seam:

- **Per-phase protocols** (`ChecksHarness`, `CommitHarness`, `RemediationHarness`,
  `TriageHarness`, `ReviewHarness`) over a single `Harness` Protocol: each adapter
  carries one typed `execute()` with no sum-type dispatch. Wave C completion makes
  these ports required, so there is no hidden legacy dispatch path.
- **Adapters close over `LoopConfig`** in `__init__`; request types carry only
  the per-call variance (iteration, runtime inputs). `LoopConfig` never appears
  in core types.
- **Errors still raise**: harness.execute() raises on failure (same contract as
  the current phase functions); outcome types cover success paths only.
- **"Decide" is read-only-IO-allowed**: `ChecksRequest` etc. carry pre-call data;
  disk introspection (e.g. adaptive-check skip) happens inside `execute()`.

`ArtifactStore` and `GitGateway` are deliberately absent — they gain consumers
in B3+; writing protocols with no implementation is hexagonal cosplay.

The core imports only the standard library and these ports (Contract C4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from code_review_loop.budgets import BudgetState
from code_review_loop.clock import Clock
from code_review_loop.core.routing_types import ResolvedRoute
from code_review_loop.events import EventSink
from code_review_loop.git_context_cache import GitContextCache
from code_review_loop.identity import RunIdentity

ReviewStatus = Literal["clear", "findings", "unknown"]
CommitStatus = Literal["committed", "skipped", "skipped_no_changes"]


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


# ---------------------------------------------------------------------------
# B2a — per-phase request / outcome value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChecksRequest:
    """Inputs for one checks phase invocation."""

    iteration: int
    artifact_label: str | None = None
    display_label: str | None = None


@dataclass(frozen=True)
class ChecksOutcome:
    """Result of a successful checks phase."""

    results: tuple[CommandResult, ...]
    failed_commands: tuple[str, ...]


@dataclass(frozen=True)
class CommitRequest:
    """Inputs for one commit phase invocation."""

    iteration: int
    retrying: bool = False


@dataclass(frozen=True)
class CommitOutcome:
    """Result of a successful commit phase."""

    status: CommitStatus


@dataclass(frozen=True)
class RemediationRequest:
    """Inputs for one remediation phase invocation."""

    iteration: int
    remediation_input: str
    resolved_route: ResolvedRoute | None = None
    artifact_label: str | None = None
    display_label: str | None = None


@dataclass(frozen=True)
class RemediationOutcome:
    """Result of a successful remediation phase."""

    result: CommandResult


@dataclass(frozen=True)
class TriageRequest:
    """Inputs for one triage phase invocation."""

    iteration: int
    run_id: str
    source_review_artifact: str
    review_output: str


@dataclass(frozen=True)
class TriageOutcome:
    """Result of a successful triage phase."""

    handoff: str
    suppressed_count: int
    is_clear: bool
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class ReviewRequest:
    """Inputs for one review phase invocation."""

    artifact_label: str
    display_label: str | None = None


@dataclass(frozen=True)
class ReviewOutcome:
    """Result of a successful review phase."""

    status: ReviewStatus
    result: CommandResult


# ---------------------------------------------------------------------------
# Per-phase harness Protocols. Each adapter closes over LoopConfig in
# __init__; request types carry only per-call variance.
# ---------------------------------------------------------------------------

class ChecksHarness(Protocol):
    """Executes the checks phase."""

    def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome: ...


class CommitHarness(Protocol):
    """Executes the commit phase."""

    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome: ...


class RemediationHarness(Protocol):
    """Executes the remediation phase."""

    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome: ...


class TriageHarness(Protocol):
    """Executes the triage phase."""

    def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome: ...


class ReviewHarness(Protocol):
    """Executes the review phase."""

    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome: ...


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
    phase_checks: ChecksHarness
    phase_commit: CommitHarness
    phase_remediation: RemediationHarness
    phase_triage: TriageHarness
    phase_review: ReviewHarness
    event_sink: EventSink | None = None
    budget_state: BudgetState | None = None
    progress_reporter: ProgressReporter | None = None
    git_context_cache: GitContextCache | None = None
    git_head_at_start: str | None = None


@dataclass(frozen=True)
class PhaseHarnessBundle:
    """Injected phase harness set used by non-CLI application callers and tests."""

    checks: ChecksHarness
    commit: CommitHarness
    remediation: RemediationHarness
    review: ReviewHarness
    triage: TriageHarness
