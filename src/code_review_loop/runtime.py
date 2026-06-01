"""Runtime exceptions and operator-facing summary formatting."""

from __future__ import annotations

import copy
import ntpath
import posixpath
import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

from code_review_loop.core.outcome import OutcomeFailed, RunOutcome
from code_review_loop.core.ports import CommandResult

Runner = Callable[[Sequence[str], Path, str | None, float | None], CommandResult]


@dataclass(frozen=True)
class RunnerResult:
    """Typed private runner result with an explicit summary projection."""

    summary: Mapping[str, object]
    outcome: RunOutcome

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy(dict(self.summary))


class RunLoopFailed(RuntimeError):
    """Raised when a bounded loop finishes with an expected step failure."""

    def __init__(self, summary: dict[str, object], message: str, *, outcome: OutcomeFailed):
        super().__init__(message)
        self._summary = copy.deepcopy(summary)
        self.outcome = outcome

    @property
    def summary(self) -> dict[str, object]:
        return copy.deepcopy(self._summary)


def _artifact_filename(path: object) -> str:
    if isinstance(path, PurePath):
        return path.name
    text = str(path)
    return ntpath.basename(posixpath.basename(text))


def format_terminal_summary(summary: dict[str, object]) -> str:
    artifact_dir = str(summary.get("artifact_dir") or "")
    status = str(summary.get("final_status") or "unknown")
    reason = str(summary.get("stopped_reason") or "unknown")
    lines = [
        f"Review-remediation loop: {status} ({reason})",
        f"Artifacts: {artifact_dir}",
    ]
    history_path = summary.get("history_path")
    if history_path:
        lines.append(f"Run history: {history_path}")
    phase_config = summary.get("phase_config")
    if isinstance(phase_config, dict):
        lines.append(f"Phase config: {_phase_config_summary(phase_config)}")

    iterations = summary.get("iterations")
    if isinstance(iterations, list) and iterations:
        lines.append("Iterations:")
        for item in iterations:
            if not isinstance(item, dict):
                continue
            iteration = item.get("iteration")
            review_status = item.get("review_status", "unknown")
            check_failures = item.get("check_failures")
            check_text = "checks not run" if check_failures is None else f"check failures: {check_failures}"
            failed = " remediation failed" if item.get("remediation_failed") else ""
            commit_status = item.get("commit_status")
            commit_text = f", commit={commit_status}" if commit_status else ""
            commit_failed = " commit failed" if item.get("commit_failed") else ""
            lines.append(
                f"  {iteration}: review={review_status}, {check_text}{failed}"
                f"{commit_text}{commit_failed}"
            )

    artifact_paths = summary.get("artifact_paths")
    if isinstance(artifact_paths, dict):
        reviews = artifact_paths.get("reviews")
        last_messages = artifact_paths.get("last_messages")
        checks = artifact_paths.get("checks")
        if isinstance(reviews, list) and reviews:
            lines.append(f"Latest review: {reviews[-1]}")
            if status == "findings":
                lines.append(f"Continue command: {_resume_command(summary, str(reviews[-1]))}")
        if isinstance(last_messages, list) and last_messages:
            lines.append(f"Latest remediation summary: {last_messages[-1]}")
        if isinstance(checks, list) and checks:
            latest_checks = _latest_iteration_checks([str(path) for path in checks])
            check_rows = _latest_check_rows(summary, latest_checks)
            if check_rows:
                lines.append("Latest check status:")
                for row in check_rows:
                    status_text = str(row.get("status", "unknown"))
                    command = str(row.get("command", "check"))
                    path = str(row.get("path", ""))
                    lines.append(f"  - {status_text}: {command} ({path})")
            else:
                lines.append("Latest check output artifacts:")
                for path in latest_checks:
                    lines.append(f"  - {path}")
        commits = artifact_paths.get("commits")
        if isinstance(commits, list) and commits:
            commit_outputs = [
                str(path)
                for path in commits
                if re.fullmatch(r"commit-\d+\.txt", _artifact_filename(path))
            ]
            lines.append(f"Latest commit artifact: {(commit_outputs or commits)[-1]}")
        summary_path = artifact_paths.get("summary")
        if summary_path:
            lines.append(f"JSON summary: {summary_path}")

    excerpt = str(summary.get("latest_review_excerpt") or "").strip()
    if excerpt and status != "clear":
        lines.append("")
        lines.append("Latest actionable review output:")
        lines.append(excerpt)

    if summary.get("error"):
        lines.append("")
        lines.append(f"Error: {summary['error']}")

    unexpected = summary.get("unexpected_behaviors")
    if isinstance(unexpected, list) and unexpected:
        lines.append("")
        lines.append("WARNING: unexpected loop behavior detected.")
        lines.append("Review status was classified as unknown during this run.")
        bug_report_path = summary.get("bug_report_path")
        if bug_report_path:
            lines.append(f"Bug report details: {bug_report_path}")

    return "\n".join(lines)


def _phase_config_summary(phase_config: dict[object, object]) -> str:
    parts: list[str] = []
    for phase in ("review", "triage", "remediation", "commit_message"):
        value = phase_config.get(phase)
        if not isinstance(value, dict):
            continue
        source = value.get("source")
        source_text = f"source={source}" if isinstance(source, str) and source else None
        if value.get("enabled") is False:
            parts.append(f"{phase}=disabled({source_text})" if source_text else f"{phase}=disabled")
            continue
        details = [
            str(item)
            for item in (
                value.get("harness"),
                value.get("model"),
                f"effort={value['reasoning_effort']}" if value.get("reasoning_effort") else None,
                f"timeout={value['timeout_seconds']}" if value.get("timeout_seconds") is not None else None,
                source_text,
            )
            if item
        ]
        parts.append(f"{phase}({', '.join(details)})")
    return "; ".join(parts) if parts else "not recorded"


def _resume_command(summary: dict[str, object], review_path: str) -> str:
    resume_config = summary.get("resume_config")
    config = resume_config if isinstance(resume_config, dict) else {}
    command = ["./.venv/bin/revrem"]
    base = config.get("base") or summary.get("base")
    if isinstance(base, str) and base:
        command.extend(["--base", base])
    max_iterations = config.get("max_iterations") or summary.get("max_iterations")
    if isinstance(max_iterations, int):
        command.extend(["--max-iterations", str(max_iterations)])
    profile = summary.get("profile")
    if isinstance(profile, str) and profile:
        command.extend(["--profile", profile])
    elif isinstance(config.get("check_commands"), list):
        for check in config["check_commands"]:
            if isinstance(check, str) and check:
                command.extend(["--check", check])
    timeout_seconds = config.get("timeout_seconds")
    if isinstance(timeout_seconds, int | float):
        command.extend(["--timeout-seconds", _format_number(timeout_seconds)])
    _append_phase_resume_overrides(command, config, summary)
    commit_after = config.get("commit_after_remediation")
    if isinstance(commit_after, bool):
        command.append("--commit-after-remediation" if commit_after else "--no-commit-after-remediation")
    command.extend(["--initial-review-file", review_path])
    hook_policy = config.get("commit_on_hook_failure") or summary.get("commit_on_hook_failure")
    if isinstance(hook_policy, str) and hook_policy:
        command.extend(["--commit-on-hook-failure", hook_policy])
    return shlex.join(command)


def _append_phase_resume_overrides(
    command: list[str],
    config: Mapping[object, object],
    summary: Mapping[str, object],
) -> None:
    phase_config = summary.get("phase_config")
    phase_config_map = phase_config if isinstance(phase_config, dict) else {}
    profile = summary.get("profile")
    profile_selected = isinstance(profile, str) and bool(profile)
    _append_string_override(
        command,
        "--review-harness",
        config.get("review_harness"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "review", "harness"),
        default="codex",
    )
    _append_string_override(
        command,
        "--review-model",
        config.get("review_model"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "review", "model"),
    )
    _append_string_override(
        command,
        "--review-reasoning-effort",
        config.get("review_reasoning_effort"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "review", "reasoning_effort"),
    )
    _append_string_override(
        command,
        "--remediation-harness",
        config.get("remediation_harness"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "remediation", "harness"),
        default="codex",
    )
    _append_string_override(
        command,
        "--remediation-model",
        config.get("remediation_model"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "remediation", "model"),
    )
    _append_string_override(
        command,
        "--remediation-reasoning-effort",
        config.get("remediation_reasoning_effort"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "remediation", "reasoning_effort"),
    )
    _append_string_override(
        command,
        "--commit-message-model",
        config.get("commit_message_model"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "commit_message", "model"),
    )
    _append_string_override(
        command,
        "--commit-message-harness",
        config.get("commit_message_harness"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "commit_message", "harness"),
    )
    _append_string_override(
        command,
        "--commit-reasoning-effort",
        config.get("commit_reasoning_effort"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "commit_message", "reasoning_effort"),
    )
    _append_bool_override(
        command,
        true_flag="--triage",
        false_flag="--no-triage",
        value=config.get("triage_enabled"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "enabled"),
    )
    _append_string_override(
        command,
        "--triage-contract",
        config.get("triage_contract"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "contract"),
        default="v1",
    )
    _append_string_override(
        command,
        "--triage-model",
        config.get("triage_model"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "model"),
    )
    _append_string_override(
        command,
        "--triage-harness",
        config.get("triage_harness"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "harness"),
        default="codex",
    )
    _append_string_override(
        command,
        "--triage-reasoning-effort",
        config.get("triage_reasoning_effort"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "reasoning_effort"),
    )
    _append_number_override(
        command,
        "--triage-timeout-seconds",
        config.get("triage_timeout_seconds"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "timeout_seconds"),
    )
    _append_bool_override(
        command,
        true_flag="--routing",
        false_flag="--no-routing",
        value=config.get("routing_enabled"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "routing_enabled"),
    )
    _append_bool_override(
        command,
        true_flag="--routing-strict",
        false_flag="--no-routing-strict",
        value=config.get("routing_strict"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "routing_strict"),
    )
    _append_string_override(
        command,
        "--route",
        config.get("routing_default_route"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "routing_default_route"),
    )
    _append_bool_override(
        command,
        true_flag="--allow-model-escalation",
        false_flag="--no-allow-model-escalation",
        value=config.get("allow_model_escalation"),
        profile_selected=profile_selected,
        source=_phase_field_source(phase_config_map, "triage", "allow_model_escalation"),
    )


def _phase_field_source(phase_config: Mapping[object, object], phase: str, field: str) -> str | None:
    value = phase_config.get(phase)
    if not isinstance(value, dict):
        return None
    sources = value.get("sources")
    if isinstance(sources, dict):
        source = sources.get(field)
        if isinstance(source, str):
            return source
    source = value.get("source")
    return source if isinstance(source, str) else None


def _should_emit_resume_override(
    value: object,
    *,
    profile_selected: bool,
    source: str | None,
    default: object = None,
) -> bool:
    if value is None:
        return False
    if source == "cli":
        return True
    if value == default:
        return False
    return not profile_selected


def _append_string_override(
    command: list[str],
    flag: str,
    value: object,
    *,
    profile_selected: bool,
    source: str | None,
    default: object = None,
) -> None:
    if isinstance(value, str) and value and _should_emit_resume_override(
        value,
        profile_selected=profile_selected,
        source=source,
        default=default,
    ):
        command.extend([flag, value])


def _append_number_override(
    command: list[str],
    flag: str,
    value: object,
    *,
    profile_selected: bool,
    source: str | None,
) -> None:
    if isinstance(value, int | float) and _should_emit_resume_override(
        value,
        profile_selected=profile_selected,
        source=source,
    ):
        command.extend([flag, _format_number(value)])


def _append_bool_override(
    command: list[str],
    *,
    true_flag: str,
    false_flag: str,
    value: object,
    profile_selected: bool,
    source: str | None,
) -> None:
    if not isinstance(value, bool):
        return
    if source == "cli":
        command.append(true_flag if value else false_flag)
    elif not profile_selected and value:
        command.append(true_flag)


def _format_number(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _latest_iteration_checks(paths: list[str]) -> list[str]:
    latest_iteration = -1
    parsed: list[tuple[int, str]] = []
    for path in paths:
        match = re.search(r"check-(\d+)-\d+\.txt$", _artifact_filename(path))
        if not match:
            continue
        iteration = int(match.group(1))
        latest_iteration = max(latest_iteration, iteration)
        parsed.append((iteration, path))
    if latest_iteration < 0:
        return paths
    return [path for iteration, path in parsed if iteration == latest_iteration]


def _latest_check_rows(summary: dict[str, object], latest_paths: list[str]) -> list[dict[str, object]]:
    iterations = summary.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        return []
    latest = next((item for item in reversed(iterations) if isinstance(item, dict) and isinstance(item.get("checks"), list)), None)
    if not isinstance(latest, dict):
        return []
    checks = latest.get("checks")
    if not isinstance(checks, list):
        return []
    path_by_name = {_artifact_filename(path): path for path in latest_paths}
    rows: list[dict[str, object]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        artifact = item.get("artifact")
        row = dict(item)
        if isinstance(artifact, str):
            row["path"] = path_by_name.get(artifact, artifact)
        rows.append(row)
    return rows
