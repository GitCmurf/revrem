"""``revrem policy`` subcommand (REVREM-TASK-003 Wave C1a)."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from code_review_loop import profiles
from code_review_loop.cli.args import parse_policy_args

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_policy_args(argv)
    try:
        if args.command == "lint":
            code = policy_lint(
                args.profile,
                output_format=getattr(args, "format", None),
                executable_routes=args.executable_routes,
            )
            return (
                CommandOk(exit_code=code).exit_code
                if code == 0
                else CommandFailed(exit_code=code).exit_code
            )
        if args.command == "review":
            code = policy_review(
                Path(args.artifact_dir), output_format=getattr(args, "format", None)
            )
            return (
                CommandOk(exit_code=code).exit_code
                if code == 0
                else CommandFailed(exit_code=code).exit_code
            )
        raise ValueError(f"unhandled policy command: {args.command}")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code


def policy_lint(
    profile_name: str,
    output_format: str | None = None,
    *,
    executable_routes: bool = False,
) -> int:
    try:
        profile = profiles.resolve_profile(profile_name, cwd=Path.cwd(), require_implemented=False)
        policy_issues = profiles.validate_policy(profile, executable_routes=executable_routes)
        if policy_issues:
            raise ValueError("\n".join(policy_issues))
        if output_format == "json":
            print(json.dumps({"status": "ok", "profile": profile_name}))
        else:
            print(f"Policy lint passed for profile: {profile_name}")
        return CommandOk().exit_code
    except (FileNotFoundError, ValueError) as exc:
        if output_format == "json":
            print(json.dumps({"status": "error", "message": str(exc)}))
        else:
            print(f"Policy lint FAILED for profile {profile_name}: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code


def policy_review(artifact_dir: Path, output_format: str | None = None) -> int:
    if not artifact_dir.is_dir():
        raise ValueError(f"artifact directory not found: {artifact_dir}")

    decisions: list[dict[str, Any]] = []

    def _routing_sort_key(path: Path) -> int:
        parts = path.stem.split("-")
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
        return 0  # outcome-exempt: sort key fallback

    for routing_path in sorted(artifact_dir.glob("routing-*.json"), key=_routing_sort_key):
        payload = json.loads(routing_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        outcome_path = artifact_dir / routing_path.name.replace("routing-", "routing-outcome-", 1)
        outcome: dict[str, Any] = {}
        if outcome_path.is_file():
            outcome_payload = json.loads(outcome_path.read_text(encoding="utf-8"))
            if isinstance(outcome_payload, dict):
                outcome = outcome_payload
        effective_route = payload.get("effective_route")
        policy_decision = payload.get("policy_decision")
        prompt = payload.get("prompt")
        if not isinstance(effective_route, dict) or not isinstance(policy_decision, dict):
            continue
        decisions.append(
            {
                "iteration": payload.get("iteration"),
                "decision": policy_decision.get("decision"),
                "route_tier": effective_route.get("route_tier"),
                "harness": effective_route.get("harness"),
                "model": effective_route.get("model"),
                "fallbacks_considered": payload.get("fallbacks_considered", []),
                "prompt_sha256": prompt.get("sha256") if isinstance(prompt, dict) else None,
                "checks_passed": outcome.get("checks_passed"),
                "exit_code": outcome.get("exit_code"),
            }
        )

    summary = {
        "artifact_dir": str(artifact_dir),
        "routing_decisions": decisions,
        "decision_count": len(decisions),
    }
    if output_format == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
        return CommandOk().exit_code
    if not decisions:
        print(f"No routing decisions found in {artifact_dir}.")
        return CommandOk().exit_code
    print(f"Routing policy review for {artifact_dir}:")
    for decision in decisions:
        print(
            "iteration={iteration} decision={decision} route={route_tier} "
            "harness={harness} model={model} checks_passed={checks_passed}".format(**decision)
        )
    return CommandOk().exit_code
