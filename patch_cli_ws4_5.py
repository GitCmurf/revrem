import re
from pathlib import Path

with open("src/code_review_loop/cli.py", "r") as f:
    content = f.read()

# 1. Add trusted_repo to LoopConfig
content = content.replace(
    "profile_v2: profiles.Profile | None = None",
    "profile_v2: profiles.Profile | None = None\n    trusted_repo: bool = False"
)

# 2. Populate trusted_repo in resolve_config
content = re.sub(
    r"(profile_name=args\.profile,)(\s+budget_config=budget_config,)",
    r"\1\2\n        trusted_repo=pick(args.trusted_repo, False, False),",
    content
)

# 3. Populate trusted_repo in resume_loop_config
content = content.replace(
    "profile_v2=profile_v2,",
    "profile_v2=profile_v2,\n        trusted_repo=_resume_bool(resume_config, \"trusted_repo\", False),"
)

# 4. Pass trusted_repo to compose_remediation_prompt
content = content.replace(
    "max_chars=config.max_remediation_input_chars,",
    "max_chars=config.max_remediation_input_chars,\n                            trusted_repo=config.trusted_repo,"
)

# 5. Add --trusted-repo to parse_args
content = content.replace(
    "parser.add_argument(\n        \"--dry-run\",",
    "parser.add_argument(\n        \"--trusted-repo\",\n        action=\"store_true\",\n        default=None,\n        help=\"Explicitly trust repo-local prompt fragments.\",\n    )\n    parser.add_argument(\n        \"--dry-run\","
)

# 6. routing_outcome logic & events
content = content.replace(
    "iterations[-1][\"check_failures\"] = sum(1 for result in check_results if result.returncode != 0)",
    """iterations[-1]["check_failures"] = sum(1 for result in check_results if result.returncode != 0)
            if resolved_route:
                outcome_payload = {
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "iteration": iteration,
                    "source_routing_artifact": f"routing-{iteration}.json",
                    "exit_code": rem_result.returncode,
                    "wall_time_seconds": 0.0,
                    "checks_passed": all(r.returncode == 0 for r in check_results),
                }
                triage.write_routing_outcome_artifact(config.artifact_dir, iteration, outcome_payload)
                emit_event(config, "routing_outcome", phase="remediate", iteration=iteration, payload=outcome_payload)"""
)

# 7. policy_lint enhancement
content = re.sub(
    r"def policy_lint\(profile_name: str, output_format: str \| None = None\) -> int:.*?return 1",
    """def policy_lint(profile_name: str, output_format: str | None = None) -> int:
    try:
        profile = profiles.resolve_profile(profile_name, cwd=Path.cwd(), require_implemented=False)
        policy_issues = profiles.validate_policy(profile)
        if policy_issues:
            raise ValueError("\\n".join(policy_issues))
        if output_format == "json":
            print(json.dumps({"status": "ok", "profile": profile_name}))
        else:
            print(f"Policy lint passed for profile: {profile_name}")
        return 0
    except Exception as exc:
        if output_format == "json":
            print(json.dumps({"status": "error", "message": str(exc)}))
        else:
            print(f"Policy lint FAILED for profile {profile_name}: {exc}", file=sys.stderr)
        return 1""",
    content,
    flags=re.DOTALL
)

with open("src/code_review_loop/cli.py", "w") as f:
    f.write(content)
