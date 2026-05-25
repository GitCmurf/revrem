"""Reusable fake phase harnesses for RunContext tests."""

from __future__ import annotations

from code_review_loop.core.ports import (
    ChecksOutcome,
    ChecksRequest,
    CommandResult,
    CommitOutcome,
    CommitRequest,
    RemediationOutcome,
    RemediationRequest,
    ReviewOutcome,
    ReviewRequest,
    RunContext,
    TriageOutcome,
    TriageRequest,
)


class FakeChecksHarness:
    def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
        return ChecksOutcome(results=(), failed_commands=())


class FakeCommitHarness:
    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
        return CommitOutcome(status="skipped")


class FakeRemediationHarness:
    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
        return RemediationOutcome(result=CommandResult(args=["cmd"], returncode=0))


class FakeTriageHarness:
    def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome:
        return TriageOutcome(handoff="", suppressed_count=0, is_clear=True, payload=None)


class FakeReviewHarness:
    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
        return ReviewOutcome(status="clear", result=CommandResult(args=["cmd"], returncode=0))


def phase_harness_kwargs(**overrides: object) -> dict[str, object]:
    harnesses: dict[str, object] = {
        "phase_checks": FakeChecksHarness(),
        "phase_commit": FakeCommitHarness(),
        "phase_remediation": FakeRemediationHarness(),
        "phase_triage": FakeTriageHarness(),
        "phase_review": FakeReviewHarness(),
    }
    harnesses.update(overrides)
    return harnesses
