from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import __version__, diagnostics
from code_review_loop._compat_jsonschema import Draft202012Validator, validate
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from tests.support import application_runner

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "docs" / "52-api" / "schemas"
ARTIFACT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "artifacts"


def _load_schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _validation_error_paths(errors: list[object]) -> list[object]:
    paths: list[object] = []
    for error in errors:
        path = getattr(error, "path", None)
        if path is None:
            paths.append(str(error))
        else:
            paths.append(list(path))
    return paths


def test_schema_files_are_valid_draft_2020_12():
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def _assert_v1_schema_history_baselines_are_present_and_current() -> None:
    history_dir = SCHEMA_DIR / "_history"

    for path in sorted(SCHEMA_DIR.glob("*-v1.schema.json")):
        history_path = history_dir / path.name
        assert history_path.is_file(), f"missing schema history baseline for {path.name}"
        assert history_path.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_v1_schema_history_baselines_are_present_and_current():
    _assert_v1_schema_history_baselines_are_present_and_current()


def test_no_unintentional_breaks():
    _assert_v1_schema_history_baselines_are_present_and_current()


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
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = application_runner.run_loop(config, runner).to_dict()
    summary_payload = json.loads(
        (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    )

    validate(summary_payload, schema)
    assert summary["schema_version"] == "1.0"
    assert summary_payload["cli_version"] == __version__
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


def test_routing_schema_accepts_unbounded_timeouts():
    schema = _load_schema("routing-v1.schema.json")
    payload = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "iteration": 1,
        "source_triage_artifact": "triage-1.json",
        "policy_decision": {
            "matched_rule_ids": [],
            "decision": "proposal_accepted",
            "rationale": "accepted",
        },
        "effective_route": {
            "route_tier": "efficient",
            "harness": "codex",
            "model": "gpt-test",
            "reasoning_effort": "low",
            "sandbox": "workspace-write",
            "timeout_seconds": 0,
        },
        "fallbacks_considered": [],
        "prompt": {
            "path": "remediation-1-prompt.txt",
            "sha256": "a" * 64,
            "bytes": 1,
            "fragments": [],
        },
    }

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_routing_schema_accepts_fractional_timeouts():
    schema = _load_schema("routing-v1.schema.json")
    payload = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "iteration": 1,
        "source_triage_artifact": "triage-1.json",
        "policy_decision": {
            "matched_rule_ids": [],
            "decision": "proposal_accepted",
            "rationale": "accepted",
        },
        "effective_route": {
            "route_tier": "efficient",
            "harness": "codex",
            "model": "gpt-test",
            "reasoning_effort": "low",
            "sandbox": "workspace-write",
            "timeout_seconds": 0.5,
        },
        "fallbacks_considered": [],
        "prompt": {
            "path": "remediation-1-prompt.txt",
            "sha256": "a" * 64,
            "bytes": 1,
            "fragments": [],
        },
    }

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_routing_schema_rejects_negative_timeouts():
    schema = _load_schema("routing-v1.schema.json")
    payload = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "iteration": 1,
        "source_triage_artifact": "triage-1.json",
        "policy_decision": {
            "matched_rule_ids": [],
            "decision": "proposal_accepted",
            "rationale": "accepted",
        },
        "effective_route": {
            "route_tier": "efficient",
            "harness": "codex",
            "model": "gpt-test",
            "reasoning_effort": "low",
            "sandbox": "workspace-write",
            "timeout_seconds": -1,
        },
        "fallbacks_considered": [],
        "prompt": {
            "path": "remediation-1-prompt.txt",
            "sha256": "a" * 64,
            "bytes": 1,
            "fragments": [],
        },
    }

    errors = list(Draft202012Validator(schema).iter_errors(payload))

    paths = _validation_error_paths(errors)
    assert ["effective_route", "timeout_seconds"] in paths or any(
        ".effective_route.timeout_seconds" in path for path in paths if isinstance(path, str)
    )


def test_routing_schema_accepts_minimal_reasoning_effort():
    schema = _load_schema("routing-v1.schema.json")
    payload = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "iteration": 1,
        "source_triage_artifact": "triage-1.json",
        "policy_decision": {
            "matched_rule_ids": [],
            "decision": "proposal_accepted",
            "rationale": "accepted",
        },
        "effective_route": {
            "route_tier": "efficient",
            "harness": "codex",
            "model": "gpt-test",
            "reasoning_effort": "minimal",
            "sandbox": "workspace-write",
            "timeout_seconds": 1,
        },
        "model_proposal": {
            "route_tier": "efficient",
            "harness": "codex",
            "model": "gpt-test",
            "reasoning_effort": "minimal",
            "sandbox": "workspace-write",
            "timeout_seconds": 1,
            "rationale": "accepted",
        },
        "fallbacks_considered": [],
        "prompt": {
            "path": "remediation-1-prompt.txt",
            "sha256": "a" * 64,
            "bytes": 1,
            "fragments": [],
        },
    }

    validate(payload, schema)


def test_routing_outcome_schema_rejects_negative_metrics():
    schema = _load_schema("routing-outcome-v1.schema.json")
    payload = {
        "schema_version": "1.0",
        "run_id": "run-1",
        "iteration": 1,
        "source_routing_artifact": "routing-1.json",
        "exit_code": 0,
        "wall_time_seconds": -0.1,
        "checks_passed": True,
        "cost_usd": -1,
        "tokens_consumed": -1,
    }

    errors = list(Draft202012Validator(schema).iter_errors(payload))

    paths = _validation_error_paths(errors)
    assert ["wall_time_seconds"] in paths or any(".wall_time_seconds" in path for path in paths if isinstance(path, str))
    assert ["cost_usd"] in paths or any(".cost_usd" in path for path in paths if isinstance(path, str))
    assert ["tokens_consumed"] in paths or any(".tokens_consumed" in path for path in paths if isinstance(path, str))
