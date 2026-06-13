"""Tests for the inner-check-retry path of ``runner_shell``.

These tests guard the contract documented in
``docs/70-devex/devex-001-using-code-review-loop.md``:

* On-disk artifact stems keep the operator-friendly ``-retry-N`` suffix
  (e.g. ``remediation-1-retry-1.txt``).
* ``phase_start`` / ``phase_result`` events emitted while an inner-check
  retry is in flight use a schema-compatible dotted ``iteration`` label
  (e.g. ``"1.1"``) so ``events.jsonl`` validates against
  ``docs/52-api/schemas/events-v1.schema.json``.

Regression fingerprint: ``f1:inner-check-retry-label-schema-incompat``.
"""

from __future__ import annotations

import json
from pathlib import Path

from code_review_loop._compat_jsonschema import Draft202012Validator
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, ProcessRunner
from tests.support import application_runner

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "52-api" / "schemas" / "events-v1.schema.json"


def _load_events_schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_artifact_label_keeps_legacy_retry_suffix() -> None:
    from code_review_loop.iteration_labels import (
        artifact_label,
        event_iteration_label,
    )

    assert artifact_label(1, 0) == "1"
    assert artifact_label(1, 1) == "1-retry-1"
    assert artifact_label(3, 2) == "3-retry-2"
    assert event_iteration_label(1, 0) == "1"
    assert event_iteration_label(1, 1) == "1.1"
    assert event_iteration_label(3, 2) == "3.2"


def test_event_iteration_label_matches_events_v1_schema_pattern() -> None:
    from code_review_loop.iteration_labels import event_iteration_label

    schema = _load_events_schema()
    validator = Draft202012Validator(schema)

    for retry_count in range(0, 3):
        for iteration in range(1, 4):
            label = event_iteration_label(iteration, retry_count)
            envelope = {
                "schema_version": "1.0",
                "run_id": "run-1",
                "seq": 1,
                "ts": "2026-05-12T00:00:00Z",
                "kind": "phase_start",
                "phase": "remediate",
                "iteration": label,
                "payload": {"summary": "start"},
            }
            errors = list(validator.iter_errors(envelope))
            assert errors == [], (label, errors)


def _build_check_runner(
    check_outcomes: list[tuple[int, str]],
) -> ProcessRunner:
    iterator = iter(check_outcomes)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[0] == "codex" and args[1] == "review":
            return CommandResult(list(args), 0, stdout="Issue found.\nREVIEW_STATUS: findings\n")
        if args[0] == "pytest":
            rc, out = next(iterator)
            return CommandResult(list(args), rc, stdout=out)
        return CommandResult(list(args), 0, stdout="remediated\n")

    return runner


def test_inner_check_retry_emits_schema_valid_event_labels(tmp_path: Path) -> None:
    runner = _build_check_runner(
        [
            (1, "1 FAILED\n"),
            (0, "1 passed\n"),
        ]
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        inner_check_retries=1,
        final_review=False,
    )

    summary = application_runner.run_loop(config, runner).to_dict()

    artifact_dir = config.artifact_dir
    assert (artifact_dir / "remediation-1.txt").exists()
    assert (artifact_dir / "remediation-1-retry-1.txt").exists()
    assert (artifact_dir / "check-1-2.txt").exists()
    assert (artifact_dir / "check-1-retry-1-2.txt").exists()
    assert not (artifact_dir / "remediation-1.1.txt").exists()
    assert summary["iterations"][0]["check_attempts"] == [
        {
            "retry": 0,
            "artifact_label": "1",
            "display_label": "1",
            "check_failures": 1,
            "checks": [
                {
                    "command": "git status -z --porcelain=v1 --untracked-files=all",
                    "status": "passed",
                    "artifact": "check-1-1.txt",
                },
                {
                    "command": "pytest -q",
                    "status": "failed",
                    "artifact": "check-1-2.txt",
                }
            ],
        },
        {
            "retry": 1,
            "artifact_label": "1-retry-1",
            "display_label": "1.1",
            "check_failures": 0,
            "checks": [
                {
                    "command": "git status -z --porcelain=v1 --untracked-files=all",
                    "status": "passed",
                    "artifact": "check-1-retry-1-1.txt",
                },
                {
                    "command": "pytest -q",
                    "status": "passed",
                    "artifact": "check-1-retry-1-2.txt",
                }
            ],
        },
    ]

    events_path = artifact_dir / "events.jsonl"
    assert events_path.is_file()
    schema = _load_events_schema()
    validator = Draft202012Validator(schema)

    remediate_labels: list[str] = []
    check_labels: list[str] = []
    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            errors = list(validator.iter_errors(record))
            assert errors == [], (record, errors)
            phase = record.get("phase")
            iteration = record.get("iteration")
            kind = record.get("kind")
            assert "retry" not in str(iteration), record
            if phase == "remediate" and kind in {"phase_start", "phase_result"}:
                remediate_labels.append(str(iteration))
            elif phase == "check" and kind in {"phase_start", "phase_result"}:
                check_labels.append(str(iteration))

    assert "1" in remediate_labels, remediate_labels
    assert "1.1" in remediate_labels, remediate_labels
    assert "1-retry-1" not in remediate_labels, remediate_labels

    dotted_check_labels = [label for label in check_labels if "." in label]
    assert any(label.startswith("1.1.") for label in dotted_check_labels), check_labels
    assert all("retry" not in label for label in check_labels), check_labels


def test_inner_check_retry_events_jsonl_validates_against_schema(
    tmp_path: Path,
) -> None:
    """Regression guard: the produced events.jsonl must validate cleanly."""
    runner = _build_check_runner(
        [
            (1, "1 FAILED\n"),
            (0, "1 passed\n"),
        ]
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        inner_check_retries=1,
        final_review=False,
    )

    application_runner.run_loop(config, runner)

    events_path = config.artifact_dir / "events.jsonl"
    schema = _load_events_schema()
    validator = Draft202012Validator(schema)

    seen = 0
    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            errors = list(validator.iter_errors(record))
            assert errors == [], (record, errors)
            assert "retry" not in str(record.get("iteration")), record
            seen += 1

    assert seen > 0


def test_inner_check_retry_with_no_retry_path_still_emits_schema_valid_events(
    tmp_path: Path,
) -> None:
    """The schema must also validate the no-retry case as a baseline.

    Guards against accidentally widening the iteration label contract
    to a form the no-retry path does not match.
    """
    runner = _build_check_runner([(0, "1 passed\n")])
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        inner_check_retries=0,
        final_review=False,
    )

    application_runner.run_loop(config, runner)

    events_path = config.artifact_dir / "events.jsonl"
    schema = _load_events_schema()
    validator = Draft202012Validator(schema)

    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            errors = list(validator.iter_errors(record))
            assert errors == [], (record, errors)
