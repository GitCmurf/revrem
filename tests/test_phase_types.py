"""Tests for B2a phase request/outcome types and harness Protocols (ports.py)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from code_review_loop.clock import Clock
from code_review_loop.core.ports import (
    ChecksHarness,
    ChecksOutcome,
    ChecksRequest,
    CommandResult,
    CommitHarness,
    CommitOutcome,
    CommitRequest,
    RemediationHarness,
    RemediationOutcome,
    RemediationRequest,
    ReviewHarness,
    ReviewOutcome,
    ReviewRequest,
    RunContext,
    TriageHarness,
    TriageOutcome,
    TriageRequest,
)
from code_review_loop.core.routing_types import ResolvedRoute
from code_review_loop.identity import RunIdentity


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ctx(**kwargs: object) -> RunContext:
    return RunContext(
        clock=MagicMock(spec=Clock),
        identity=MagicMock(spec=RunIdentity),
        runner=MagicMock(),
        **kwargs,  # type: ignore[arg-type]
    )


def _cr(returncode: int = 0) -> CommandResult:
    return CommandResult(args=["cmd"], returncode=returncode)


# ---------------------------------------------------------------------------
# Request types
# ---------------------------------------------------------------------------

class TestChecksRequest:
    def test_fields(self) -> None:
        r = ChecksRequest(iteration=3)
        assert r.iteration == 3

    def test_frozen(self) -> None:
        r = ChecksRequest(iteration=1)
        with pytest.raises(Exception):
            r.iteration = 2  # type: ignore[misc]


class TestCommitRequest:
    def test_defaults(self) -> None:
        r = CommitRequest(iteration=1)
        assert r.retrying is False

    def test_retrying_explicit(self) -> None:
        r = CommitRequest(iteration=2, retrying=True)
        assert r.retrying is True


class TestRemediationRequest:
    def test_without_route(self) -> None:
        r = RemediationRequest(iteration=1, remediation_input="fix this")
        assert r.resolved_route is None
        assert r.remediation_input == "fix this"

    def test_with_route(self) -> None:
        route = ResolvedRoute(route_tier="fast", harness="codex")
        r = RemediationRequest(iteration=1, remediation_input="x", resolved_route=route)
        assert r.resolved_route is route


class TestTriageRequest:
    def test_fields(self) -> None:
        r = TriageRequest(
            iteration=2,
            run_id="run-abc",
            source_review_artifact="review-1.txt",
            review_output="some findings",
        )
        assert r.iteration == 2
        assert r.run_id == "run-abc"
        assert r.source_review_artifact == "review-1.txt"
        assert r.review_output == "some findings"


class TestReviewRequest:
    def test_display_label_defaults_to_none(self) -> None:
        r = ReviewRequest(artifact_label="review-1")
        assert r.display_label is None

    def test_explicit_display_label(self) -> None:
        r = ReviewRequest(artifact_label="review-1", display_label="initial")
        assert r.display_label == "initial"


# ---------------------------------------------------------------------------
# Outcome types
# ---------------------------------------------------------------------------

class TestChecksOutcome:
    def test_empty(self) -> None:
        o = ChecksOutcome(results=(), failed_commands=())
        assert o.results == ()
        assert o.failed_commands == ()

    def test_with_failures(self) -> None:
        cr = _cr(returncode=1)
        o = ChecksOutcome(results=(cr,), failed_commands=("pytest",))
        assert len(o.results) == 1
        assert o.failed_commands == ("pytest",)


class TestCommitOutcome:
    @pytest.mark.parametrize("status", ["committed", "skipped", "skipped_no_changes"])
    def test_valid_statuses(self, status: str) -> None:
        o = CommitOutcome(status=status)  # type: ignore[arg-type]
        assert o.status == status


class TestRemediationOutcome:
    def test_wraps_command_result(self) -> None:
        cr = _cr()
        o = RemediationOutcome(result=cr)
        assert o.result is cr


class TestTriageOutcome:
    def test_clear(self) -> None:
        o = TriageOutcome(handoff="", suppressed_count=2, is_clear=True, payload={"k": "v"})
        assert o.is_clear is True
        assert o.suppressed_count == 2

    def test_null_payload(self) -> None:
        o = TriageOutcome(handoff="handoff text", suppressed_count=0, is_clear=False, payload=None)
        assert o.payload is None


class TestReviewOutcome:
    @pytest.mark.parametrize("status", ["clear", "findings", "unknown"])
    def test_valid_statuses(self, status: str) -> None:
        cr = _cr()
        o = ReviewOutcome(status=status, result=cr)  # type: ignore[arg-type]
        assert o.status == status

    def test_result_field(self) -> None:
        cr = _cr()
        o = ReviewOutcome(status="clear", result=cr)
        assert o.result is cr


# ---------------------------------------------------------------------------
# RunContext harness fields
# ---------------------------------------------------------------------------

class TestRunContextHarnessFields:
    def test_all_default_to_none(self) -> None:
        ctx = _ctx()
        assert ctx.phase_checks is None
        assert ctx.phase_commit is None
        assert ctx.phase_remediation is None
        assert ctx.phase_triage is None
        assert ctx.phase_review is None

    def test_harness_fields_injected(self) -> None:
        fake_checks = MagicMock(spec=ChecksHarness)
        fake_commit = MagicMock(spec=CommitHarness)
        fake_remediation = MagicMock(spec=RemediationHarness)
        fake_triage = MagicMock(spec=TriageHarness)
        fake_review = MagicMock(spec=ReviewHarness)
        ctx = _ctx(
            phase_checks=fake_checks,
            phase_commit=fake_commit,
            phase_remediation=fake_remediation,
            phase_triage=fake_triage,
            phase_review=fake_review,
        )
        assert ctx.phase_checks is fake_checks
        assert ctx.phase_commit is fake_commit
        assert ctx.phase_remediation is fake_remediation
        assert ctx.phase_triage is fake_triage
        assert ctx.phase_review is fake_review


# ---------------------------------------------------------------------------
# Protocol duck-type compliance
# ---------------------------------------------------------------------------

class FakeChecksHarness:
    def execute(self, request: ChecksRequest, ctx: RunContext) -> ChecksOutcome:
        return ChecksOutcome(results=(), failed_commands=())


class FakeCommitHarness:
    def execute(self, request: CommitRequest, ctx: RunContext) -> CommitOutcome:
        return CommitOutcome(status="skipped")


class FakeRemediationHarness:
    def execute(self, request: RemediationRequest, ctx: RunContext) -> RemediationOutcome:
        return RemediationOutcome(result=_cr())


class FakeTriageHarness:
    def execute(self, request: TriageRequest, ctx: RunContext) -> TriageOutcome:
        return TriageOutcome(handoff="", suppressed_count=0, is_clear=True, payload=None)


class FakeReviewHarness:
    def execute(self, request: ReviewRequest, ctx: RunContext) -> ReviewOutcome:
        return ReviewOutcome(status="clear", result=_cr())


class TestProtocolCompliance:
    """Concrete fakes can be injected and called through the RunContext."""

    def test_checks_harness_callable(self) -> None:
        ctx = _ctx(phase_checks=FakeChecksHarness())
        outcome = ctx.phase_checks.execute(ChecksRequest(iteration=1), ctx)  # type: ignore[union-attr]
        assert isinstance(outcome, ChecksOutcome)

    def test_commit_harness_callable(self) -> None:
        ctx = _ctx(phase_commit=FakeCommitHarness())
        outcome = ctx.phase_commit.execute(CommitRequest(iteration=1), ctx)  # type: ignore[union-attr]
        assert outcome.status == "skipped"

    def test_remediation_harness_callable(self) -> None:
        ctx = _ctx(phase_remediation=FakeRemediationHarness())
        req = RemediationRequest(iteration=1, remediation_input="fix")
        outcome = ctx.phase_remediation.execute(req, ctx)  # type: ignore[union-attr]
        assert isinstance(outcome, RemediationOutcome)

    def test_triage_harness_callable(self) -> None:
        ctx = _ctx(phase_triage=FakeTriageHarness())
        req = TriageRequest(iteration=1, run_id="r", source_review_artifact="a.txt", review_output="out")
        outcome = ctx.phase_triage.execute(req, ctx)  # type: ignore[union-attr]
        assert outcome.is_clear is True

    def test_review_harness_callable(self) -> None:
        ctx = _ctx(phase_review=FakeReviewHarness())
        outcome = ctx.phase_review.execute(ReviewRequest(artifact_label="review-1"), ctx)  # type: ignore[union-attr]
        assert outcome.status == "clear"
