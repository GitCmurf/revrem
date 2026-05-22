"""Unit tests for the hexagon's structural spine (REVREM-TASK-003 B0a).

`core/ports.py` is the canonical import surface for the ports the core declares
and the port-adjacent value types. B0a defines only the ports with a consumer
today (Clock, RunIdentity, ProcessRunner, EventSink) plus CommandResult and the
collaborator bundle RunContext; the remaining ports (Harness, ProgressReporter,
ArtifactStore, GitGateway) are deferred to B2/B4 where they gain consumers.
"""

from __future__ import annotations

from code_review_loop.core import ports
from code_review_loop.core.ports import (
    Clock,
    CommandResult,
    EventSink,
    ProcessRunner,
    RunContext,
    RunIdentity,
)


def test_command_result_is_homed_in_core_ports():
    result = CommandResult(["git", "status"], 0, stdout="ok")
    assert result.args == ["git", "status"]
    assert result.returncode == 0
    assert result.stdout == "ok"


def test_cli_reexports_the_same_command_result_object():
    from code_review_loop import cli

    assert cli.CommandResult is CommandResult


def test_ports_surface_exposes_the_declared_protocols():
    for name in ("Clock", "RunIdentity", "ProcessRunner", "EventSink", "RunContext"):
        assert hasattr(ports, name), f"core.ports missing {name}"


def test_deferred_ports_are_not_defined_yet():
    # B0a deliberately defers these to B2/B4 (no consumer today, avoid cosplay).
    for name in ("Harness", "ProgressReporter", "ArtifactStore", "GitGateway"):
        assert not hasattr(ports, name), f"core.ports should defer {name} to B2/B4"


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
