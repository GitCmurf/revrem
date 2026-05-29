"""Summary, artifact-path, and run-history reporting helpers."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from code_review_loop import __version__, artifacts, budgets, run_history
from code_review_loop.adapters.phase_support import write_artifact
from code_review_loop.clock import SYSTEM_CLOCK, Clock, utc_iso
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import EventSink


def add_artifact_paths(summary: dict[str, object], config: LoopConfig) -> None:
    artifact_dir = config.artifact_dir
    files = sorted(
        (path for path in artifact_dir.glob("*") if path.is_file()),
        key=artifact_sort_key,
    )
    summary["artifact_paths"] = {
        "artifact_dir": str(artifact_dir),
        "summary": str(artifact_dir / "summary.json"),
        "reviews": [
            str(path)
            for path in files
            if path.name.startswith("review-") and path.suffix == ".txt"
        ],
        "remediations": [
            str(path)
            for path in files
            if path.name.startswith("remediation-")
            and "last-message" not in path.name
            and not path.name.endswith("-prompt.txt")
        ],
        "prompts": [
            str(path)
            for path in files
            if path.name.startswith("remediation-") and path.name.endswith("-prompt.txt")
        ],
        "routing": [str(path) for path in files if path.name.startswith("routing-")],
        "triage": [str(path) for path in files if path.name.startswith("triage-")],
        "commits": [str(path) for path in files if path.name.startswith("commit-")],
        "last_messages": [
            str(path)
            for path in files
            if path.name.startswith("remediation-") and "last-message" in path.name
        ],
        "checks": [str(path) for path in files if path.name.startswith("check-")],
        "diagnostics": [
            str(path)
            for path in files
            if path.name == "diagnostics.json"
            or path.name.endswith("-status.json")
            or path.name.startswith("diagnostics-")
        ],
    }


def artifact_sort_key(path: Path) -> tuple[str, int, str]:
    name = path.name
    match = re.search(r"-(\d+)(?:-|\.txt$)", name)
    if match:
        return (name.split("-", 1)[0], int(match.group(1)), name)
    if "initial" in name:
        return (name.split("-", 1)[0], 0, name)
    if "final" in name:
        return (name.split("-", 1)[0], 1_000_000, name)
    return (name.split("-", 1)[0], 999_999, name)


def write_summary(
    config: LoopConfig,
    summary: dict[str, object],
    *,
    clock: Clock = SYSTEM_CLOCK,
    budget_state: budgets.BudgetState | None = None,
    event_sink: EventSink | None = None,
) -> None:
    update_unexpected_behaviors(config, summary)
    add_summary_contract_fields(config, summary, clock=clock)
    add_artifact_paths(summary, config)
    if budget_state is not None or "budgets" not in summary:
        summary["budgets"] = summary_budget_payload(config, budget_state=budget_state)
    if event_sink is not None:
        emit_artifact_write_events(config, summary, event_sink=event_sink)
        summary_detail = summary.get("stopped_reason") or summary.get("final_status") or "summary"
        event_sink.emit("summary", payload={"summary": str(summary_detail)})
    artifacts.write_json_artifact(config.artifact_dir, "summary.json", summary)


def summary_budget_payload(
    config: LoopConfig,
    *,
    budget_state: budgets.BudgetState | None = None,
) -> dict[str, object]:
    tokens = None
    usd = None
    wall_elapsed_seconds = None
    if budget_state is not None:
        wall_elapsed_seconds = budgets.wall_elapsed_seconds(budget_state)
        if budget_state.tokens_reported:
            tokens = budget_state.tokens_used
        if budget_state.usd_reported:
            usd = str(budget_state.usd_used)
    return {
        "max_wall_seconds": config.budget_config.max_wall_seconds,
        "max_tokens": config.budget_config.max_tokens,
        "max_usd": str(config.budget_config.max_usd) if config.budget_config.max_usd is not None else None,
        "soft_warn_fraction": config.budget_config.soft_warn_fraction,
        "wall_elapsed_seconds": wall_elapsed_seconds,
        "tokens": tokens,
        "usd": usd,
    }


def emit_artifact_write_events(config: LoopConfig, summary: dict[str, object], *, event_sink: EventSink) -> None:
    artifact_paths = summary.get("artifact_paths")
    if not isinstance(artifact_paths, dict):
        return
    for kind, path in iter_artifact_paths(artifact_paths):
        payload: dict[str, object] = {"kind": kind, "path": path}
        with suppress(OSError):
            payload["bytes"] = Path(path).stat().st_size
        event_sink.emit("artifact_write", phase="artifacts", payload=payload)


def iter_artifact_paths(artifact_paths: dict[object, object]) -> Iterator[tuple[str, str]]:
    for kind, value in artifact_paths.items():
        if kind == "artifact_dir":
            continue
        if isinstance(kind, str) and isinstance(value, str):
            yield kind, value
        elif isinstance(kind, str) and isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield kind, item


def add_summary_contract_fields(
    config: LoopConfig, summary: dict[str, object], *, clock: Clock = SYSTEM_CLOCK
) -> None:
    summary["schema_version"] = artifacts.JSON_SCHEMA_VERSION
    summary.setdefault("cli_version", __version__)
    summary.setdefault("harness", config.review_harness)
    summary.setdefault("harness_version", None)
    summary.setdefault("command_line", list(config.command_line) if config.command_line else None)
    summary.setdefault("phase_config", phase_config_payload(config))
    summary.setdefault("tokens", None)
    summary.setdefault("usd", None)
    iterations = summary.get("iterations")
    summary.setdefault(
        "phases",
        {
            "_summary": {
                "iteration_count": len(iterations) if isinstance(iterations, list) else 0,
            },
        },
    )
    summary.setdefault("finished_at", utc_iso(clock.now()))
    summary.setdefault("duration_seconds", _summary_duration_seconds(summary))


def phase_config_payload(config: LoopConfig) -> dict[str, object]:
    return {
        "review": {
            "harness": config.review_harness,
            "model": config.review_model or config.model,
            "reasoning_effort": config.review_reasoning_effort or config.reasoning_effort,
            "timeout_seconds": config.review_timeout_seconds,
        },
        "triage": {
            "enabled": config.triage_enabled,
            "harness": config.triage_harness,
            "model": config.triage_model,
            "reasoning_effort": config.triage_reasoning_effort,
            "timeout_seconds": config.triage_timeout_seconds,
            "contract": config.triage_contract,
            "routing_enabled": (
                config.profile_v2.triage.routing.enabled
                if config.profile_v2 is not None
                else False
            ),
        },
        "remediation": {
            "harness": config.remediation_harness,
            "model": config.remediation_model or config.model,
            "reasoning_effort": config.remediation_reasoning_effort or config.reasoning_effort,
            "timeout_seconds": config.remediation_timeout_seconds,
            "sandbox": config.exec_sandbox,
        },
        "commit_message": {
            "enabled": config.commit_after_remediation,
            "harness": config.commit_message_harness,
            "model": config.commit_message_model,
            "reasoning_effort": config.commit_reasoning_effort,
            "timeout_seconds": config.commit_timeout_seconds,
        },
        "checks": {
            "commands": list(config.check_commands),
            "timeout_seconds": config.timeout_seconds,
        },
    }


def _summary_duration_seconds(summary: dict[str, object]) -> float | None:
    started_at = summary.get("started_at")
    finished_at = summary.get("finished_at")
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds())


def update_unexpected_behaviors(config: LoopConfig, summary: dict[str, object]) -> None:
    iterations = summary.get("iterations")
    if not isinstance(iterations, list):
        return
    unknowns = [
        item
        for item in iterations
        if isinstance(item, dict) and item.get("review_status") == "unknown"
    ]
    if not unknowns:
        summary.pop("unexpected_behaviors", None)
        summary.pop("bug_report_path", None)
        return

    report_path = config.artifact_dir / "unexpected-behavior-report.txt"
    behaviors: list[dict[str, object]] = []
    lines = [
        "RevRem unexpected behavior report",
        "",
        "A review status was classified as unknown during this run.",
        "Please include this file and the referenced review/status artifacts in a bug report.",
        "",
        f"run_id: {summary.get('run_id')}",
        f"base: {summary.get('base')}",
        f"final_status: {summary.get('final_status')}",
        f"stopped_reason: {summary.get('stopped_reason')}",
        f"artifact_dir: {summary.get('artifact_dir')}",
        "",
        "Unknown review iterations:",
    ]
    for item in unknowns:
        iteration = item.get("iteration")
        review_path = config.artifact_dir / f"review-{iteration}.txt"
        status_path = config.artifact_dir / f"review-{iteration}-status.json"
        behavior = {
            "kind": "unknown_review_status",
            "iteration": iteration,
            "review_path": str(review_path),
        }
        if status_path.is_file():
            behavior["status_diagnostics_path"] = str(status_path)
        behaviors.append(behavior)
        lines.append(f"- iteration {iteration}: {review_path}")
        if status_path.is_file():
            lines.append(f"  diagnostics: {status_path}")
    lines.append("")
    write_artifact(report_path, "\n".join(lines))
    summary["unexpected_behaviors"] = behaviors
    summary["bug_report_path"] = str(report_path)


def append_run_history(summary: dict[str, object], config: LoopConfig) -> Path:
    history_path = run_history.append_history(summary, cwd=config.cwd)
    summary["history_path"] = str(history_path)
    write_summary(config, summary)
    return history_path
