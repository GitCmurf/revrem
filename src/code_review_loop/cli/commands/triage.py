"""``revrem triage`` subcommand (REVREM-TASK-003 Wave C1a)."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop.cli.args import parse_triage_args

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    args = parse_triage_args(argv)
    try:
        if args.command == "explain":
            code = triage_explain(
                Path(args.run_dir),
                args.iteration,
                output_format=getattr(args, "format", None),
            )
            return CommandOk(exit_code=code).exit_code if code == 0 else CommandFailed(exit_code=code).exit_code
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    raise AssertionError(f"unhandled triage command: {args.command}")


def triage_explain(run_dir: Path, iteration: int, output_format: str | None = None) -> int:
    routing_path = run_dir / f"routing-{iteration}.json"
    if not routing_path.is_file():
        print(f"ERROR: routing artifact not found: {routing_path}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code

    try:
        routing = json.loads(routing_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid routing artifact JSON at {routing_path}: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    if not isinstance(routing, dict):
        print(f"ERROR: routing artifact must be a JSON object: {routing_path}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    if output_format == "json":
        print(json.dumps(routing, indent=2, sort_keys=True))
    else:
        print(f"Routing Explanation for {run_dir.name} iteration {iteration}:")
        decision = routing.get("policy_decision", {})
        if not isinstance(decision, dict):
            print(f"ERROR: routing artifact policy_decision must be an object: {routing_path}", file=sys.stderr)
            return CommandFailed(exit_code=1).exit_code
        print(f"  Decision: {decision.get('decision')}")
        print(f"  Rationale: {decision.get('rationale')}")
        matched_rules = decision.get("matched_rule_ids", [])
        if not isinstance(matched_rules, list) or not all(isinstance(rule, str) for rule in matched_rules):
            print(
                f"ERROR: routing artifact policy_decision.matched_rule_ids must be a string array: {routing_path}",
                file=sys.stderr,
            )
            return CommandFailed(exit_code=1).exit_code
        print(f"  Matched Rules: {', '.join(matched_rules)}")

        effective = routing.get("effective_route", {})
        if not isinstance(effective, dict):
            print(f"ERROR: routing artifact effective_route must be an object: {routing_path}", file=sys.stderr)
            return CommandFailed(exit_code=1).exit_code
        print(f"  Effective Route: {effective.get('route_tier')}")
        print(f"    Harness: {effective.get('harness')}")
        print(f"    Model: {effective.get('model')}")

        proposal = routing.get("model_proposal", {})
        if not isinstance(proposal, dict):
            print(f"ERROR: routing artifact model_proposal must be an object: {routing_path}", file=sys.stderr)
            return CommandFailed(exit_code=1).exit_code
        print(f"  Model Proposal: {proposal.get('route_tier')}")
        print(f"    Rationale: {proposal.get('rationale')}")

        prompt = routing.get("prompt", {})
        if not isinstance(prompt, dict):
            print(f"ERROR: routing artifact prompt must be an object: {routing_path}", file=sys.stderr)
            return CommandFailed(exit_code=1).exit_code
        print(f"  Prompt Artifact: {prompt.get('path')}")
        print(f"  Prompt Hash: {prompt.get('sha256')}")

    return CommandOk().exit_code
