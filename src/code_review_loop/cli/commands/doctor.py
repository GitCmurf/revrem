"""``revrem doctor`` subcommand (REVREM-TASK-003 Wave C1a).

Runs preflight diagnostics. ``_doctor_artifact_dir``,
``_suppression_doctor_issues``, ``profile_routed_harnesses`` and
``profile_or_default`` remain in ``code_review_loop.cli`` for C1a and are looked
up lazily so existing ``monkeypatch.setattr(MODULE, …)`` test patches stay in
effect.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import diagnostics

from ..outcome import CommandFailed, CommandOk


def main(argv: Sequence[str]) -> int:
    from code_review_loop import loop as _cli  # late import; preserves monkeypatching

    args = _cli.parse_doctor_args(argv)
    try:
        profile = _cli.profile_or_default(args.profile, Path.cwd(), require_implemented=False)
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
        artifact_dir = _cli._doctor_artifact_dir(args, profile)
        issues = diagnostics.run_doctor(
            diagnostics.DoctorConfig(
                cwd=Path.cwd(),
                base=args.base if args.base is not None else profile.pipeline.base,
                artifact_dir=artifact_dir,
                artifact_dir_is_default=args.artifact_dir is None and profile.output.artifact_dir is None,
                codex_bin=args.codex_bin if args.codex_bin is not None else profile.runtime.codex_bin,
                review_harness=profile.review.harness,
                remediation_harness=profile.remediation.harness,
                triage_enabled=profile.triage.enabled,
                triage_harness=profile.triage.harness,
                commit_message_harness=profile.commit.harness,
                routed_harnesses=_cli.profile_routed_harnesses(profile),
                harness_executables=profile.runtime.harness_executables,
                check_commands=tuple(args.check) if args.check is not None else profile.pipeline.checks,
                commit_after_remediation=args.commit_after_remediation or profile.commit.enabled,
                review_timeout_seconds=profile.review.timeout_seconds,
                remediation_timeout_seconds=profile.remediation.timeout_seconds,
                triage_timeout_seconds=(
                    profile.triage.timeout_seconds if profile.triage.enabled else None
                ),
            )
        )
        issues.extend(_cli._suppression_doctor_issues(Path.cwd()))
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
