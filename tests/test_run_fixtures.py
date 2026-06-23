"""Meta-test for the finished-run fixture catalogue (REVREM-PLAN-005 T0).

Guards the shared inputs every v0.5.0 read-only consumer (``revrem report``,
the GitHub Action) reads: each scenario directory must contain a valid
``summary.json`` + ``events.jsonl`` pair that validates against the frozen
artifact schemas. A drift here would surface as a confusing failure in a
downstream report test, so it is caught at the source.
"""

from __future__ import annotations

import json

import pytest

from code_review_loop._compat_jsonschema import validate
from tests.support.run_fixtures import RUN_FIXTURE_DIR, RUN_SCENARIOS, load_run


def _load_schema(name: str) -> dict[str, object]:
    from pathlib import Path

    schema_dir = Path(__file__).resolve().parents[1] / "docs" / "52-api" / "schemas"
    return json.loads((schema_dir / name).read_text(encoding="utf-8"))


_SUMMARY_SCHEMA = _load_schema("summary-v1.schema.json")
_EVENTS_SCHEMA = _load_schema("events-v1.schema.json")


def test_run_catalogue_has_expected_scenarios():
    """The catalogue is a stable contract for downstream tests; lock it."""
    assert set(RUN_SCENARIOS) == {
        "clear",
        "findings_remediated",
        "findings_remaining",
        "findings_with_triage",
        "timeout",
        "check_failure",
        "cost_ceiling",
        "cancelled",
        "all_suppressed",
    }


def test_run_catalogue_matches_on_disk_directories():
    """The catalogue must match the actual fixture directories on disk.

    A stray directory (e.g. an abandoned experiment) or a missing one would
    otherwise surface as a confusing failure in a downstream report test. This
    catches both drift directions at the source.
    """
    on_disk = {p.name for p in RUN_FIXTURE_DIR.iterdir() if p.is_dir()}
    assert on_disk == set(RUN_SCENARIOS), (
        f"fixture dirs on disk do not match RUN_SCENARIOS; "
        f"only-on-disk={sorted(on_disk - set(RUN_SCENARIOS))}, "
        f"only-in-catalogue={sorted(set(RUN_SCENARIOS) - on_disk)}"
    )


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_run_fixture_has_summary_and_events(scenario: str):
    run_dir = load_run(scenario)
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "events.jsonl").is_file()


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_run_fixture_summary_validates_against_schema(scenario: str):
    run_dir = load_run(scenario)
    payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    validate(payload, _SUMMARY_SCHEMA)


@pytest.mark.parametrize("scenario", RUN_SCENARIOS)
def test_run_fixture_events_validate_against_schema(scenario: str):
    run_dir = load_run(scenario)
    text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, f"{scenario}: events.jsonl is empty"
    for lineno, line in enumerate(lines, 1):
        try:
            validate(json.loads(line), _EVENTS_SCHEMA)
        except Exception as exc:  # pragma: no cover - diagnostic surface only
            raise AssertionError(f"{scenario}: events.jsonl line {lineno} invalid: {exc}") from exc
