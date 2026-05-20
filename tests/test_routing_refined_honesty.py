from __future__ import annotations

from code_review_loop import policy, triage


def test_routing_artifact_honesty_full_logic():
    # Setup inputs mimicking _run_loop
    triage_payload = {
        "confirmed_findings": [],
        "rejected_findings": [],
        "needs_more_info": [],
        "classification": {"risk_level": "low"},
        "prompt_requirements": {"definition_of_done": []},
    }

    resolved_route = policy.ResolvedRoute(
        route_tier="midtier",
        harness="codex",
        sandbox="workspace-write",
        timeout_seconds=300.0,
        rule_id="default",
    )

    run_id = "r1"
    iteration = 1

    # Logic extracted from cli.py
    eff_harness = resolved_route.harness
    eff_model = resolved_route.model or "gpt-5.4-mini"
    eff_reasoning = resolved_route.reasoning_effort or "low"
    eff_sandbox = resolved_route.sandbox
    eff_timeout = (
        int(resolved_route.timeout_seconds)
        if resolved_route.timeout_seconds is not None
        else 300
    )

    effective_route = {
        "route_tier": resolved_route.route_tier,
        "harness": eff_harness,
        "sandbox": eff_sandbox,
        "timeout_seconds": eff_timeout,
    }
    if eff_model:
        effective_route["model"] = eff_model
    if eff_reasoning:
        effective_route["reasoning_effort"] = eff_reasoning

    if resolved_route.fallback_applied:
        decision = "fallback_applied"
        original = (
            resolved_route.fallbacks_considered[0]
            if resolved_route.fallbacks_considered
            else "unknown"
        )
        rationale = (
            f"Original route {original!r} fell back to {resolved_route.fallback_applied!r}."
        )
    elif resolved_route.rule_id == "default":
        decision = "default_route_applied"
        rationale = "No model route proposal or rule match; applied default route."
    else:
        decision = "policy_override"
        rationale = "Applied policy based on classification."

    routing_payload = {
        "schema_version": "1.0",
        "run_id": run_id,
        "iteration": iteration,
        "source_triage_artifact": f"triage-{iteration}.json",
        "policy_decision": {
            "decision": decision,
            "matched_rule_ids": (
                [resolved_route.rule_id]
                if resolved_route.rule_id and resolved_route.rule_id != "default"
                else []
            ),
            "rationale": rationale,
        },
        "effective_route": effective_route,
        "fallbacks_considered": list(resolved_route.fallbacks_considered),
        "prompt": {
            "path": f"remediation-{iteration}-prompt.txt",
            "sha256": "abc",
            "bytes": 10,
            "fragments": [],
        },
    }

    if triage_payload.get("route_proposal"):
        p = triage_payload["route_proposal"]
        routing_payload["model_proposal"] = {
            k: v
            for k, v in p.items()
            if k in ("route_tier", "harness", "model", "rationale")
        }

    assert "model_proposal" not in routing_payload
    assert routing_payload["policy_decision"]["decision"] == "default_route_applied"
    triage.validate_routing_payload(routing_payload)
