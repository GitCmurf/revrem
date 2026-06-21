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


def test_clear_run_index_matches_golden_snapshot():
    """Lock the clear-run index shape against schema drift."""
    summary, event_records = _load("clear")
    idx = build_report_index(summary, event_records)
    assert_snapshot("report_index_clear", idx)


def test_schema_file_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(_REPORT_INDEX_SCHEMA)
