"""Headless application test helpers for REVREM-TASK-003 Wave D."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_review_loop import application, budgets
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import (
    ChecksOutcome,
    ChecksRequest,
    CommandResult,
    CommitOutcome,
    CommitRequest,
    CommitStatus,
    PhaseHarnessBundle,
    ProcessRunner,
    RemediationOutcome,
    RemediationRequest,
    ReviewOutcome,
    ReviewRequest,
    ReviewStatus,
    RunContext,
    TriageOutcome,
    TriageRequest,
)
from tests.support.fakes import FakeClock, FakeRunIdentity


class UnexpectedProcessCall(AssertionError):
    """Raised when a headless test unexpectedly reaches the process runner."""

    def __init__(self, argv: Sequence[str]):
        super().__init__(f"unexpected process call: {list(argv)}")
        self.argv = list(argv)


class RecordingProcessRunner:
    """Process runner that records calls and fails unless configured."""

    def __init__(self, responses: dict[str, CommandResult | BaseException] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(
        self,
        args: Sequence[str],
        cwd: Path,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        argv = list(args)
        self.calls.append((argv, input_text))
        phase = argv[1] if len(argv) > 1 else ""
        response = self.responses.get(phase)
        if response is None:
            raise UnexpectedProcessCall(argv)
        if isinstance(response, BaseException):
            raise response
        return CommandResult(
            argv,
            response.returncode,
            stdout=response.stdout,
            stderr=response.stderr,
            tokens=response.tokens,
            usd=response.usd,
        )


class SequencedReviewHarness:
    def __init__(self, statuses: Sequence[ReviewStatus]) -> None:
        self.statuses = list(statuses)
        self.calls: list[ReviewRequest] = []

    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
        self.calls.append(request)
        if not self.statuses:
            raise AssertionError("review status sequence exhausted")
        status = self.statuses.pop(0)
        stdout = f"review status: {status}\nREVIEW_STATUS: {status}\n"
        return ReviewOutcome(
            status=status,
            result=CommandResult(["fake", "review"], 0, stdout=stdout),
        )


class StaticTriageHarness:
    def __init__(self, *, is_clear: bool = False, handoff: str = "fix it") -> None:
        self.is_clear = is_clear
        self.handoff = handoff
        self.calls: list[TriageRequest] = []

    def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome:
        self.calls.append(request)
        return TriageOutcome(
            handoff=self.handoff,
            suppressed_count=0,
            is_clear=self.is_clear,
            payload={"confirmed_findings": []},
        )


class RecordingRemediationHarness:
    def __init__(self, exc: BaseException | None = None) -> None:
        self.exc = exc
        self.calls: list[RemediationRequest] = []

    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
        self.calls.append(request)
        if self.exc is not None:
            raise self.exc
        return RemediationOutcome(result=CommandResult(["fake", "exec"], 0, stdout="fixed\n"))


class SequencedChecksHarness:
    def __init__(self, failed_commands: Sequence[Sequence[str]] = ()) -> None:
        self.failed_commands = [tuple(commands) for commands in failed_commands]
        self.calls: list[ChecksRequest] = []

    def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
        self.calls.append(request)
        failed = self.failed_commands.pop(0) if self.failed_commands else ()
        results = tuple(
            CommandResult(command.split(), 1, stdout=f"{command} failed\n")
            for command in failed
        )
        return ChecksOutcome(results=results, failed_commands=failed)


class StaticCommitHarness:
    def __init__(self, status: CommitStatus = "skipped") -> None:
        self.status = status
        self.calls: list[CommitRequest] = []

    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
        self.calls.append(request)
        return CommitOutcome(status=self.status)


@dataclass
class HeadlessRun:
    config: LoopConfig
    process_runner: ProcessRunner = field(default_factory=RecordingProcessRunner)
    clock: FakeClock = field(default_factory=FakeClock)
    identity: FakeRunIdentity = field(default_factory=FakeRunIdentity)
    budget_state: budgets.BudgetState | None = None
    review: SequencedReviewHarness = field(default_factory=lambda: SequencedReviewHarness(["clear"]))
    triage: StaticTriageHarness = field(default_factory=StaticTriageHarness)
    remediation: RecordingRemediationHarness = field(default_factory=RecordingRemediationHarness)
    checks: SequencedChecksHarness = field(default_factory=SequencedChecksHarness)
    commit: StaticCommitHarness = field(default_factory=StaticCommitHarness)

    @classmethod
    def with_tmp_config(cls, tmp_path: Path, **kwargs: Any) -> HeadlessRun:
        config = LoopConfig(
            base="main",
            max_iterations=2,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
            progress=False,
            triage_enabled=False,
        )
        return cls(config=config, **kwargs)

    def phase_harnesses(self) -> PhaseHarnessBundle:
        return PhaseHarnessBundle(
            checks=self.checks,
            commit=self.commit,
            remediation=self.remediation,
            review=self.review,
            triage=self.triage,
        )

    def run(self) -> application.ReviewLoopResult:
        return application.run_review_loop(
            self.config,
            self.process_runner,
            clock=self.clock,
            identity=self.identity,
            budget_state=self.budget_state,
            phase_harnesses=self.phase_harnesses(),
            terminal_ui=False,
        )
