"""Tests for ``revrem report`` HTML rendering (REVREM-PLAN-005 T1).

The report is a read-only consumer of ``summary.json`` + ``events.jsonl``: it
never invokes a model or touches the network (gate G5), and redaction is on by
default for anything that leaves the run dir (gate G7). These tests cover every
T0 fixture, determinism (byte-stable across two renders), the redaction
default, truncated-event tolerance, and the CLI exit-code/error paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from code_review_loop import events
from code_review_loop.cli.commands import report as report_command
from code_review_loop.report_html import build_report_index, render_report
from tests.support.run_fixtures import RUN_SCENARIOS, load_run


def _load(name: str) -> tuple[dict, list]:
    run_dir = load_run(name)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    event_records, _ = events.read_events(run_dir / events.EVENTS_FILENAME)
    return summary, event_records


def _load_triage(name: str) -> list[dict] | None:
    """Load triage artifacts the way the report command does (C1)."""
    run_dir = load_run(name)
    triage_paths = (json.loads((run_dir / "summary.json").read_text()).get("artifact_paths") or {}).get("triage") or []
    loaded: list[dict] = []
    for raw in triage_paths:
        candidate = run_dir / raw if not Path(raw).is_absolute() else Path(raw)
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            loaded.append(payload)
    return loaded if loaded else None


# --- pure-function rendering over the T0 fixture catalogue -----------------


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_render_report_contains_run_id_and_status(scenario: str):
    summary, event_records = _load(scenario)
    html_out = render_report(summary, event_records)
    assert summary["run_id"] in html_out
    assert summary["final_status"] in html_out
    assert html_out.startswith("<!DOCTYPE html>")


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_render_report_is_deterministic(scenario: str):
    summary, event_records = _load(scenario)
    first = render_report(summary, event_records)
    second = render_report(summary, event_records)
    assert first == second


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_render_report_has_no_crlf(scenario: str):
    """Determinism guard (Contract #9): HTML must contain no \\r\\n bytes.

    Without this, a golden passes on Linux CI and fails on a macOS/Windows
    dev box that normalises line endings.
    """
    summary, event_records = _load(scenario)
    assert b"\r" not in render_report(summary, event_records).encode("utf-8")


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_render_report_is_single_file_with_no_external_refs(scenario: str):
    """The report is a single file safe to open offline: no script/external src/link."""
    summary, event_records = _load(scenario)
    html_out = render_report(summary, event_records)
    lowered = html_out.lower()
    assert "<script" not in lowered
    assert "<link" not in lowered
    # No external src/href attributes (inline <style> is allowed).
    assert "src=" not in lowered
    assert "href=" not in lowered


def test_render_report_redacts_by_default_and_reveals_with_opt_out():
    """A synthetic secret is scrubbed when redact=True (default) and present otherwise."""
    summary, event_records = _load("clear")
    # Use a real-format OpenAI key (sk- + >=20 word chars) that the redactor
    # genuinely matches, not an arbitrary string it would miss.
    secret = "sk-abcdef1234567890ABCDEF1234567890"  # pragma: allowlist secret
    summary = {**summary, "run_id": f"run-leaked-{secret}"}
    redacted = render_report(summary, event_records, redact=True)
    unredacted = render_report(summary, event_records, redact=False)
    assert secret not in redacted
    assert secret in unredacted


def test_render_report_calls_no_disk():
    """render_report is pure: callable with in-memory inputs only."""
    summary = {
        "schema_version": "1.0",
        "run_id": "mem-1",
        "final_status": "clear",
        "stopped_reason": "review_clear",
        "started_at": "2026-06-21T00:00:00Z",
        "finished_at": "2026-06-21T00:00:01Z",
    }
    html_out = render_report(summary, [])
    assert "mem-1" in html_out
    assert "clear" in html_out


def test_header_renders_summary_harness():
    """The header shows the top-level summary.harness."""
    summary, event_records = _load("clear")
    summary = {**summary, "harness": "codex"}
    html_out = render_report(summary, event_records)
    assert "codex" in html_out


def test_phase_config_section_absent_when_summary_omits_it():
    """A run that carries no phase_config (e.g. an older run) omits the section
    rather than rendering an empty table."""
    summary, event_records = _load("clear")
    summary = {k: v for k, v in summary.items() if k != "phase_config"}
    html_out = render_report(summary, event_records)
    assert "Phase configuration" not in html_out


def test_phase_config_section_renders_model_bearing_phases_only():
    """When summary.phase_config is present (every modern run), the section
    renders the model-bearing phases and skips checks/runtime (no harness/model).

    Regression guard for P0-A: the prior P0-2 wrongly deleted this section,
    believing the key did not exist. It is written on every real run by
    reporting.add_summary_contract_fields."""
    summary, event_records = _load("clear")
    summary = {
        **summary,
        "phase_config": {
            "review": {"harness": "codex", "model": "gpt-5.5",
                       "reasoning_effort": "high"},
            "remediation": {"harness": "codex", "model": "gpt-5.4-mini"},
            "checks": {"commands": ["ruff check ."]},
            "runtime": {"provider_retry_attempts": 2},
        },
    }
    html_out = render_report(summary, event_records)
    assert "Phase configuration" in html_out
    assert "gpt-5.5" in html_out
    assert "gpt-5.4-mini" in html_out
    # checks/runtime have no harness/model — filtered, not blank rows.
    assert "<td>checks</td>" not in html_out
    assert "<td>runtime</td>" not in html_out


def test_phase_failures_section_surfaces_diagnostics_and_retry_command():
    summary, event_records = _load("clear")
    summary = {
        **summary,
        "final_status": "error",
        "stopped_reason": "review_failed",
        "phase_failures": [
            {
                "phase": "review",
                "iteration": "1",
                "diagnostic_artifact": "tmp/run/diagnostics-review-1-failure.json",
                "failure": {
                    "reason": "provider_exit",
                    "detail": "exit 1",
                    "transient": False,
                },
                "redirected_retry_command": {
                    "command": ["codex", "--model", "gpt-5.5", "review"]
                },
            }
        ],
    }

    html_out = render_report(summary, event_records)

    assert "Phase failures" in html_out
    assert "provider_exit" in html_out
    assert "exit 1" in html_out
    assert "tmp/run/diagnostics-review-1-failure.json" in html_out
    assert "codex --model gpt-5.5 review" in html_out


@pytest.mark.parametrize(
    ("stopped_reason", "expected_code"),
    (
        ("review_failed", 1),
        ("budget_ceiling_hit", 3),
        ("setup_failed", 4),
        ("cancelled", 5),
    ),
)
def test_error_exit_code_mapping_honors_stopped_reason(
    stopped_reason: str, expected_code: int
):
    """The HTML report mirrors the runtime exit-code contract for error states."""
    summary = {
        "schema_version": "1.0",
        "run_id": f"error-{stopped_reason}",
        "final_status": "error",
        "stopped_reason": stopped_reason,
        "started_at": "2026-06-21T00:00:00Z",
        "finished_at": "2026-06-21T00:00:01Z",
    }
    html_out = render_report(summary, [])
    assert f"Exit code: <code>{expected_code}</code>" in html_out


# --- CLI command -----------------------------------------------------------


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_report_command_writes_html_and_exits_zero(
    scenario: str, tmp_path: Path, capsys
):
    run_dir = load_run(scenario)
    output = tmp_path / "report.html"
    exit_code = report_command.main([str(run_dir), "--output", str(output)])
    assert exit_code == 0
    assert output.is_file()
    content = output.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")
    captured = capsys.readouterr()
    assert str(output) in captured.out


def test_report_command_default_output_is_run_dir(tmp_path: Path):
    """Without --output, the report lands at <run-dir>/report.html."""
    run_dir = load_run("clear")
    exit_code = report_command.main([str(run_dir)])
    assert exit_code == 0
    assert (run_dir / "report.html").is_file()
    # Clean up so the fixture tree stays pristine for other tests.
    (run_dir / "report.html").unlink()


def test_report_command_missing_run_dir_exits_one(tmp_path: Path, capsys):
    missing = tmp_path / "does-not-exist"
    exit_code = report_command.main([str(missing)])
    assert exit_code == 1
    assert "ERROR" in capsys.readouterr().err


def test_report_command_no_redact_without_acknowledgement_exits_four(
    capsys,
    tmp_path,
):
    run_dir = load_run("clear")
    # Use tmp_path rather than the POSIX-only /dev/null so the suite is portable.
    exit_code = report_command.main(
        [str(run_dir), "--no-redact", "--output", str(tmp_path / "dummy.html")]
    )
    assert exit_code == 4
    assert "--i-understand-the-risks" in capsys.readouterr().err


def test_report_command_truncated_events_still_renders_with_warning(
    tmp_path: Path, capsys
):
    """A truncated events.jsonl renders what is available + warns, exits 0."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": "trunc-1",
                "final_status": "error",
                "stopped_reason": "review_failed",
                "started_at": "2026-06-21T00:00:00Z",
                "finished_at": "2026-06-21T00:00:01Z",
            }
        ),
        encoding="utf-8",
    )
    # An events.jsonl with a seq gap (1 then 3) triggers read_events truncation.
    (run_dir / events.EVENTS_FILENAME).write_text(
        '{"iteration":null,"kind":"summary","payload":{},"phase":null,'
        '"run_id":"trunc-1","schema_version":"1.0","seq":3,'
        '"ts":"2026-06-21T00:00:01Z"}\n',
        encoding="utf-8",
    )
    output = tmp_path / "report.html"
    exit_code = report_command.main([str(run_dir), "--output", str(output)])
    assert exit_code == 0
    assert output.is_file()
    assert "truncated" in capsys.readouterr().err.lower()


def test_report_command_malformed_events_warns_once_without_contradiction(
    tmp_path: Path, capsys
):
    """A fully-malformed event stream (seq gap -> ValueError) renders from
    summary.json only and must NOT also print the contradictory "rendered with
    the events available" message (which implies partial events were used when
    none were). The two warnings are for distinct truncation states."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": "mal-1",
                "final_status": "error",
                "stopped_reason": "review_failed",
                "started_at": "2026-06-21T00:00:00Z",
                "finished_at": "2026-06-21T00:00:01Z",
            }
        ),
        encoding="utf-8",
    )
    # A seq gap raises ValueError in read_events -> event_records stays empty.
    (run_dir / events.EVENTS_FILENAME).write_text(
        '{"iteration":null,"kind":"summary","payload":{},"phase":null,'
        '"run_id":"mal-1","schema_version":"1.0","seq":5,'
        '"ts":"2026-06-21T00:00:01Z"}\n',
        encoding="utf-8",
    )
    exit_code = report_command.main(
        [str(run_dir), "--output", str(tmp_path / "report.html")]
    )
    assert exit_code == 0
    err = capsys.readouterr().err.lower()
    # The "summary.json only" message must appear (no events were usable)...
    assert "summary.json only" in err
    # ...and the contradictory "events available" message must NOT (none were).
    assert "events available" not in err


def test_report_command_uses_latest_triage_artifact_for_index(
    tmp_path: Path, capsys
):
    """Only the highest-numbered triage artifact is authoritative for reports."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": "multi-triage",
                "final_status": "clear",
                "stopped_reason": "review_clear",
                "started_at": "2026-06-21T00:00:00Z",
                "finished_at": "2026-06-21T00:00:01Z",
                "artifact_paths": {
                    # Deliberately out of order: highest N still wins.
                    "triage": ["triage-2.json", "triage-1.json"],
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / events.EVENTS_FILENAME).write_text("", encoding="utf-8")
    (run_dir / "triage-1.json").write_text(
        json.dumps(
            {
                "confirmed_findings": [
                    {
                        "fingerprint": "stale",
                        "severity": "high",
                        "summary": "stale finding",
                        "affected_paths": ["src/stale.py"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "triage-2.json").write_text(
        json.dumps({"confirmed_findings": []}),
        encoding="utf-8",
    )

    exit_code = report_command.main([str(run_dir), "--format", "json"])
    assert exit_code == 0
    idx = json.loads(capsys.readouterr().out)
    assert idx["finding_counts"] == {"critical": 0, "high": 0, "low": 0, "medium": 0}
    assert idx["top_findings"] == []


# --- machine-readable JSON index ------------------------------------------


def test_build_report_index_required_keys_always_present():
    summary, event_records = _load("clear")
    idx = build_report_index(summary, event_records)
    for key in (
        "schema_version",
        "run_id",
        "final_status",
        "finding_counts",
        "suppression_count",
        "cost_usd",
        "top_findings",
        "artifact_paths",
    ):
        assert key in idx, f"missing required key {key}"


def test_build_report_index_cost_usd_null_for_fake_harness():
    """cost_usd is null when the harness did not record cost (nullability contract)."""
    summary, event_records = _load("clear")
    idx = build_report_index(summary, event_records)
    assert idx["cost_usd"] is None


def test_build_report_index_suppression_count_for_all_suppressed():
    summary, event_records = _load("all_suppressed")
    triage = _load_triage("all_suppressed")
    idx = build_report_index(summary, event_records, triage_findings=triage)
    assert idx["suppression_count"] >= 1


def test_build_report_index_top_findings_bounded_and_redacted():
    summary, event_records = _load("clear")
    idx = build_report_index(summary, event_records)
    assert isinstance(idx["top_findings"], list)
    assert len(idx["top_findings"]) <= 5


# --- T2: body content sections --------------------------------------------


def test_findings_remediated_shows_check_and_clear_status():
    """The remediated fixture shows the passing check and the final clear status."""
    summary, event_records = _load("findings_remediated")
    html_out = render_report(summary, event_records)
    assert "pytest -q" in html_out
    assert "passed" in html_out
    # Final review came back clear after remediation.
    assert "clear" in html_out


def test_all_suppressed_shows_suppressed_findings_and_stop_reason():
    summary, event_records = _load("all_suppressed")
    html_out = render_report(summary, event_records)
    assert "suppressed" in html_out.lower()
    assert "all_findings_suppressed" in html_out


def test_cost_ceiling_shows_ceiling_breach_and_badge():
    summary, event_records = _load("cost_ceiling")
    html_out = render_report(summary, event_records)
    assert "budget ceiling" in html_out.lower()
    assert "10 / 10" in html_out
    # The error status badge reflects the budget-stop state.
    assert "error" in html_out


def test_cost_section_renders_null_not_zero():
    """When the harness cannot report cost, the section says 'not reported', not 0."""
    summary, event_records = _load("clear")
    html_out = render_report(summary, event_records)
    assert "not reported" in html_out
    # Never fabricate a zero USD figure for an unreported cost.
    assert "usd</dt><dd>0" not in html_out.lower()


def test_diff_stats_unavailable_when_absent():
    """No diff-stat data in the run dir renders 'unavailable'; the report never shells out."""
    summary, event_records = _load("clear")
    html_out = render_report(summary, event_records)
    assert "diff stats unavailable" in html_out.lower()


# --- T2: golden HTML comparison (Contract #9) ------------------------------


_GOLDEN_DIR = Path(__file__).resolve().parent / "golden" / "report"
_GOLDEN_SCENARIOS = (
    "clear",
    "findings_remediated",
    "findings_remaining",
    "check_failure",
    "cost_ceiling",
    "all_suppressed",
)


def _assert_golden_html(scenario: str) -> None:
    """Compare the rendered HTML against a committed golden, byte-for-byte.

    Regenerate intentionally with ``REVREM_UPDATE_SNAPSHOTS=1`` (consistent with
    the repo's other golden-master snapshots). The golden guarantees the report
    is byte-stable across runs and platforms (Contract #9): no CRLF, paths
    POSIX-normalised, timestamps pinned from inputs. Triage findings are loaded
    so the findings section renders from its authoritative source (C1).
    """
    summary, event_records = _load(scenario)
    triage = _load_triage(scenario)
    actual = render_report(summary, event_records, triage_findings=triage)
    golden_path = _GOLDEN_DIR / f"{scenario}.html"
    if os.environ.get("REVREM_UPDATE_SNAPSHOTS") == "1" or not golden_path.exists():
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(actual, encoding="utf-8")
        return
    expected = golden_path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"Golden HTML for {scenario!r} changed. If intentional, record it and "
        f"regenerate with REVREM_UPDATE_SNAPSHOTS=1.\n"
        + _diff(expected, actual)
    )


def _diff(expected: str, actual: str) -> str:
    import difflib

    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile="(committed)",
            tofile="(actual)",
        )
    )


@pytest.mark.parametrize("scenario", _GOLDEN_SCENARIOS)
def test_report_matches_golden_html(scenario: str):
    _assert_golden_html(scenario)


@pytest.mark.parametrize("scenario", _GOLDEN_SCENARIOS)
def test_golden_html_is_cross_platform_safe(scenario: str):
    """Determinism guards enforced on the committed golden itself.

    The golden must contain no CRLF and no backslash path separators, so it is
    byte-stable on Linux CI and a macOS/Windows dev box alike. Asserting on the
    committed golden (not just the live render) makes the invariant durable.
    """
    golden_path = _GOLDEN_DIR / f"{scenario}.html"
    raw = golden_path.read_bytes()
    assert b"\r" not in raw, f"{scenario} golden contains CRLF"
    text = raw.decode("utf-8")
    # No backslash path separators leaked from os.sep.
    assert "\\" not in text, f"{scenario} golden contains a backslash"
