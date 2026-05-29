from __future__ import annotations

from code_review_loop import policy, routing_artifacts
from code_review_loop.config import LoopConfig


def _route(timeout_seconds: float | None = None) -> policy.ResolvedRoute:
    return policy.ResolvedRoute(
        route_tier="efficient",
        harness="codex",
        model="gpt-test",
        reasoning_effort="low",
        timeout_seconds=timeout_seconds,
        sandbox="workspace-write",
    )


def test_routing_payload_inherits_global_timeout_for_omitted_route_timeout(
    tmp_path,
):
    payload = routing_artifacts.build_routing_payload(
        resolved_route=_route(timeout_seconds=None),
        triage_payload={},
        run_id="run-1",
        iteration=1,
        remediation_input="fix it",
        config=LoopConfig(cwd=tmp_path, artifact_dir=tmp_path, timeout_seconds=900),
    )

    assert payload["effective_route"]["timeout_seconds"] == 900


def test_routing_payload_records_zero_for_unbounded_inherited_timeout(tmp_path):
    payload = routing_artifacts.build_routing_payload(
        resolved_route=_route(timeout_seconds=None),
        triage_payload={},
        run_id="run-1",
        iteration=1,
        remediation_input="fix it",
        config=LoopConfig(cwd=tmp_path, artifact_dir=tmp_path, timeout_seconds=None),
    )

    assert payload["effective_route"]["timeout_seconds"] == 0


def test_routing_payload_preserves_fractional_route_timeout(tmp_path):
    payload = routing_artifacts.build_routing_payload(
        resolved_route=_route(timeout_seconds=0.5),
        triage_payload={},
        run_id="run-1",
        iteration=1,
        remediation_input="fix it",
        config=LoopConfig(cwd=tmp_path, artifact_dir=tmp_path),
    )

    assert payload["effective_route"]["timeout_seconds"] == 0.5


def test_routing_payload_counts_prompt_utf8_bytes(tmp_path):
    remediation_input = "Fix café ☕"

    payload = routing_artifacts.build_routing_payload(
        resolved_route=_route(timeout_seconds=60),
        triage_payload={},
        run_id="run-1",
        iteration=1,
        remediation_input=remediation_input,
        config=LoopConfig(cwd=tmp_path, artifact_dir=tmp_path),
    )

    assert payload["prompt"]["bytes"] == len(remediation_input.encode("utf-8"))
    assert payload["prompt"]["bytes"] > len(remediation_input)
