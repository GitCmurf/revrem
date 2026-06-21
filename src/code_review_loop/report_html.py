"""Static HTML report renderer for finished RevRem runs (REVREM-PLAN-005 T1).

Read-only: consumes the already-frozen ``summary.json`` (``summary-v1``) and
``events.jsonl`` (``events-v1``) of a finished run and renders them into a
single self-contained HTML file — plain HTML5 + inline ``<style>``, no JS, no
external assets — safe to upload as a CI artifact and open offline. Also
exposes a machine-readable JSON index (``build_report_index``) that is the
minimum payload a CI comment builder needs without re-reading raw events.

This module never invokes a model, touches the network, or re-runs a phase
(gate G5 extended to a new renderer). Redaction is on by default for anything
that leaves the run dir (gate G7): every interpolated string is passed through
``redaction.redact_text`` unless ``redact=False``.

The two public functions are pure (inputs -> str/dict, no disk I/O) so they
are trivially testable and deterministic: the same inputs always yield the
same bytes (timestamps are read from the inputs, never ``now()`` at render
time; filesystem paths are normalised to ``/`` via ``PurePosixPath``).
"""

from __future__ import annotations

import html
from pathlib import PurePosixPath
from typing import Any

from code_review_loop import __version__
from code_review_loop.events import Event
from code_review_loop.redaction import redact_text

REPORT_INDEX_SCHEMA_VERSION = "1.0"

# Distinct colours per terminal status, mirrored in the report-index enum.
_STATUS_COLOURS: dict[str, str] = {
    "clear": "#1a7f37",
    "findings": "#bf8700",
    "unknown": "#6e7781",
    "error": "#cf222e",
}

# Maps a run's final_status / stopped_reason to the documented exit code
# (Contract #6). The report surfaces the mapping; it never redefines it.
_EXIT_CODE_BY_STATUS: dict[str, int] = {
    "clear": 0,
    "findings": 2,
    "unknown": 2,
    "error": 1,
}


def _esc(value: object, *, redact: bool) -> str:
    """HTML-escape (and optionally redact) a single interpolated value."""
    text = "" if value is None else str(value)
    if redact:
        text = redact_text(text).text
    return html.escape(text, quote=True)


def _normalize_path(value: object) -> str:
    """Render a filesystem path with POSIX separators so ``os.sep`` never leaks.

    Determinism guard (Contract #9): a golden must be byte-stable across
    Linux/macOS, so any embedded path is rendered through ``PurePosixPath``.
    """
    if value is None:
        return ""
    return str(PurePosixPath(str(value)))


def _status_badge(final_status: str, *, redact: bool) -> str:
    colour = _STATUS_COLOURS.get(final_status, "#6e7781")
    label = _esc(final_status, redact=redact)
    return f'<span class="badge" style="background:{colour}">{label}</span>'


def _exit_code_for(summary: dict[str, Any]) -> int:
    """Map a run's terminal state to its documented exit code (display only)."""
    final_status = summary.get("final_status")
    if isinstance(final_status, str):
        return _EXIT_CODE_BY_STATUS.get(final_status, 1)
    return 1


def _phase_config_rows(summary: dict[str, Any], *, redact: bool) -> str:
    """Per-phase harness/model rows from ``summary.phase_config`` if present."""
    phase_config = summary.get("phase_config")
    if not isinstance(phase_config, dict) or not phase_config:
        return ""
    rows: list[str] = []
    for phase in sorted(phase_config):
        cfg = phase_config[phase]
        if not isinstance(cfg, dict):
            continue
        harness = cfg.get("harness", "")
        model = cfg.get("model", "")
        rows.append(
            "<tr>"
            f"<td>{_esc(phase, redact=redact)}</td>"
            f"<td>{_esc(harness, redact=redact)}</td>"
            f"<td>{_esc(model, redact=redact)}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    body = "".join(rows)
    return (
        '<section><h2>Phase configuration</h2>'
        '<table><thead><tr><th>Phase</th><th>Harness</th><th>Model</th>'
        '</tr></thead><tbody>'
        f"{body}"
        '</tbody></table></section>'
    )


def _header(summary: dict[str, Any], *, redact: bool) -> str:
    run_id = _esc(summary.get("run_id"), redact=redact)
    badge = _status_badge(str(summary.get("final_status", "")), redact=redact)
    base = _esc(summary.get("base"), redact=redact)
    head = _esc(summary.get("head"), redact=redact)
    profile = _esc(summary.get("profile"), redact=redact)
    harness = _esc(summary.get("harness"), redact=redact)
    duration = summary.get("duration_seconds")
    duration_text = "unknown" if duration is None else _esc(duration, redact=redact)
    exit_code = _exit_code_for(summary)
    exit_hint = _exit_hint(summary)
    started = _esc(summary.get("started_at"), redact=redact)
    finished = _esc(summary.get("finished_at"), redact=redact)
    return (
        '<header>'
        f'<h1>RevRem run <code>{run_id}</code></h1>'
        f'<p class="status">Final status: {badge}</p>'
        f'<p>Exit code: <code>{exit_code}</code>'
        f'{f" &mdash; {exit_hint}" if exit_hint else ""}</p>'
        "<dl>"
        f"<dt>Base ref</dt><dd>{base or '<em>unset</em>'}</dd>"
        f"<dt>HEAD</dt><dd>{head or '<em>unset</em>'}</dd>"
        f"<dt>Profile</dt><dd>{profile or '<em>none</em>'}</dd>"
        f"<dt>Harness</dt><dd>{harness or '<em>unknown</em>'}</dd>"
        f"<dt>Wall-clock</dt><dd>{duration_text}s</dd>"
        f"<dt>Started</dt><dd>{started or '<em>unknown</em>'}</dd>"
        f"<dt>Finished</dt><dd>{finished or '<em>unknown</em>'}</dd>"
        "</dl>"
        "</header>"
    )


def _exit_hint(summary: dict[str, Any]) -> str:
    reason = str(summary.get("stopped_reason") or "")
    if reason == "budget_ceiling_hit":
        return "budget ceiling reached"
    if reason == "cancelled":
        return "cancelled by operator"
    if reason == "review_failed" or reason == "setup_failed":
        return "error"
    return ""


def _outcome_summary(
    summary: dict[str, Any], events: list[Event], *, redact: bool
) -> str:
    reason = _esc(summary.get("stopped_reason"), redact=redact)
    iterations = summary.get("iterations") or []
    iteration_count = len(iterations) if isinstance(iterations, list) else 0
    check_pass = sum(
        1
        for ev in events
        if ev.kind == "check_result"
        and str(ev.payload.get("status", "")).lower() == "passed"
    )
    check_fail = sum(
        1
        for ev in events
        if ev.kind == "check_result"
        and str(ev.payload.get("status", "")).lower() == "failed"
    )
    suppressed = sum(1 for ev in events if ev.kind == "suppressed")
    return (
        '<section><h2>Outcome</h2><dl>'
        f"<dt>Stopped reason</dt><dd>{reason or '<em>none</em>'}</dd>"
        f"<dt>Iterations</dt><dd>{iteration_count}</dd>"
        f"<dt>Checks passed</dt><dd>{check_pass}</dd>"
        f"<dt>Checks failed</dt><dd>{check_fail}</dd>"
        f"<dt>Suppressed findings</dt><dd>{suppressed}</dd>"
        "</dl></section>"
    )


def _timeline(events: list[Event], *, redact: bool) -> str:
    """Compact ordered list of phase_start/phase_result events."""
    rows: list[str] = []
    for ev in events:
        if ev.kind not in ("phase_start", "phase_result"):
            continue
        phase = _esc(ev.phase, redact=redact)
        iteration = _esc(ev.iteration, redact=redact)
        status = _esc(ev.payload.get("status") or ev.payload.get("message"), redact=redact)
        rows.append(
            f'<li><span class="seq">{ev.seq}</span> '
            f'<span class="phase">{phase}</span> '
            f'<span class="iter">{iteration}</span> '
            f'<span class="kind">{ev.kind}</span> '
            f'<span class="detail">{status}</span></li>'
        )
    if not rows:
        return ""
    return (
        '<section><h2>Timeline</h2><ol class="timeline">'
        + "".join(rows)
        + "</ol></section>"
    )


def _findings_section(
    summary: dict[str, Any], events: list[Event], *, redact: bool
) -> str:
    """Findings & triage section.

    Source: ``status_classification`` events for configured findings, plus
    ``suppressed`` events for suppressed findings with provenance. The richer
    per-finding detail in a ``triage-N.json`` artifact is surfaced when the
    run dir contains one (T2 reads it via summary artifact_paths); otherwise
    the section renders the event-derived view honestly.
    """
    configured: list[str] = []
    for ev in events:
        if ev.kind != "status_classification":
            continue
        for severity in ("critical", "high", "medium", "low"):
            for item in ev.payload.get(severity, []) or []:
                if isinstance(item, dict):
                    summary_text = item.get("summary") or item.get("title") or ""
                    fingerprint = item.get("fingerprint", "")
                    configured.append(
                        f"<tr><td>{_esc(severity, redact=redact)}</td>"
                        f"<td>{_esc(item.get('path') or item.get('file') or '', redact=redact)}</td>"
                        f"<td>{_esc(summary_text, redact=redact)}</td>"
                        f"<td><code>{_esc(fingerprint, redact=redact)}</code></td></tr>"
                    )

    suppressed_rows: list[str] = []
    for ev in events:
        if ev.kind != "suppressed":
            continue
        message = ev.payload.get("message", "")
        suppressed_rows.append(
            f"<li>{_esc(message, redact=redact)} "
            f'<span class="placeholder">(suppressed)</span></li>'
        )

    artifact_hint = ""
    artifact_paths = summary.get("artifact_paths") or {}
    triage_artifacts = (
        artifact_paths.get("triage") or artifact_paths.get("triages") or []
    )
    if isinstance(triage_artifacts, list) and triage_artifacts:
        joined = ", ".join(_esc(_normalize_path(a), redact=redact) for a in triage_artifacts)
        artifact_hint = f'<p class="placeholder">Detailed triage: <code>{joined}</code></p>'

    parts = ['<section><h2>Findings &amp; triage</h2>']
    if configured:
        parts.append(
            '<table><thead><tr><th>Severity</th><th>Path</th>'
            '<th>Summary</th><th>Fingerprint</th></tr></thead><tbody>'
        )
        parts.extend(configured)
        parts.append("</tbody></table>")
    else:
        parts.append('<p class="placeholder">No configured findings recorded.</p>')

    if suppressed_rows:
        parts.append("<h3>Suppressed findings</h3><ul>")
        parts.extend(suppressed_rows)
        parts.append("</ul>")
    parts.append(artifact_hint)
    parts.append("</section>")
    return "".join(parts)


def _checks_section(events: list[Event], *, redact: bool) -> str:
    """Checks section from ``check_result`` events: command, status, message."""
    rows: list[str] = []
    for ev in events:
        if ev.kind != "check_result":
            continue
        command = ev.payload.get("command", "")
        status = str(ev.payload.get("status", "")).lower()
        message = ev.payload.get("message", "")
        status_class = "check-pass" if status == "passed" else "check-fail"
        rows.append(
            "<tr>"
            f'<td><code>{_esc(command, redact=redact)}</code></td>'
            f'<td class="{status_class}">{_esc(status, redact=redact)}</td>'
            f"<td>{_esc(message, redact=redact)}</td>"
            f"<td>{_esc(ev.iteration, redact=redact)}</td>"
            "</tr>"
        )
    if not rows:
        return (
            '<section><h2>Checks</h2>'
            '<p class="placeholder">No check results recorded.</p></section>'
        )
    return (
        '<section><h2>Checks</h2>'
        '<table><thead><tr><th>Command</th><th>Status</th>'
        '<th>Message</th><th>Iteration</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></section>"
    )


def _cost_section(
    summary: dict[str, Any], events: list[Event], *, redact: bool
) -> str:
    """Cost & budget section. Renders ``null`` honestly, never ``0``."""
    tokens = summary.get("tokens")
    usd = summary.get("usd")
    cost_charges = [ev for ev in events if ev.kind == "cost_charge"]
    ceiling_hits = [ev for ev in events if ev.kind == "cost_ceiling_hit"]

    def _fmt_tokens(t: object) -> str:
        if t is None:
            return '<em class="placeholder">not reported</em>'
        if isinstance(t, dict):
            if not t:
                return '<em class="placeholder">not reported</em>'
            return ", ".join(
                f"{_esc(k, redact=redact)}={_esc(v, redact=redact)}"
                for k, v in sorted(t.items())
            )
        return _esc(t, redact=redact)

    _not_reported = '<em class="placeholder">not reported</em>'
    usd_cell = _esc(usd, redact=redact) if usd is not None else _not_reported
    rows = [
        f"<dt>Tokens</dt><dd>{_fmt_tokens(tokens)}</dd>",
        f"<dt>USD</dt><dd>{usd_cell}</dd>",
        f"<dt>Charge events</dt><dd>{len(cost_charges)}</dd>",
    ]
    if ceiling_hits:
        ceiling = ceiling_hits[-1].payload
        rows.append(
            f"<dt>Budget ceiling</dt><dd>{_esc(ceiling.get('ceiling'), redact=redact)} "
            f"reached ({_esc(ceiling.get('actual'), redact=redact)} / "
            f"{_esc(ceiling.get('limit'), redact=redact)})</dd>"
        )
    return (
        '<section><h2>Cost &amp; budget</h2><dl>'
        + "".join(rows)
        + "</dl></section>"
    )


def _diff_stats_section(summary: dict[str, Any], *, redact: bool) -> str:
    """Diff stats from in-artifact data only. Never shells out to git.

    The summary may carry a diff-stat block under various keys; when absent the
    section renders "diff stats unavailable for this run" rather than
    recomputing from the worktree (the report must not shell out).
    """
    diff_stat = summary.get("diff_stat") or summary.get("diff_stats")
    if not diff_stat:
        return (
            '<section><h2>Diff stats</h2>'
            '<p class="placeholder">Diff stats unavailable for this run.</p>'
            "</section>"
        )
    return (
        '<section><h2>Diff stats</h2><pre>'
        + _esc(diff_stat, redact=redact)
        + "</pre></section>"
    )


_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1f2328;line-height:1.5}
code{background:#f6f8fa;padding:.1em .3em;border-radius:4px;font-size:.95em}
header h1{font-size:1.6rem;margin-bottom:.25rem}
.status{font-size:1.15rem}
.badge{color:#fff;padding:.15em .5em;border-radius:1em;font-weight:600;font-size:.85em}
dl{display:grid;grid-template-columns:auto 1fr;gap:.25rem 1rem;margin:.5rem 0}
dt{font-weight:600;color:#57606a}
section{margin-top:1.75rem;padding-top:.5rem;border-top:1px solid #d0d7de}
h2{font-size:1.2rem;margin-bottom:.5rem}
table{border-collapse:collapse;margin:.5rem 0}
th,td{border:1px solid #d0d7de;padding:.35rem .6rem;text-align:left}
th{background:#f6f8fa}
.timeline{list-style:none;padding-left:0}
.timeline li{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.85rem;
padding:.15rem 0;border-bottom:1px solid #eaeef2}
.seq{color:#6e7781;display:inline-block;width:3em}
.phase{display:inline-block;width:7em;color:#0969da}
.iter{display:inline-block;width:4em;color:#57606a}
.kind{display:inline-block;width:8em;color:#8250df}
.placeholder{color:#6e7781;font-style:italic}
footer{margin-top:2.5rem;padding-top:.75rem;border-top:1px solid #d0d7de;
font-size:.8rem;color:#57606a}
.check-pass{color:#1a7f37;font-weight:600}
.check-fail{color:#cf222e;font-weight:600}
pre{background:#f6f8fa;padding:.75rem;border-radius:6px;overflow-x:auto;
font-size:.85rem}
"""


def _footer(summary: dict[str, Any], *, redact: bool) -> str:
    schema_version = _esc(summary.get("schema_version"), redact=redact)
    artifact_dir = _esc(
        _normalize_path(summary.get("artifact_dir")), redact=redact
    )
    redaction_note = (
        "Redaction enabled (default): secrets scrubbed."
        if redact
        else "WARNING: redaction disabled (--no-redact). Output may contain secrets."
    )
    return (
        "<footer>"
        f"<p>RevRem <code>{__version__}</code> &middot; "
        f"summary schema <code>{schema_version}</code> &middot; "
        "rendered from <code>events.jsonl</code> &mdash; no model was re-run.</p>"
        f"<p>Run directory: <code>{artifact_dir}</code></p>"
        f"<p>{redaction_note}</p>"
        "</footer>"
    )


def render_report(
    summary: dict[str, Any], events: list[Event], *, redact: bool = True
) -> str:
    """Render a finished run's ``summary`` + ``events`` into a self-contained HTML string.

    Pure: no disk I/O, no network, no model. ``redact`` defaults to True so the
    rendered HTML is safe to upload across a trust boundary by default (gate
    G7). Deterministic across runs and platforms (Contract #9).
    """
    body = (
        _header(summary, redact=redact)
        + _outcome_summary(summary, events, redact=redact)
        + _phase_config_rows(summary, redact=redact)
        + _findings_section(summary, events, redact=redact)
        + _checks_section(events, redact=redact)
        + _cost_section(summary, events, redact=redact)
        + _diff_stats_section(summary, redact=redact)
        + _timeline(events, redact=redact)
        + _footer(summary, redact=redact)
    )
    title = _esc(
        f"RevRem run {summary.get('run_id', '')}", redact=redact
    )
    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>{title}</title>"
        f"<style>{_CSS}</style>"
        "</head>"
        f"<body>{body}</body>"
        "</html>"
    )


# --- Machine-readable JSON index (D-3) --------------------------------------


def _count_findings_by_severity(events: list[Event]) -> dict[str, int]:
    """Tally finding severities. T1 derives a conservative count from events.

    Authoritative per-finding detail comes from triage artifacts (T2); here we
    surface a best-effort count keyed by severity so the index is never empty.
    """
    counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for ev in events:
        if ev.kind == "status_classification":
            payload = ev.payload or {}
            for key, value in payload.items():
                if isinstance(value, list):
                    counts[key] = counts.get(key, 0) + len(value)
    return counts


def _top_findings(events: list[Event], *, redact: bool) -> list[dict[str, Any]]:
    """At most 5 redacted finding summaries for the comment builder.

    Each entry: severity, file, line (nullable), and a one-sentence title.
    T1 derives these conservatively from status_classification events; T2 will
    source richer detail from triage artifacts. The list is empty when there
    are no findings or they were suppressed.
    """
    findings: list[dict[str, Any]] = []
    for ev in events:
        if ev.kind != "status_classification":
            continue
        payload = ev.payload or {}
        for severity in ("critical", "high", "medium", "low"):
            for item in payload.get(severity, []) or []:
                if not isinstance(item, dict):
                    continue
                title = item.get("summary") or item.get("title") or item.get("message") or ""
                path = item.get("path") or item.get("file") or item.get("affected_path")
                line = item.get("line")
                findings.append(
                    {
                        "severity": severity,
                        "file": _esc(_normalize_path(path), redact=False)
                        if path
                        else None,
                        "line": line if isinstance(line, int) else None,
                        "title": _esc(title, redact=False) if title else "",
                    }
                )
                if len(findings) >= 5:
                    return findings
    return findings


def _redact_index_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted: list[dict[str, Any]] = []
    for item in findings:
        redacted.append(
            {
                "severity": item["severity"],
                "file": redact_text(item["file"]).text if item["file"] else None,
                "line": item["line"],
                "title": redact_text(item["title"]).text if item["title"] else "",
            }
        )
    return redacted


def _cost_usd(summary: dict[str, Any]) -> float | None:
    """Total USD spent, or null when the harness did not report cost."""
    usd = summary.get("usd")
    if usd is None or usd == "":
        return None
    try:
        return float(usd)
    except (TypeError, ValueError):
        return None


def _artifact_paths(summary: dict[str, Any]) -> dict[str, Any]:
    """Artifact locations keyed by type. Empty dict when unavailable."""
    paths = summary.get("artifact_paths")
    if not isinstance(paths, dict) or not paths:
        return {}
    return {str(k): _normalize_path(v) for k, v in paths.items()}


def build_report_index(
    summary: dict[str, Any], events: list[Event], *, redact: bool = True
) -> dict[str, Any]:
    """Build the machine-readable report index (D-3).

    The minimum payload ``post_pr_comment.py`` needs to populate a PR comment
    body from this file alone, without reading raw ``events.jsonl`` or
    ``summary.json``. Fields follow the nullability contract: ``cost_usd`` is
    null for dry-runs / unrecorded cost; ``top_findings`` is ``[]`` when there
    are no findings or they were suppressed (each entry's ``line`` is null when
    the finding has no file-level location); ``artifact_paths`` is ``{}`` when
    the run dir is unavailable. All other required keys are always present and
    non-null; a missing key is a schema violation, not a null.
    """
    top = _top_findings(events, redact=redact)
    if redact:
        top = _redact_index_findings(top)
    run_id = summary.get("run_id", "")
    if redact:
        run_id = redact_text(str(run_id)).text
    return {
        "schema_version": REPORT_INDEX_SCHEMA_VERSION,
        "run_id": run_id,
        "final_status": summary.get("final_status"),
        "stopped_reason": summary.get("stopped_reason"),
        "finding_counts": _count_findings_by_severity(events),
        "suppression_count": sum(1 for ev in events if ev.kind == "suppressed"),
        "cost_usd": _cost_usd(summary),
        "top_findings": top,
        "artifact_paths": _artifact_paths(summary),
    }
