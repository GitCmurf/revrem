"""Real-findings render gate (REVREM-PLAN-005 corrective, P0-1).

This gate exists to prevent the self-confirming-fixture failure mode that
slipped through T1/T2: the renderer was validated against hand-authored
fixtures whose status_classification payload invented a severity-keyed shape
that does not exist in the engine. Real confirmed findings live in
triage-N.json::confirmed_findings and per-iteration status in
summary.iterations[].review_status — neither of which the original renderer
read.

This fixture (findings_with_triage) carries a real-shaped status_classification
event (payload {message, summary} — no severities) and a triage-1.json with one
confirmed medium finding. The renderer MUST surface that finding. It failed
before C1 and goes green only when findings are sourced from triage artifacts.
Registered in REVREM-TEST-001.
"""

from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import events
from code_review_loop.cli.commands import report as report_command
from code_review_loop.report_html import build_report_index, render_report

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "runs"
    / "findings_with_triage"
)


def _load():
    summary = json.loads((_FIXTURE / "summary.json").read_text(encoding="utf-8"))
    event_records, _ = events.read_events(_FIXTURE / events.EVENTS_FILENAME)
    return summary, event_records


def _real_status_classification_has_no_severities():
    """Sanity: the fixture status_classification event matches the real engine shape."""
    _summary, evs = _load()
    sc = [e for e in evs if e.kind == "status_classification"]
    assert sc, "fixture should carry a status_classification event"
    payload = sc[0].payload
    assert set(payload.keys()) <= {
        "message", "summary", "status", "findings", "clear_phrase", "stderr"
    }
    assert "critical" not in payload
    assert "high" not in payload


def test_html_report_surfaces_the_confirmed_triage_finding(capsys):
    """The confirmed medium finding in triage-1.json must appear in the HTML."""
    _real_status_classification_has_no_severities()
    # The command layer loads triage-N.json and threads it into the renderer.
    # Verify end-to-end by writing an HTML report, then assert on the file.
    exit_code = report_command.main([str(_FIXTURE), "--output", str(_FIXTURE / "report.html")])
    assert exit_code == 0
    html_out = (_FIXTURE / "report.html").read_text(encoding="utf-8")
    (_FIXTURE / "report.html").unlink()  # keep fixture tree pristine

    assert "f1:sql-injection-user-input" in html_out, (
        "the confirmed finding fingerprint must render; findings are sourced "
        "from triage-N.json::confirmed_findings, not the status_classification event"
    )
    assert "SQL injection in user lookup query" in html_out
    assert "src/app.py" in html_out
    assert "medium" in html_out.lower()


def test_json_index_counts_and_surfaces_the_finding():
    """The PR-comment payload must report finding_counts total > 0 and surface the finding."""
    _real_status_classification_has_no_severities()
    summary, evs = _load()
    triage = json.loads((_FIXTURE / "triage-1.json").read_text(encoding="utf-8"))
    idx = build_report_index(
        summary, evs, triage_findings=[triage] if triage.get("confirmed_findings") else []
    )
    total = sum(idx["finding_counts"].values())
    assert total >= 1, (
        f"finding_counts total is {total}; the confirmed medium finding in "
        "triage-1.json is not counted (PR comment would report 0 findings)"
    )
    titles = [f.get("title", "") for f in idx["top_findings"]]
    assert any("SQL injection" in t for t in titles), (
        "the finding did not surface in top_findings: " + str(idx["top_findings"])
    )


def test_findings_section_is_not_empty_on_real_shaped_input():
    """No real run should show "No configured findings recorded" when triage found issues."""
    summary, evs = _load()
    triage = json.loads((_FIXTURE / "triage-1.json").read_text(encoding="utf-8"))
    html_out = render_report(
        summary, evs, triage_findings=[triage] if triage.get("confirmed_findings") else []
    )
    assert "No configured findings recorded" not in html_out
