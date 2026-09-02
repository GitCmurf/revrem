"""Aggregate model telemetry from local per-run summaries."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from code_review_loop import run_history
from code_review_loop.cli.args import parse_stats_args
from code_review_loop.cli.outcome import CommandFailed, CommandOk
from code_review_loop.repo_roots import repo_root_or_cwd


def main(argv: Sequence[str]) -> int:
    args = parse_stats_args(argv)
    if args.limit < 1:
        print("ERROR: --limit must be at least 1", file=__import__("sys").stderr)
        return CommandFailed(exit_code=1).exit_code
    repo = None if args.all_repos else Path(args.repo or Path.cwd()).resolve()
    rows = _invocations(args.limit, repo=repo)
    rows = [row for row in rows if _matches(row, args)]
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("phase") or "provider-default"),
            str(row.get("harness") or "provider-default"),
            str(row.get("model") or "provider-default"),
            str(row.get("reasoning_effort") or "provider-default"),
        )
        grouped[key].append(row)
    payload = [_summarize(key, values) for key, values in sorted(grouped.items())]
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not payload:
        print("No matching model invocations found in local run artifacts.")
    else:
        print("PHASE          HARNESS  MODEL            EFFORT  CALLS  OK  TOKEN_COVERAGE  MEAN    P95")
        for item in payload:
            print(f"{item['phase']:<14} {item['harness']:<8} {item['model']:<16} {item['reasoning_effort']:<7} {item['calls']:>5} {item['ok']:>3} {item['token_coverage']:<14} {item['duration_seconds']['mean']:>6.1f}s {item['duration_seconds']['p95']:>6.1f}s")
    return CommandOk().exit_code


def _invocations(limit: int, *, repo: Path | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    requested_repo = repo_root_or_cwd(repo) if repo is not None else None
    # Apply repository filtering before truncating by `--limit` so older local
    # runs from the same repository remain visible.
    records = (
        run_history.read_history()
        if requested_repo is not None
        else run_history.read_history(limit=limit)
    )
    matched_records = 0
    for record in records:
        raw_cwd = record.get("cwd")
        # A missing cwd must never resolve to the caller's repository. It
        # cannot establish ownership or resolve a relative artifact safely.
        if not isinstance(raw_cwd, str) or not raw_cwd.strip():
            continue
        record_cwd = Path(raw_cwd).resolve()
        if requested_repo is not None:
            if repo_root_or_cwd(record_cwd) != requested_repo:
                continue
            matched_records += 1
        summary_path = record.get("summary_path")
        if not summary_path:
            continue
        resolved_summary_path = _resolve_summary_path(
            str(summary_path),
            record_cwd,
        )
        if resolved_summary_path is None:
            continue
        try:
            summary = json.loads(resolved_summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(summary, dict):
            continue
        values = summary.get("model_invocations", [])
        if isinstance(values, list):
            result.extend(item for item in values if isinstance(item, dict))
        if requested_repo is not None and limit is not None and matched_records >= limit:
            break
    return result


def _resolve_summary_path(value: str, record_cwd: Path) -> Path | None:
    path = Path(value)
    candidates = [path] if path.is_absolute() else [record_cwd / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _matches(row: dict[str, Any], args: Any) -> bool:
    return all(not expected or row.get(field) == expected for field, expected in (("phase", args.phase), ("harness", args.harness), ("model", args.model)))


def _summarize(key: tuple[str, str, str, str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    durations = sorted(_duration_seconds(row.get("duration_seconds")) for row in rows)
    tokens = [
        row["tokens"]
        for row in rows
        if isinstance(row.get("tokens"), int) and not isinstance(row.get("tokens"), bool)
    ]
    p95_index = max(0, min(len(durations) - 1, math.ceil(0.95 * len(durations)) - 1))
    return {
        "phase": key[0], "harness": key[1], "model": key[2], "reasoning_effort": key[3],
        "calls": len(rows), "ok": sum(row.get("outcome") == "ok" for row in rows),
        "token_coverage": f"{len(tokens)}/{len(rows)}", "tokens": sum(tokens) if tokens else None,
        "duration_seconds": {"min": min(durations), "mean": statistics.fmean(durations), "p50": statistics.median(durations), "p95": durations[p95_index], "max": max(durations)},
    }


def _duration_seconds(value: object) -> float:
    """Normalize malformed local telemetry durations for best-effort stats."""
    if isinstance(value, bool):
        return 0.0  # outcome-exempt: telemetry value, not a command exit code
    if not isinstance(value, (int, float, str)):
        return 0.0  # outcome-exempt: malformed telemetry is excluded from stats
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 0.0  # outcome-exempt: telemetry value, not a command exit code
    return duration if math.isfinite(duration) else 0.0
