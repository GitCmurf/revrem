"""Tests for the PR comment builder and GitHub posting (PLAN-005 T4).

``build_comment_body`` is pure and unit-tested in isolation. The posting path
is exercised against a local stub GitHub API (no network) to assert
idempotency (create-vs-update via the marker) and the comment-before-fail
ordering the action depends on.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests.support.fake_github_api import FakeGitHubServer

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "post_pr_comment.py"


def _load_script_module():
    """Load post_pr_comment.py as a module (it lives outside the package)."""
    spec = importlib.util.spec_from_file_location("post_pr_comment", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ppc = _load_script_module()


# --- pure body builder -----------------------------------------------------


def _clear_index():
    return {
        "schema_version": "1.0",
        "run_id": "run-1",
        "final_status": "clear",
        "stopped_reason": "review_clear",
        "finding_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "suppression_count": 0,
        "cost_usd": None,
        "top_findings": [],
        "artifact_paths": {},
    }


def _findings_index():
    return {
        "schema_version": "1.0",
        "run_id": "run-2",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "finding_counts": {"critical": 1, "high": 2, "medium": 0, "low": 3},
        "suppression_count": 1,
        "cost_usd": 0.42,
        "top_findings": [
            {"severity": "critical", "file": "src/app.py", "line": 42, "title": "SQL injection"},
            {"severity": "high", "file": "src/db.py", "line": None, "title": "Missing index"},
        ],
        "artifact_paths": {},
    }


def test_body_contains_marker_and_status():
    body = ppc.build_comment_body(_clear_index())
    assert ppc.MARKER in body
    assert "clear" in body


def test_body_lists_findings_when_present():
    body = ppc.build_comment_body(_findings_index())
    assert "SQL injection" in body
    assert "src/app.py:42" in body
    # Bounded finding count in the summary row.
    assert "critical: 1" in body
    assert "high: 2" in body


def test_summary_severity_counts_do_not_break_markdown_table():
    body = ppc.build_comment_body(_findings_index())
    row = next(ln for ln in body.splitlines() if ln.startswith("| **Findings** |"))
    assert row == (
        "| **Findings** | "
        "6 (critical: 1 \\| high: 2 \\| medium: 0 \\| low: 3) |"
    )


def test_stop_reason_does_not_break_markdown_table_or_code_span():
    idx = {**_findings_index(), "stopped_reason": "bad|reason\nwith `code`"}
    body = ppc.build_comment_body(idx)
    row = next(ln for ln in body.splitlines() if ln.startswith("| **Stop reason** |"))
    assert row == "| **Stop reason** | `bad\\|reason with 'code'` |"


def test_failure_summary_is_rendered_in_summary_table():
    idx = {
        **_clear_index(),
        "final_status": "error",
        "stopped_reason": "review_failed",
        "failure_summary": {
            "phase": "review",
            "iteration": "1",
            "reason": "provider_quota_exhausted",
            "detail": "provider quota exhausted",
            "message": "Provider quota/billing exhausted. Fix billing, then rerun.",
        },
    }

    body = ppc.build_comment_body(idx)

    row = next(ln for ln in body.splitlines() if ln.startswith("| **Failure** |"))
    assert row == (
        "| **Failure** | "
        "Provider quota/billing exhausted. Fix billing, then rerun. |"
    )


def test_failure_summary_does_not_break_markdown_table():
    idx = {
        **_clear_index(),
        "final_status": "error",
        "failure_summary": {
            "phase": "review",
            "iteration": "1",
            "reason": "bad|reason",
            "detail": "",
            "message": "bad | failure\nwith `code`",
        },
    }

    body = ppc.build_comment_body(idx)

    row = next(ln for ln in body.splitlines() if ln.startswith("| **Failure** |"))
    assert row == "| **Failure** | bad \\| failure with 'code' |"


def test_body_no_findings_when_absent():
    body = ppc.build_comment_body(_clear_index())
    assert "Top findings" not in body


def test_body_renders_cost_and_suppression():
    body = ppc.build_comment_body(_findings_index())
    assert "$0.42" in body
    assert "Suppressed" in body


def test_body_cost_na_when_null():
    body = ppc.build_comment_body(_clear_index())
    assert "n/a" in body


def test_body_includes_run_url_when_provided():
    body = ppc.build_comment_body(_clear_index(), run_url="https://example/run/1")
    assert "https://example/run/1" in body


def test_main_prefers_artifact_url_over_run_url(tmp_path, fake_github, monkeypatch):
    """The comment links the uploaded report artifact (REVREM_ARTIFACT_URL) when
    present, falling back to the run URL only when absent (C6)."""
    report = tmp_path / "revrem-report.json"
    report.write_text(json.dumps(_clear_index()), encoding="utf-8")
    monkeypatch.setenv("REVREM_REPORT_JSON", str(report))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_PR_NUMBER", "7")
    monkeypatch.setenv("REVREM_ARTIFACT_URL", "https://artifact-link/report.html")
    monkeypatch.setenv("GITHUB_RUN_URL", "https://run/1")
    assert ppc.main([]) == 0
    posted = next(iter(fake_github.comments.values()))["body"]
    assert "https://artifact-link/report.html" in posted
    assert "https://run/1" not in posted
    # The artifact link is labelled [Report], not mislabelled [Run] (C6).
    assert "[Report](https://artifact-link/report.html)" in posted


def test_table_cells_are_sanitized_against_markdown_injection():
    """A model-derived finding title containing a pipe, newline, or backtick must
    not break the Markdown table row or inject formatting (GPT review #6)."""
    idx = {
        **_findings_index(),
        "top_findings": [
            {
                "severity": "high",
                "file": "src/a|b.py",
                "line": 1,
                "title": "bad | title\nwith newline and `code`",
            }
        ],
    }
    body = ppc.build_comment_body(idx)
    rows = [ln for ln in body.splitlines() if ln.startswith("| high ")]
    assert len(rows) == 1, f"finding must occupy exactly one table row: {rows}"
    row = rows[0]
    # The raw pipe from the title must not appear unescaped (it would add a column).
    assert "bad | title" not in row
    assert "bad \\| title" in row
    # No literal newline leaked into the row (asserted by single-row check above).
    assert row.count("\n") == 0


def test_body_never_embeds_secrets_by_design():
    """The builder only reads known index fields; it never pastes raw stdin/argv.
    A stray secret in an unrelated field would not appear because we never
    serialize the whole index."""
    idx = _clear_index()
    idx["__raw_model_output"] = "SECRET-ghp_abcdef"  # ignored, not a rendered field
    body = ppc.build_comment_body(idx)
    assert "SECRET-ghp_abcdef" not in body


# --- posting against a stub API --------------------------------------------


@pytest.fixture()
def fake_github(monkeypatch):
    server = FakeGitHubServer()
    base = server.start()
    monkeypatch.setattr(ppc, "_API_BASE", base)
    yield server
    server.stop()


def test_post_creates_then_updates_existing_comment(fake_github):
    body1 = ppc.build_comment_body(_findings_index())
    action1 = ppc.post_or_update_comment(
        body1, token="t", repo="o/r", pr_number="1"
    )
    assert action1 == "created"
    assert len(fake_github.comments) == 1

    body2 = ppc.build_comment_body(_clear_index())
    action2 = ppc.post_or_update_comment(
        body2, token="t", repo="o/r", pr_number="1"
    )
    assert action2 == "updated"
    # Still only one comment (updated in place via the marker), not two.
    assert len(fake_github.comments) == 1
    updated_body = next(iter(fake_github.comments.values()))["body"]
    assert ppc.MARKER in updated_body
    assert "clear" in updated_body


def test_post_marker_is_the_idempotency_key(fake_github):
    """A pre-existing unrelated comment must not be mistaken for the RevRem one."""
    fake_github.comments[500] = {"id": 500, "body": "some other comment"}
    body = ppc.build_comment_body(_clear_index())
    action = ppc.post_or_update_comment(
        body, token="t", repo="o/r", pr_number="1"
    )
    assert action == "created"
    # The unrelated comment is untouched; a new marked comment was created.
    assert len(fake_github.comments) == 2
    revrem_comments = [c for c in fake_github.comments.values() if ppc.MARKER in c["body"]]
    assert len(revrem_comments) == 1


def test_post_finds_marker_across_paginated_comments(fake_github):
    """The marker must be found even when it sits past the first 100 comments.

    Idempotency depends on locating the existing marked comment; without Link-
    header pagination a long-lived PR would get a duplicate comment every run.
    """
    # 150 unrelated comments push the marker onto page 2 at per_page=100.
    fake_github.page_size = 100
    for i in range(150):
        fake_github.comments[2000 + i] = {"id": 2000 + i, "body": f"noise {i}"}
    marker_id = 3000
    fake_github.comments[marker_id] = {
        "id": marker_id,
        "body": ppc.MARKER + "\nold body",
    }
    body = ppc.build_comment_body(_clear_index())
    action = ppc.post_or_update_comment(body, token="t", repo="o/r", pr_number="1")
    assert action == "updated"
    # No duplicate created: the marked comment was updated in place.
    assert len(fake_github.comments) == 151
    assert ppc.MARKER in fake_github.comments[marker_id]["body"]
    assert "old body" not in fake_github.comments[marker_id]["body"]


def test_post_sends_json_content_type(fake_github):
    """POST must declare Content-Type: application/json, not let urllib default
    to application/x-www-form-urlencoded (GitHub expects JSON on this endpoint)."""
    body = ppc.build_comment_body(_clear_index())
    ppc.post_or_update_comment(body, token="t", repo="o/r", pr_number="1")
    post_requests = [r for r in fake_github.requests if r["method"] == "POST"]
    assert post_requests, "expected a POST request"
    assert post_requests[-1]["headers"].get("Content-Type") == "application/json"


def test_main_handles_invalid_json_response(monkeypatch):
    """A non-JSON API response (proxy outage, empty body) must exit 1, not crash."""
    import http.server
    import threading

    class BadJsonHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A002
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Link", '<http://x>; rel="next"')
            self.end_headers()
            self.wfile.write(b"not-json")

    server = http.server.HTTPServer(("127.0.0.1", 0), BadJsonHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        monkeypatch.setattr(ppc, "_API_BASE", base)
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
        monkeypatch.setenv("GITHUB_PR_NUMBER", "7")
        # main() must catch the ValueError from json.loads and return 1.
        assert ppc.main([]) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_comment_before_fail_ordering(fake_github):
    """The comment is posted (created) before any exit-code mapping happens.
    The action applies the exit code LAST; here we assert the posting step
    itself completes and records a create, independent of a later failure."""
    body = ppc.build_comment_body(
        {**_findings_index(), "final_status": "findings"}
    )
    action = ppc.post_or_update_comment(
        body, token="t", repo="o/r", pr_number="1"
    )
    assert action == "created"
    # A findings comment was posted even though the run "failed".
    posted = next(iter(fake_github.comments.values()))["body"]
    assert "findings" in posted


def test_main_reads_report_json_and_posts(tmp_path, fake_github, monkeypatch):
    report = tmp_path / "revrem-report.json"
    report.write_text(json.dumps(_clear_index()), encoding="utf-8")
    monkeypatch.setenv("REVREM_REPORT_JSON", str(report))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_PR_NUMBER", "7")
    monkeypatch.delenv("GITHUB_RUN_URL", raising=False)
    assert ppc.main([]) == 0
    assert len(fake_github.comments) == 1


def test_main_degraded_when_report_unreadable(tmp_path, fake_github, monkeypatch):
    """If the redacted report can't be read, post a degraded generic comment, not a crash."""
    monkeypatch.setenv("REVREM_REPORT_JSON", str(tmp_path / "nope.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_PR_NUMBER", "7")
    monkeypatch.delenv("GITHUB_RUN_URL", raising=False)
    assert ppc.main([]) == 0
    posted = next(iter(fake_github.comments.values()))["body"]
    assert "report-unavailable" in posted


def test_main_requires_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("REVREM_REPORT_JSON", str(tmp_path / "nope.json"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_PR_NUMBER", raising=False)
    assert ppc.main([]) == 1
