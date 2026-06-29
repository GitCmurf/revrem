from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VOLATILE_KEYS = frozenset(
    {
        "actual",
        "artifact",
        "artifact_dir",
        "artifact_paths",
        "base_commit",
        "bug_report_path",
        "bytes",
        "command_line",
        "cwd",
        "diagnostic_artifact",
        "duration_seconds",
        "elapsed",
        "finished_at",
        "git_state",
        "head",
        "history_path",
        "invocation",
        "merge_base",
        "message",
        "path",
        "phase_observations",
        "prompt_artifact",
        "run_id",
        "session_id",
        "started_at",
        "terminal_excerpt_chars",
        "tokens",
        "usd",
        "wall_elapsed_seconds",
        "workdir",
    }
)
VOLATILE_KEY_FRAGMENTS = ("_at", "_path", "_paths", "artifact", "duration")
STABLE_SUMMARY_KEYS = frozenset(
    {
        "checks",
        "cli_version",
        "final_status",
        "iterations",
        "max_iterations",
        "pending_check_failures",
        "profile",
        "schema_version",
        "stopped_reason",
        "triage_diagnostics",
        "unexpected_behaviors",
    }
)
STABLE_EVENT_KEYS = frozenset({"kind", "phase", "iteration", "payload", "schema_version"})
IGNORED_ARTIFACT_NAMES = frozenset({"events.jsonl", "invocation.json", "summary.json"})


def assert_equivalent_run_artifacts(cli_dir: Path, tui_dir: Path) -> None:
    """Assert stable CLI/TUI run artifacts are equivalent.

    Run artifacts intentionally include timestamps, run ids, absolute paths, and
    durations. The equivalence gate compares only the contractually meaningful
    run shape: terminal summary state, event sequence, and stable artifact names.
    """

    cli_signature = _run_signature(cli_dir)
    tui_signature = _run_signature(tui_dir)
    assert cli_signature == tui_signature, _format_diff(cli_signature, tui_signature)


def _run_signature(run_dir: Path) -> dict[str, Any]:
    return {
        "summary": _stable_summary(run_dir),
        "events": _stable_events(run_dir),
        "files": _stable_files(run_dir),
    }


def _stable_summary(run_dir: Path) -> dict[str, Any]:
    summary = _read_json(run_dir / "summary.json")
    return {
        key: _scrub(value)
        for key, value in summary.items()
        if key in STABLE_SUMMARY_KEYS
    }


def _stable_events(run_dir: Path) -> list[dict[str, Any]]:
    events_path = run_dir / "events.jsonl"
    records: list[dict[str, Any]] = []
    with events_path.open(encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            records.append(
                {
                    key: _scrub(value)
                    for key, value in payload.items()
                    if key in STABLE_EVENT_KEYS
                }
            )
    return records


def _stable_files(run_dir: Path) -> list[str]:
    return sorted(
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path.name not in IGNORED_ARTIFACT_NAMES
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _scrub(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _is_volatile_key(key):
        return "<volatile>"
    if isinstance(value, dict):
        return {
            str(item_key): _scrub(item_value, key=str(item_key))
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
            if not _is_volatile_key(str(item_key))
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str) and ("/" in value or "\\" in value):
        return "<path>"
    return value


def _is_volatile_key(key: str) -> bool:
    return key in VOLATILE_KEYS or any(fragment in key for fragment in VOLATILE_KEY_FRAGMENTS)


def _format_diff(cli_signature: dict[str, Any], tui_signature: dict[str, Any]) -> str:
    return (
        "CLI and TUI run artifacts diverged\n"
        "CLI:\n"
        f"{json.dumps(cli_signature, indent=2, sort_keys=True)}\n"
        "TUI:\n"
        f"{json.dumps(tui_signature, indent=2, sort_keys=True)}"
    )
