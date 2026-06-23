"""Tests for the ``revrem report --format json`` index (REVREM-PLAN-005 T1).

The JSON index (schema ``report-index-v1``) is the machine-readable companion
to the HTML report — the minimum payload ``post_pr_comment.py`` needs to build
a PR comment body without re-reading raw events or summary. It is a versioned
cross-boundary contract (Contract #8), so every produced index validates
against the schema, and a golden snapshot locks the clear-run shape against
drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_review_loop import events
from code_review_loop._compat_jsonschema import Draft202012Validator, validate
from code_review_loop.cli.commands import report as report_command
from code_review_loop.report_html import build_report_index
from tests.support.run_fixtures import RUN_SCENARIOS, load_run
from tests.support.snapshot import assert_snapshot

ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_DIR = ROOT / "docs" / "52-api" / "schemas"


def _load_schema(name: str) -> dict[str, object]:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


_REPORT_INDEX_SCHEMA = _load_schema("report-index-v1.schema.json")


def _load(name: str) -> tuple[dict, list]:
    run_dir = load_run(name)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    event_records, _ = events.read_events(run_dir / events.EVENTS_FILENAME)
    return summary, event_records


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_report_index_validates_against_schema(scenario: str):
    summary, event_records = _load(scenario)
    idx = build_report_index(summary, event_records)
    validate(idx, _REPORT_INDEX_SCHEMA)


def test_report_index_validates_with_triage_findings_including_unknown_severity():
    """top_findings[].severity is schema-enum-constrained (critical/high/medium/low).

    A model that returns an out-of-enum severity ("info") or omits the key must
    not produce a structurally invalid index. The renderer clamps such values
    into the enum so every index validates downstream. This also closes a test
    gap: the parametrized schema test above passes triage_findings=None, so
    top_findings is always [] and the enum was never exercised.
    """
    summary = {
        "run_id": "r1",
        "final_status": "findings",
        "artifact_paths": {},
    }
    triage_findings = [
        {
            "confirmed_findings": [
                {"severity": "critical", "affected_paths": ["src/a.py"], "summary": "real"},
                {"severity": "INFO", "affected_paths": ["src/b.py"], "summary": "out of enum"},
                {"affected_paths": ["src/c.py"], "summary": "missing severity"},
            ]
        }
    ]
    idx = build_report_index(summary, [], triage_findings=triage_findings)
    # Must validate despite the out-of-enum / missing severities in the source.
    validate(idx, _REPORT_INDEX_SCHEMA)
    severities = {f["severity"] for f in idx["top_findings"]}
    assert severities == {"critical", "low"}  # "INFO" and missing both clamp to "low"
    # finding_counts must clamp identically — no stray "info" key, and the
    # clamped tally must agree with top_findings (the index must not
    # self-contradict). Guards _count_findings_by_severity: top_findings was
    # already clamped before this fix, so without this assertion the counts bug
    # would pass silently.
    assert set(idx["finding_counts"]) == {"critical", "high", "medium", "low"}
    assert idx["finding_counts"]["critical"] == 1
    assert idx["finding_counts"]["low"] == 2  # "INFO" + missing severity


def test_report_index_schema_requires_baseline_finding_count_keys():
    idx = {
        "schema_version": "1.0",
        "run_id": "r1",
        "final_status": "clear",
        "stopped_reason": "review_clear",
        "finding_counts": {"critical": 0, "high": 0, "medium": 0},
        "suppression_count": 0,
        "cost_usd": None,
        "top_findings": [],
        "artifact_paths": {},
    }

    validator = Draft202012Validator(_REPORT_INDEX_SCHEMA)
    errors = list(validator.iter_errors(idx))

    assert any(error.validator == "required" and "low" in str(error) for error in errors)


def test_artifact_paths_preserve_list_shape():
    """List-valued artifact paths (triage/reviews/...) must stay lists, not be
    flattened to repr strings like "['triage-1.json']" (GPT review #3). The
    schema allows arrays; the PR comment / consumers rely on the real shape."""
    summary = {
        "run_id": "r1",
        "artifact_paths": {
            "summary": "summary.json",
            "triage": ["triage-1.json", "triage-2.json"],
            "checks": [],
        },
    }
    idx = build_report_index(summary, [], redact=True)
    ap = idx["artifact_paths"]
    assert ap["summary"] == "summary.json"
    assert ap["triage"] == ["triage-1.json", "triage-2.json"]
    assert ap["checks"] == []


def test_report_index_normalizes_windows_path_separators():
    summary = {
        "run_id": "r1",
        "final_status": "findings",
        "artifact_paths": {
            "summary": "artifacts\\summary.json",
            "triage": ["artifacts\\triage-1.json"],
        },
    }
    triage_findings = [
        {
            "confirmed_findings": [
                {
                    "severity": "medium",
                    "affected_paths": ["src\\app.py"],
                    "summary": "Windows-style path",
                },
            ]
        }
    ]

    idx = build_report_index(
        summary, [], redact=True, triage_findings=triage_findings
    )

    validate(idx, _REPORT_INDEX_SCHEMA)
    assert idx["artifact_paths"]["summary"] == "artifacts/summary.json"
    assert idx["artifact_paths"]["triage"] == ["artifacts/triage-1.json"]
    assert idx["top_findings"][0]["file"] == "src/app.py"


def test_artifact_paths_are_redacted_when_redact_true():
    """An absolute run dir under the user's home must be redacted in the index
    when redact=True (GPT review #7). redact_text scrubs the current home to
    [REDACTED:home]; real runs use relative paths, but a local absolute path is
    a genuine leak vector."""
    import os

    home = os.path.expanduser("~")
    summary = {
        "run_id": "r1",
        "artifact_paths": {
            "artifact_dir": f"{home}/secret/runs/x",
            "triage": [f"{home}/secret/runs/x/triage-1.json"],
        },
    }
    idx = build_report_index(summary, [], redact=True)
    assert home not in idx["artifact_paths"]["artifact_dir"]
    assert "[REDACTED:home]" in idx["artifact_paths"]["artifact_dir"]
    assert home not in idx["artifact_paths"]["triage"][0]


def test_report_index_includes_quota_failure_summary():
    summary = {
        "run_id": "r-quota",
        "final_status": "error",
        "stopped_reason": "review_failed",
        "artifact_paths": {},
        "phase_failures": [
            {
                "phase": "review",
                "iteration": "1",
                "failure": {
                    "reason": "provider_quota_exhausted",
                    "detail": "provider quota exhausted",
                    "transient": False,
                },
            }
        ],
    }

    idx = build_report_index(summary, [], redact=True)

    validate(idx, _REPORT_INDEX_SCHEMA)
    assert idx["failure_summary"] == {
        "phase": "review",
        "iteration": "1",
        "reason": "provider_quota_exhausted",
        "detail": "provider quota exhausted",
        "message": (
            "Provider quota/billing exhausted. The model provider refused the "
            "request because account, project, or billing capacity is exhausted; "
            "fix provider billing/quota or credentials, then rerun."
        ),
    }


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_report_command_json_output_validates_against_schema(
    scenario: str, capsys
):
    """``revrem report --format json`` prints canonical JSON to stdout."""
    run_dir = load_run(scenario)
    exit_code = report_command.main([str(run_dir), "--format", "json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    validate(payload, _REPORT_INDEX_SCHEMA)
    assert payload["schema_version"] == "1.0"


def test_report_command_json_ignores_output_flag(capsys, tmp_path: Path):
    """With --format json, --output is ignored; output lands on stdout."""
    run_dir = load_run("clear")
    bogus_output = tmp_path / "should-not-be-written.json"
    exit_code = report_command.main(
        [str(run_dir), "--format", "json", "--output", str(bogus_output)]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    # stdout is valid JSON.
    json.loads(captured.out)
    # --output was ignored: no file written.
    assert not bogus_output.exists()


def test_report_command_ignores_triage_artifacts_outside_run_dir(
    capsys, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps(
            {
                "confirmed_findings": [
                    {
                        "severity": "critical",
                        "affected_paths": ["outside.py"],
                        "summary": "outside finding",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "triage-1.json").write_text(
        json.dumps(
            {
                "confirmed_findings": [
                    {
                        "severity": "low",
                        "affected_paths": ["inside.py"],
                        "summary": "inside finding",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / events.EVENTS_FILENAME).write_text("", encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "scoped-run",
                "final_status": "findings",
                "stopped_reason": "max_iterations_reached",
                "artifact_paths": {
                    "triage": [
                        "../outside.json",
                        str(outside),
                        "triage-1.json",
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = report_command.main([str(run_dir), "--format", "json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [finding["title"] for finding in payload["top_findings"]] == [
        "inside finding"
    ]


def test_report_command_loads_absolute_triage_artifact_inside_run_dir(
    capsys, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    triage_path = run_dir / "triage-1.json"
    triage_path.write_text(
        json.dumps(
            {
                "confirmed_findings": [
                    {
                        "severity": "high",
                        "affected_paths": ["prod.py"],
                        "summary": "production-shaped absolute triage path",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / events.EVENTS_FILENAME).write_text("", encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "absolute-in-run",
                "final_status": "findings",
                "stopped_reason": "max_iterations_reached",
                "artifact_paths": {"triage": [str(triage_path)]},
            }
        ),
        encoding="utf-8",
    )

    exit_code = report_command.main([str(run_dir), "--format", "json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["finding_counts"]["high"] == 1
    assert [finding["title"] for finding in payload["top_findings"]] == [
        "production-shaped absolute triage path"
    ]


def test_clear_run_index_matches_golden_snapshot():
    """Lock the clear-run index shape against schema drift."""
    summary, event_records = _load("clear")
    idx = build_report_index(summary, event_records)
    assert_snapshot("report_index_clear", idx)


def test_schema_file_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(_REPORT_INDEX_SCHEMA)
