import re
from pathlib import Path

with open("src/code_review_loop/cli.py", "r") as f:
    content = f.read()

# 1. Implement _resolve_executable
helper = """
def _resolve_executable(harness: str, config: LoopConfig) -> str:
    if harness == "codex":
        return config.codex_bin
    registry = harnesses.harness_registry()
    if harness in registry:
        return registry[harness].executable
    return harness
"""

if "_resolve_executable" not in content:
    content = content.replace("def build_review_command", helper + "\n\ndef build_review_command")

# 2. Update command builders to use _resolve_executable and correct harness/role
content = re.sub(
    r"def build_review_command\(config: LoopConfig\) -> list\[str\]:.*?executable=config\.codex_bin,",
    r'def build_review_command(config: LoopConfig) -> list[str]:\n    return harnesses.build_phase_command(\n        harnesses.PhaseCommandRequest(\n            harness=config.review_harness,\n            role="review",\n            executable=_resolve_executable(config.review_harness, config),',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r"def build_remediation_command\(.*?executable=config\.codex_bin,",
    r'def build_remediation_command(\n    config: LoopConfig,\n    output_last_message: Path | None = None,\n    resolved_route: policy.ResolvedRoute | None = None,\n) -> list[str]:\n    harness = resolved_route.harness if resolved_route else config.remediation_harness\n    return harnesses.build_phase_command(\n        harnesses.PhaseCommandRequest(\n            harness=harness,\n            role="remediation",\n            executable=_resolve_executable(harness, config),',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r"def build_triage_command\(config: LoopConfig\) -> list\[str\]:.*?executable=config\.codex_bin,",
    r'def build_triage_command(config: LoopConfig) -> list[str]:\n    return harnesses.build_phase_command(\n        harnesses.PhaseCommandRequest(\n            harness=config.triage_harness,\n            role="triage",\n            executable=_resolve_executable(config.triage_harness, config),',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r"def build_commit_message_command\(config: LoopConfig\) -> list\[str\]:.*?executable=config\.codex_bin,",
    r'def build_commit_message_command(config: LoopConfig) -> list[str]:\n    return harnesses.build_phase_command(\n        harnesses.PhaseCommandRequest(\n            harness=config.commit_message_harness,\n            role="commit-message",\n            executable=_resolve_executable(config.commit_message_harness, config),',
    content,
    flags=re.DOTALL
)

# 3. Fix routing artifact construction (schema compliance)
routing_payload_fix = """                        # Record routing artifact
                        routing_payload = {
                            "run_id": run_id,
                            "iteration": iteration,
                            "source_triage_artifact": f"triage-{iteration}.json",
                            "model_proposal": {
                                "route_tier": model_proposal.get("route_tier"),
                                "harness": model_proposal.get("harness"),
                                "model": model_proposal.get("model"),
                                "rationale": model_proposal.get("rationale"),
                            },
                            "policy_decision": {
                                "decision": "proposal_accepted" if resolved_route.rule_id == "default" else "policy_override",
                                "matched_rule_ids": [resolved_route.rule_id] if resolved_route.rule_id else [],
                                "rationale": "Applied policy based on classification.",
                            },
                            "effective_route": {
                                "route_tier": resolved_route.route_tier,
                                "harness": resolved_route.harness,
                                "model": resolved_route.model,
                                "reasoning_effort": resolved_route.reasoning_effort,
                                "sandbox": resolved_route.sandbox,
                                "timeout_seconds": int(resolved_route.timeout_seconds) if resolved_route.timeout_seconds is not None else 300,
                            },
                            "fallbacks_considered": [],
                            "prompt": {
                                "path": f"remediation-{iteration}-prompt.txt",
                                "sha256": prompts_composer.compute_prompt_hash(remediation_input),
                                "bytes": len(remediation_input),
                                "fragments": list(resolved_route.prompt_fragments),
                            },
                        }
                        # Validate routing artifact against schema
                        try:
                            triage.validate_routing_payload(routing_payload)
                        except Exception as exc:
                            progress_event(config, "triage", str(iteration), "warning", f"routing payload schema validation failed: {exc}")
                        
                        triage.write_routing_artifact(config.artifact_dir, iteration, routing_payload)"""

content = re.sub(
    r"# Record routing artifact.*?triage\.write_routing_artifact\(config\.artifact_dir, iteration, routing_payload\)",
    routing_payload_fix,
    content,
    flags=re.DOTALL
)

with open("src/code_review_loop/cli.py", "w") as f:
    f.write(content)
