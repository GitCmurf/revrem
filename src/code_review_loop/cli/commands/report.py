"""``revrem report`` subcommand (REVREM-PLAN-005 T1).

Renders a finished RevRem run into a single self-contained HTML report, or a
machine-readable JSON index, reading ``summary.json`` + ``events.jsonl`` only.
Never invokes a model or touches the network (gate G5).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import artifacts, events
from code_review_loop.cli.args import parse_report_args
from code_review_loop.report_html import build_report_index, render_report

from ..outcome import CommandFailed, CommandOk

_SUMMARY_FILENAME = "summary.json"


def _load_triage_findings(
    summary: dict, run_dir: Path
) -> list[dict] | None:
    """Load the latest parsed ``triage-N.json`` payload referenced by ``summary``.

    ``summary.artifact_paths.triage`` is a list of paths (the engine's real
    location; highest N is authoritative). Referenced paths must remain inside
    the run dir. Missing/unreadable/out-of-scope artifacts are skipped
    gracefully — the report renders with whatever triage is available. Returns
    ``None`` when no triage artifacts are referenced or loaded, so the renderer
    treats it as "no triage" (honest, not an empty-list false positive).
    """
    artifact_paths = summary.get("artifact_paths") or {}
    triage_paths = artifact_paths.get("triage") or []
    if not isinstance(triage_paths, list) or not triage_paths:
        return None
    loaded: list[tuple[tuple[int, int], dict]] = []
    for index, raw in enumerate(triage_paths):
        if not isinstance(raw, str) or not raw:
            continue
        candidate = _scoped_run_artifact_path(run_dir, raw)
        if candidate is None:
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            loaded.append((_triage_sort_key(raw, index), payload))
    if not loaded:
        return None
    _key, payload = max(loaded, key=lambda item: item[0])
    return [payload]


def _scoped_run_artifact_path(run_dir: Path, raw_path: str) -> Path | None:
    """Resolve a summary artifact path only if it stays inside ``run_dir``."""
    raw = Path(raw_path)
    try:
        root = run_dir.resolve()
        candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def _triage_sort_key(raw_path: str, index: int) -> tuple[int, int]:
    """Sort triage artifacts by numeric ``triage-N`` suffix, then list order."""
    stem = Path(raw_path).stem
    prefix = "triage-"
    if stem.startswith(prefix):
        suffix = stem.removeprefix(prefix)
        if suffix.isdigit():
            return (int(suffix), index)
    return (-1, index)


def main(argv: Sequence[str]) -> int:
    args = parse_report_args(argv)
    if args.no_redact and not args.i_understand_the_risks:
        print("ERROR: --no-redact requires --i-understand-the-risks", file=sys.stderr)
        return CommandFailed(exit_code=4).exit_code

    run_dir = Path(args.run_dir)
    summary_path = run_dir / _SUMMARY_FILENAME
    events_path = run_dir / events.EVENTS_FILENAME
    redact = not args.no_redact

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise ValueError(
                f"expected a JSON object at the top level, got {type(summary).__name__}"
            )
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read {summary_path}: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code

    truncated = False
    try:
        event_records, truncated = events.read_events(events_path)
    except OSError as exc:
        print(f"ERROR: cannot read {events_path}: {exc}", file=sys.stderr)
        return CommandFailed(exit_code=1).exit_code
    except ValueError as exc:
        # A malformed event stream (seq gap, bad envelope) is diagnostic
        # information for the reader, not a reason to fail the render. The
        # report renders with an empty event set and warns; it never fails
        # the render on events (the report is diagnostic — see T1 step 4).
        event_records = []
        truncated = True
        print(
            f"WARNING: {events_path} is malformed ({exc}); report rendered "
            "from summary.json only.",
            file=sys.stderr,
        )

    # Load triage artifacts so findings render from their authoritative source
    # (triage-N.json::confirmed_findings), not the status_classification event
    # whose payload is only {message, summary}. The renderer stays pure: it
    # receives the parsed findings, never reads disk.
    triage_findings = _load_triage_findings(summary, run_dir)

    if args.format == "json":
        index = build_report_index(
            summary, event_records, redact=redact, triage_findings=triage_findings
        )
        canonical = artifacts.canonicalize_json(index)
        print(json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        html_report = render_report(
            summary, event_records, redact=redact, triage_findings=triage_findings
        )
        output_path = (
            Path(args.output)
            if args.output
            else run_dir / "report.html"
        )
        try:
            artifacts.write_text_artifact(output_path, html_report)
        except OSError as exc:
            print(f"ERROR: cannot write {output_path}: {exc}", file=sys.stderr)
            return CommandFailed(exit_code=1).exit_code
        print(str(output_path))

    if truncated and event_records:
        # A genuinely truncated stream (malformed line mid-read) yielded a
        # partial event set; the report rendered with what was available. The
        # fully-malformed case (ValueError -> empty event_records) already
        # printed its own "summary.json only" warning above and must not reach
        # here, or the two messages would contradict each other.
        print(
            f"WARNING: {events_path} was truncated; report rendered with the "
            "events available.",
            file=sys.stderr,
        )
    return CommandOk().exit_code
