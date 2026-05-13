from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import cli as cli_module
from code_review_loop import diagnostics
from code_review_loop._compat_jsonschema import Draft202012Validator, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "52-api" / "schemas"
ARTIFACT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "artifacts"


def _load_schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_schema_files_are_valid_draft_2020_12():
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_v1_schema_history_baselines_are_present_and_current():
    history_dir = SCHEMA_DIR / "_history"

    for path in sorted(SCHEMA_DIR.glob("*-v1.schema.json")):
        history_path = history_dir / path.name
        assert history_path.is_file(), f"missing schema history baseline for {path.name}"
        assert history_path.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_doctor_payload_validates_against_diagnostics_schema():
    issues = [
        diagnostics.DiagnosticIssue(
            code="revrem.preflight.invalid_base",
            severity="blocking",
            message="Base ref 'missing' does not resolve.",
            hint="Fetch the target branch or pass --base with an existing ref.",
            evidence={"base": "missing"},
        )
    ]

    validate(
        diagnostics.doctor_payload(issues),
        _load_schema("diagnostics-v1.schema.json"),
    )


def test_artifact_scenario_fixtures_validate_against_schemas():
    expected_scenarios = {
        "clear",
        "findings",
        "setup_failure",
        "timeout",
        "check_failure",
        "unknown",
    }
    schema_by_name = {
        "summary.json": _load_schema("summary-v1.schema.json"),
        "diagnostics.json": _load_schema("diagnostics-v1.schema.json"),
    }

    assert {path.name for path in ARTIFACT_FIXTURE_DIR.iterdir() if path.is_dir()} == expected_scenarios
    for scenario_dir in sorted(path for path in ARTIFACT_FIXTURE_DIR.iterdir() if path.is_dir()):
        assert (scenario_dir / "summary.json").is_file(), scenario_dir
        for path in sorted(scenario_dir.glob("*.json")):
            schema = schema_by_name.get(path.name)
            assert schema is not None, f"no schema mapped for {path}"
            validate(json.loads(path.read_text(encoding="utf-8")), schema)


def test_summary_schema_validates_generated_summary(tmp_path):
    schema = _load_schema("summary-v1.schema.json")
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix summary contract\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return cli_module.CommandResult(list(args), 0, stdout=next(review_outputs))
        return cli_module.CommandResult(list(args), 0, stdout="fixed\n")

    config = cli_module.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = cli_module.run_loop(config, runner)
    summary_payload = json.loads((tmp_path / "artifacts" / "summary.json").read_text())

    validate(summary_payload, schema)
    assert summary["schema_version"] == "1.0"
    assert summary_payload["cli_version"] == cli_module.__version__
    assert summary_payload["harness"] == "codex"
    assert summary_payload["tokens"] is None
    assert summary_payload["usd"] is None


def test_event_schema_validates_event_envelope():
    schema = _load_schema("events-v1.schema.json")

    validate(
        {
            "schema_version": "1.0",
            "run_id": "run-1",
            "seq": 1,
            "ts": "2026-05-12T00:00:00Z",
            "kind": "summary",
            "phase": None,
            "iteration": None,
            "payload": {},
        },
        schema,
    )
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors({"extra": "missing version"}))
