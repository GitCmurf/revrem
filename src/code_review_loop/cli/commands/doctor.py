"""``revrem doctor`` subcommand."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import check_suggestions, diagnostics, profiles, suppressions
from code_review_loop.cli.args import parse_doctor_args, parse_doctor_checks_args
from code_review_loop.cli.config_builder import default_artifact_dir, profile_or_default

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    if argv and argv[0] == "checks":
        return _checks_main(argv[1:])
    args = parse_doctor_args(argv)
    try:
        profile = profile_or_default(args.profile, Path.cwd(), require_implemented=False)
    except (FileNotFoundError, ValueError) as exc:
        issues = [
            diagnostics.DiagnosticIssue(
                code="revrem.preflight.profile_error",
                severity="blocking",
                message="RevRem profile configuration could not be resolved.",
                hint=str(exc),
                evidence={"profile": args.profile},
            )
        ]
    else:
        artifact_dir = _doctor_artifact_dir(args, profile)
        issues = diagnostics.run_doctor(
            diagnostics.DoctorConfig(
                cwd=Path.cwd(),
                base=args.base if args.base is not None else profile.pipeline.base,
                artifact_dir=artifact_dir,
                artifact_dir_is_default=args.artifact_dir is None
                and profile.output.artifact_dir is None,
                codex_bin=args.codex_bin
                if args.codex_bin is not None
                else profile.runtime.codex_bin,
                review_harness=profile.review.harness,
                remediation_harness=profile.remediation.harness,
                triage_enabled=profile.triage.enabled,
                triage_harness=profile.triage.harness,
                commit_message_harness=profile.commit.harness,
                routed_harnesses=profile_routed_harnesses(
                    profile,
                    include_disabled_routes=args.validate_routes,
                ),
                harness_executables=profile.runtime.harness_executables,
                check_commands=tuple(args.check)
                if args.check is not None
                else profile.pipeline.checks,
                commit_after_remediation=(
                    args.commit_after_remediation
                    if args.commit_after_remediation is not None
                    else profile.commit.enabled
                ),
                review_timeout_seconds=profile.review.timeout_seconds,
                remediation_timeout_seconds=profile.remediation.timeout_seconds,
                triage_timeout_seconds=(
                    profile.triage.timeout_seconds if profile.triage.enabled else None
                ),
            )
        )
        issues.extend(_route_timeout_issues(profile, include_disabled_routes=args.validate_routes))
        issues.extend(_suppression_doctor_issues(Path.cwd()))
        issues = _drop_ok_if_other_issues(issues)
    output_format = args.format or ("text" if sys.stdout.isatty() else "json")
    if output_format == "json":
        print(diagnostics.doctor_json(issues), end="")
    else:
        print(diagnostics.doctor_text(issues), end="")
    if diagnostics.has_blocking_issue(issues):
        return CommandFailed(exit_code=4).exit_code
    if args.strict and diagnostics.has_warning_issue(issues):
        return CommandFailed(exit_code=6).exit_code
    return CommandOk().exit_code


def _checks_main(argv: Sequence[str]) -> int:
    args = parse_doctor_checks_args(argv)
    cwd = Path(args.cwd) if args.cwd is not None else Path.cwd()
    output_format = args.format or ("text" if sys.stdout.isatty() else "json")
    if output_format == "json":
        print(json.dumps(check_suggestions.suggestions_payload(cwd), indent=2, sort_keys=True))
    else:
        print(check_suggestions.render_suggestions_text(cwd), end="")
    return CommandOk().exit_code


def _doctor_artifact_dir(args, profile: profiles.Profile) -> Path:
    artifact_dir = (
        args.artifact_dir if args.artifact_dir is not None else profile.output.artifact_dir
    )
    if artifact_dir is not None:
        return Path(artifact_dir)
    return default_artifact_dir()


def profile_routed_harnesses(
    profile: profiles.Profile,
    *,
    include_disabled_routes: bool = False,
) -> tuple[str, ...]:
    if not include_disabled_routes and (
        not profile.triage.enabled or not profile.triage.routing.enabled
    ):
        return ()
    return tuple(route.harness for route in profile.triage.routes.values())


def _route_timeout_issues(
    profile: profiles.Profile,
    *,
    include_disabled_routes: bool = False,
) -> list[diagnostics.DiagnosticIssue]:
    if not include_disabled_routes and (
        not profile.triage.enabled or not profile.triage.routing.enabled
    ):
        return []
    issues: list[diagnostics.DiagnosticIssue] = []
    for route_name, route in sorted(profile.triage.routes.items()):
        if route.timeout_seconds != 0:
            continue
        issues.append(
            diagnostics.DiagnosticIssue(
                code="revrem.preflight.route_timeout_disabled",
                severity="warn",
                message=f"Route {route_name!r} remediation timeout is disabled.",
                hint=(
                    "Prefer bounded route timeouts for unattended runs; CLI "
                    "--timeout-seconds can cap routed remediation for watched runs."
                ),
                evidence={"route": route_name, "timeout_seconds": route.timeout_seconds},
            )
        )
    return issues


def _drop_ok_if_other_issues(
    issues: list[diagnostics.DiagnosticIssue],
) -> list[diagnostics.DiagnosticIssue]:
    if len(issues) <= 1:
        return issues
    return [issue for issue in issues if issue.code != "revrem.preflight.ok"]


def _suppression_doctor_issues(cwd: Path) -> list[diagnostics.DiagnosticIssue]:
    issues: list[diagnostics.DiagnosticIssue] = []
    for path in (suppressions.user_suppressions_path(), suppressions.repo_suppressions_path(cwd)):
        try:
            expired, unsupported = suppressions.stale_entries(path)
        except (OSError, ValueError) as exc:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.suppressions.invalid_file",
                    severity="warn",
                    message="A suppression file could not be parsed or read.",
                    hint=str(exc),
                    evidence={"path": str(path)},
                )
            )
            continue
        if expired:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.suppressions.expired",
                    severity="warn",
                    message="A suppression file contains expired entries.",
                    hint="Run revrem suppress expire for the affected scope.",
                    evidence={
                        "path": str(path),
                        "fingerprints": [entry.fingerprint for entry in expired],
                    },
                )
            )
        if unsupported:
            issues.append(
                diagnostics.DiagnosticIssue(
                    code="revrem.suppressions.unsupported_fingerprint_version",
                    severity="warn",
                    message="A suppression file contains fingerprints RevRem cannot match.",
                    hint="Recreate these suppressions after the fingerprint migration tool exists.",
                    evidence={
                        "path": str(path),
                        "fingerprints": [entry.fingerprint for entry in unsupported],
                    },
                )
            )
    return issues
