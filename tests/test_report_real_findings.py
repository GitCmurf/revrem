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
    """No real run should show "No confirmed findings recorded" when triage found issues."""
    summary, evs = _load()
    triage = json.loads((_FIXTURE / "triage-1.json").read_text(encoding="utf-8"))
    html_out = render_report(
        summary, evs, triage_findings=[triage] if triage.get("confirmed_findings") else []
    )
    assert "No confirmed findings recorded" not in html_out


def test_checks_section_renders_from_summary_iterations(capsys):
    """Checks render from summary.iterations[].checks[] (the engine real
    location), not only check_result events (C4). The fixture carries a
    summary check (ruff check ., passed) and no check_result event."""
    exit_code = report_command.main([str(_FIXTURE), "--output", str(_FIXTURE / "report.html")])
    assert exit_code == 0
    html_out = (_FIXTURE / "report.html").read_text(encoding="utf-8")
    (_FIXTURE / "report.html").unlink()
    assert "ruff check ." in html_out
    assert "passed" in html_out
    # The summary-sourced check renders, not the empty placeholder.
    assert "No check results recorded" not in html_out
    # The Outcome counters use the same summary-sourced check data as the
    # Checks table, so the report cannot contradict itself.
    assert "<dt>Checks passed</dt><dd>1</dd>" in html_out
    assert "<dt>Checks failed</dt><dd>0</dd>" in html_out


def test_phase_config_section_renders_per_phase_harness_and_model(capsys):
    """The per-phase harness/model table renders from summary.phase_config
    (P0-A regression guard). The prior P0-2 review wrongly concluded the key
    did not exist — it is written on every real run by
    reporting.add_summary_contract_fields. The fixture carries a real-shaped
    phase_config; the report MUST surface it.

    Only the model-bearing phases (review/triage/remediation/commit_message)
    render; checks/runtime carry no harness/model and must be filtered out
    rather than emitted as blank rows.
    """
    exit_code = report_command.main([str(_FIXTURE), "--output", str(_FIXTURE / "report.html")])
    assert exit_code == 0
    html_out = (_FIXTURE / "report.html").read_text(encoding="utf-8")
    (_FIXTURE / "report.html").unlink()

    assert "Phase configuration" in html_out, (
        "the phase-config section must render; summary.phase_config is present "
        "on every real run (reporting.add_summary_contract_fields)"
    )
    # Model-bearing phases and their real harness/model surface.
    for phase in ("review", "triage", "remediation", "commit_message"):
        assert phase in html_out, f"phase {phase!r} missing from the table"
    assert "gpt-5.5" in html_out  # review/triage model
    assert "gpt-5.4-mini" in html_out  # remediation model
    # checks/runtime have no harness/model and must NOT appear as table rows.
    assert "<td>checks</td>" not in html_out
    assert "<td>runtime</td>" not in html_out


def test_rejected_and_needs_more_info_findings_render(capsys):
    """Triage rejected_findings and needs_more_info are part of the C1 contract
    and must surface, not be silently dropped (C1 completeness)."""
    exit_code = report_command.main([str(_FIXTURE), "--output", str(_FIXTURE / "report.html")])
    assert exit_code == 0
    html_out = (_FIXTURE / "report.html").read_text(encoding="utf-8")
    (_FIXTURE / "report.html").unlink()
    # rejected finding: its rejection reason / fingerprint surfaces.
    assert "review-comment:2" in html_out
    assert "Not introduced by the reviewed change" in html_out
    # needs-more-info: its info request surfaces.
    assert "f2:unclear-auth-check" in html_out
    assert "auth guard is enforced upstream" in html_out


def test_per_iteration_review_status_surfaces(capsys):
    """The outcome section surfaces summary.iterations[].review_status (the
    docstring promised it; this asserts it is actually rendered)."""
    exit_code = report_command.main([str(_FIXTURE), "--output", str(_FIXTURE / "report.html")])
    assert exit_code == 0
    html_out = (_FIXTURE / "report.html").read_text(encoding="utf-8")
    (_FIXTURE / "report.html").unlink()
    # The fixture's single iteration has review_status "findings" — assert the
    # actual value renders in the outcome row, not merely the label.
    assert "<dt>Review status</dt><dd>findings</dd>" in html_out
