"""Unit tests for the hexagon's structural spine (REVREM-TASK-003 B0a, B2a).

`core/ports.py` is the canonical import surface for the ports the core declares
and the port-adjacent value types. B0a defines the foundational collaborator
bundle and base protocols; B4 added ProgressReporter; B2a adds per-phase
request/outcome types and five Harness Protocols.
"""

from __future__ import annotations

from support.phase_harnesses import phase_harness_kwargs

from code_review_loop.core import ports
from code_review_loop.core.ports import (
    Clock,
    CommandResult,
    EventSink,
    ProcessRunner,
    ProgressReporter,
    RunContext,
    RunIdentity,
)


def test_command_result_is_homed_in_core_ports():
    result = CommandResult(["git", "status"], 0, stdout="ok")
    assert result.args == ["git", "status"]
    assert result.returncode == 0
    assert result.stdout == "ok"


def test_loop_reexports_the_same_command_result_object_during_driver_migration():
    from code_review_loop import loop

    assert loop.CommandResult is CommandResult


def test_ports_surface_exposes_the_declared_protocols():
    for name in ("Clock", "RunIdentity", "ProcessRunner", "EventSink", "RunContext", "ProgressReporter"):
        assert hasattr(ports, name), f"core.ports missing {name}"


def test_deferred_ports_are_not_defined_yet():
    # ArtifactStore and GitGateway gain consumers in B3+; premature to define them.
    for name in ("ArtifactStore", "GitGateway"):
        assert not hasattr(ports, name), f"core.ports should defer {name} to B3+"


def test_run_context_bundles_collaborators_only():
    class _Clock:
        def now(self):
            raise NotImplementedError

        def monotonic(self):
            return 0.0

    class _Identity:
        def new_run_id(self):
            return "id"

    def _runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(list(args), 0)

    ctx = RunContext(
        clock=_Clock(),
        identity=_Identity(),
        runner=_runner,
        **phase_harness_kwargs(),
        event_sink=None,
        budget_state=None,
    )
    assert ctx.identity.new_run_id() == "id"
    assert ctx.runner(["x"], None).returncode == 0
    assert ctx.event_sink is None
    assert ctx.budget_state is None
    # config is intentionally NOT a RunContext field in B0 (LoopConfig is edge).
    assert not hasattr(ctx, "config")


def test_protocols_are_runtime_importable_types():
    assert Clock is not None
    assert RunIdentity is not None
    assert ProcessRunner is not None
    assert EventSink is not None
    assert ProgressReporter is not None


def test_b2a_harness_protocols_exported():
    for name in (
        "ChecksHarness", "CommitHarness", "RemediationHarness", "TriageHarness", "ReviewHarness",
    ):
        assert hasattr(ports, name), f"core.ports missing B2a {name}"


def test_b2a_phase_types_exported():
    for name in (
        "ChecksRequest", "ChecksOutcome",
        "CommitRequest", "CommitOutcome",
        "RemediationRequest", "RemediationOutcome",
        "TriageRequest", "TriageOutcome",
        "ReviewRequest", "ReviewOutcome",
    ):
        assert hasattr(ports, name), f"core.ports missing B2a {name}"


def test_b2a_run_context_has_harness_fields():
    class _Clock:
        def now(self): raise NotImplementedError
        def monotonic(self): return 0.0
    class _Identity:
        def new_run_id(self): return "id"
    def _runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(list(args), 0)

    ctx = RunContext(clock=_Clock(), identity=_Identity(), runner=_runner, **phase_harness_kwargs())
    for field in ("phase_checks", "phase_commit", "phase_remediation", "phase_triage", "phase_review"):
        assert getattr(ctx, field) is not None, f"RunContext.{field} should be required"
