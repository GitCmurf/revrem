"""Check-attempt summary helpers for the runner shell."""

from __future__ import annotations

import shlex

from code_review_loop.core.ports import CommandResult


def record_check_attempt(
    iteration_summary: dict[str, object],
    *,
    retry_count: int,
    artifact_stem: str,
    display_label: str,
    failed_commands: tuple[str, ...],
    check_results: list[CommandResult],
) -> None:
    check_rows = [
        {
            "command": shlex.join(result.args),
            "status": "passed" if result.returncode == 0 else "failed",
            "artifact": f"check-{artifact_stem}-{index}.txt",
        }
        for index, result in enumerate(check_results, start=1)
    ]
    if check_rows:
        iteration_summary["checks"] = check_rows
    attempts = iteration_summary.get("check_attempts")
    if retry_count == 0 and not failed_commands and not isinstance(attempts, list):
        return
    if not isinstance(attempts, list):
        attempts = []
        iteration_summary["check_attempts"] = attempts
    attempts.append(
        {
            "retry": retry_count,
            "artifact_label": artifact_stem,
            "display_label": display_label,
            "check_failures": len(failed_commands),
            "checks": check_rows,
        }
    )
