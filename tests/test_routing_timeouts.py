from __future__ import annotations

from code_review_loop import policy, routing_artifacts, routing_timeouts
from code_review_loop.cli import args as cli_args
from code_review_loop.cli import config_builder
from code_review_loop.adapters.remediation import run_remediation
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, RunContext
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs


def _route(timeout_seconds: float | None) -> policy.ResolvedRoute:
    return policy.ResolvedRoute(
        route_tier="codex-midi",
        harness="codex",
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        timeout_seconds=timeout_seconds,
        sandbox="workspace-write",
        prompt_fragments=(),
        allow_model_deescalation=True,
    )


def test_route_timeout_zero_is_capped_by_cli_timeout() -> None:
    config = LoopConfig(
        timeout_seconds=600,
        remediation_timeout_seconds=600,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )

    assert routing_timeouts.effective_route_timeout_seconds(config, _route(0)) == 600
    assert routing_timeouts.effective_route_timeout_display(config, _route(0)) == 600


def test_route_timeout_keeps_unbounded_when_no_cli_cap() -> None:
    config = LoopConfig(
        timeout_seconds=300,
        remediation_timeout_seconds=None,
        phase_config_field_sources={"remediation": {"timeout_seconds": "profile:dogfood"}},
    )

    assert routing_timeouts.effective_route_timeout_seconds(config, _route(0)) is None
    assert routing_timeouts.effective_route_timeout_display(config, _route(0)) == 0


def test_route_timeout_is_min_of_route_and_cli_cap() -> None:
    config = LoopConfig(
        timeout_seconds=600,
        remediation_timeout_seconds=600,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )

    assert routing_timeouts.effective_route_timeout_seconds(config, _route(1200)) == 600
    assert routing_timeouts.effective_route_timeout_seconds(config, _route(300)) == 300


def test_cli_timeout_zero_does_not_cap_positive_route_timeout() -> None:
    config = LoopConfig(
        timeout_seconds=0,
        remediation_timeout_seconds=0,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )

    assert routing_timeouts.effective_route_timeout_seconds(config, _route(1200)) == 1200
    assert routing_timeouts.effective_route_timeout_display(config, _route(1200)) == 1200


def test_cli_timeout_zero_preserves_unbounded_route_timeout() -> None:
    config = LoopConfig(
        timeout_seconds=0,
        remediation_timeout_seconds=0,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )

    assert routing_timeouts.effective_route_timeout_seconds(config, _route(0)) is None
    assert routing_timeouts.effective_route_timeout_display(config, _route(0)) == 0


def test_routing_artifact_uses_effective_timeout() -> None:
    config = LoopConfig(
        timeout_seconds=600,
        remediation_timeout_seconds=600,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )

    payload = routing_artifacts.build_routing_payload(
        resolved_route=_route(0),
        triage_payload={},
        run_id="run-1",
        iteration=1,
        remediation_input="fix it",
        config=config,
    )

    assert payload["effective_route"]["timeout_seconds"] == 600


def test_routing_artifact_records_unbounded_when_cli_zero_and_route_zero() -> None:
    config = LoopConfig(
        timeout_seconds=0,
        remediation_timeout_seconds=0,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )

    payload = routing_artifacts.build_routing_payload(
        resolved_route=_route(0),
        triage_payload={},
        run_id="run-1",
        iteration=1,
        remediation_input="fix it",
        config=config,
    )

    assert payload["effective_route"]["timeout_seconds"] == 0


def test_routed_remediation_uses_effective_timeout_for_subprocess(tmp_path) -> None:
    captured_timeouts: list[float | None] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        captured_timeouts.append(timeout_seconds)
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        timeout_seconds=600,
        remediation_timeout_seconds=600,
        output_last_message=False,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )
    route = _route(0)
    ctx = RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )

    result = run_remediation(config, runner, 1, "fix it", resolved_route=route, ctx=ctx)

    assert result.returncode == 0
    assert captured_timeouts == [600]
    assert (tmp_path / "artifacts" / "remediation-1.txt").read_text(encoding="utf-8") == "fixed\n"


def test_routed_remediation_uses_route_timeout_when_cli_zero(tmp_path) -> None:
    captured_timeouts: list[float | None] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        captured_timeouts.append(timeout_seconds)
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        timeout_seconds=0,
        remediation_timeout_seconds=0,
        output_last_message=False,
        phase_config_field_sources={"remediation": {"timeout_seconds": "cli"}},
    )
    route = _route(300)
    ctx = RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )

    result = run_remediation(config, runner, 1, "fix it", resolved_route=route, ctx=ctx)

    assert result.returncode == 0
    assert captured_timeouts == [300]


def test_cli_remediation_zero_does_not_fall_back_to_shared_timeout(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    args = cli_args.parse_args(
        [
            "--timeout-seconds",
            "600",
            "--remediation-timeout-seconds",
            "0",
            "--dry-run",
        ]
    )
    config, _summary_format = config_builder.build_loop_config(args, tmp_path)

    route = _route(1200)

    assert config.timeout_seconds == 600
    assert config.remediation_timeout_seconds == 0
    assert config.phase_config_field_sources["remediation"]["timeout_seconds"] == "cli"
    assert routing_timeouts.effective_route_timeout_seconds(config, route) == 1200
