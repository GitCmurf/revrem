from __future__ import annotations

import json
import time
from decimal import Decimal
from importlib import import_module

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop import application, budgets, events
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import OutcomeFailed
from code_review_loop.core.ports import CommandResult
from code_review_loop.runtime import RunLoopFailed

cli_main = import_module("code_review_loop.cli.main")


def test_loop_caps_remediation_passes_and_runs_final_review(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
        return CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "findings"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert "Still failing." in summary["latest_review_excerpt"]
    assert [call[0][1] for call in calls] == ["review", "exec", "review", "exec", "review"]
    assert len(summary["iterations"]) == 2
    assert (tmp_path / "artifacts" / "review-1.txt").exists()
    assert (tmp_path / "artifacts" / "review-2.txt").exists()
    assert not (tmp_path / "artifacts" / "1.txt").exists()
    assert summary["artifact_paths"]["reviews"] == [
        str(tmp_path / "artifacts" / "review-1.txt"),
        str(tmp_path / "artifacts" / "review-2.txt"),
        str(tmp_path / "artifacts" / "review-final.txt"),
    ]


def test_loop_finishes_clear_when_final_review_goes_green(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            if len([call for call in calls if call[0][1] == "review"]) == 1:
                return CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
            return CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")
        return CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "review_clear"
    assert [call[0][1] for call in calls] == ["review", "exec", "review"]


def test_loop_continues_after_check_failure_and_feeds_output_into_next_pass(tmp_path):
    """A failing --check must not abort the loop; its output is fed into the next remediation."""
    calls: list[tuple[list[str], str | None]] = []
    # review-1 → findings; review-2 → findings (triggers iter-2 exec); review-final → clear
    review_outputs = iter([
        "Missing coverage.\nREVIEW_STATUS: findings\n",
        "Still some gaps.\nREVIEW_STATUS: findings\n",
        "All good.\nREVIEW_STATUS: clear\n",
    ])
    # check fails after iter-1, passes after iter-2
    check_outputs = iter([(1, "1 FAILED\n"), (0, "1 passed\n")])

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[0] == "codex" and args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            rc, out = next(check_outputs)
            return CommandResult(list(args), rc, stdout=out)
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest tests/",),
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "clear"

    # Both remediation passes ran (loop was not aborted by the check failure)
    exec_calls = [c for c in calls if c[0][0] == "codex" and c[0][1] == "exec"]
    assert len(exec_calls) == 2, f"expected 2 exec calls, got {len(exec_calls)}"

    # The second remediation prompt must include the check-failure output from iter-1
    second_prompt = exec_calls[1][1]
    assert second_prompt is not None and "1 FAILED" in second_prompt
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    check_events = [
        event
        for event in records
        if event.kind == "check_result"
        and event.payload["command"] == "pytest tests/"
    ]
    assert truncated is False
    assert [event.payload["status"] for event in check_events] == ["failed", "passed"]
    assert check_events[0].payload["command"] == "pytest tests/"
    assert check_events[0].payload["artifact"] == "check-1-2.txt"


def test_pending_check_failure_blocks_early_clear_status(tmp_path):
    """A clear review cannot finish the loop while a previous --check failure is pending."""
    calls: list[tuple[list[str], str | None]] = []
    review_outputs = iter([
        "Missing coverage.\nREVIEW_STATUS: findings\n",
        "All good.\nREVIEW_STATUS: clear\n",
        "All good.\nREVIEW_STATUS: clear\n",
    ])
    check_outputs = iter([(1, "1 FAILED\n"), (1, "still failing\n")])

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[0] == "codex" and args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            rc, out = next(check_outputs)
            return CommandResult(list(args), rc, stdout=out)
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest tests/",),
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "findings"
    assert summary["pending_check_failures"] is True
    assert summary["stopped_reason"] == "max_iterations_reached_with_check_failures"

    exec_calls = [c for c in calls if c[0][0] == "codex" and c[0][1] == "exec"]
    assert len(exec_calls) == 2
    assert exec_calls[1][1] is not None and "1 FAILED" in exec_calls[1][1]


def test_timeout_only_check_failure_skips_inner_remediation_retry(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[0] == "codex" and args[1] == "review":
            return CommandResult(list(args), 0, stdout="Fix it.\nREVIEW_STATUS: findings\n")
        if args[0] == "pytest":
            return CommandResult(
                list(args),
                -1,
                stderr="Command timed out after 300 seconds\n",
            )
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        final_review=False,
        inner_check_retries=1,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "unknown"
    assert summary["pending_check_failures"] is True
    assert summary["stopped_reason"] == "max_iterations_reached"

    exec_calls = [c for c in calls if c[0][0] == "codex" and c[0][1] == "exec"]
    assert len(exec_calls) == 1
    assert not (tmp_path / "artifacts" / "remediation-1-retry-1.txt").exists()

    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    assert truncated is False
    assert any(
        event.kind == "warning"
        and event.phase == "check"
        and event.payload.get("message")
        == "check failures are timeout-only; skipping remediation retry"
        for event in records
    )


def test_skip_final_review_reports_unknown_status(tmp_path):
    """With --skip-final-review the loop must not report a stale pre-remediation status."""
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout="Issues found.\nREVIEW_STATUS: findings\n")
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "unknown", (
        "status after last remediation is unknowable without a follow-up review"
    )
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert "Issues found." in summary["latest_review_excerpt"]


def test_final_check_failure_prevents_clear_status(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest tests/",),
    )

    review_outputs = iter(
        [
            "Actionable finding.\nREVIEW_STATUS: findings\n",
            "All good.\nREVIEW_STATUS: clear\n",
        ]
    )

    def sequenced_runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[0] == "codex" and args[1] == "review":
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            return CommandResult(list(args), 1, stdout="1 FAILED\n")
        return CommandResult(list(args), 0, stdout="fixed\n")

    summary = runner_mod.run_loop(config, sequenced_runner).to_dict()

    assert summary["final_status"] == "findings"
    assert summary["pending_check_failures"] is True
    assert summary["stopped_reason"] == "max_iterations_reached_with_check_failures"

def test_loop_writes_failure_summary_when_remediation_fails(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout="Full review comments:\n\n- [P1] Fix\n")
        return CommandResult(list(args), 1, stderr="Error: turn/start failed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    try:
        runner_mod.run_loop(config, runner)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected remediation failure")

    summary = (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    failure_events = [event for event in records if event.kind == "failure"]

    assert '"final_status": "error"' in summary
    assert '"stopped_reason": "remediation_failed"' in summary
    assert '"artifact_paths"' in summary
    assert "review-1.txt" in summary
    assert '"1.txt"' not in summary
    assert truncated is False
    assert any(event.payload.get("reason") == "remediation_failed" for event in failure_events)


def test_loop_stops_before_model_call_when_wall_budget_exceeded(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(args)
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=budgets.BudgetConfig(max_wall_seconds=0),
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner, budget_state=budgets.BudgetState(started_at_monotonic=0))

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert calls == []
    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"
    assert summary["final_status"] == "error"
    assert summary["stopped_reason"] == "budget_ceiling_hit"
    assert summary["budgets"]["max_wall_seconds"] == 0
    assert summary["budgets"]["tokens"] is None
    assert summary["budgets"]["usd"] is None
    assert truncated is False
    assert any(event.kind == "cost_ceiling_hit" and event.payload["ceiling"] == "wall" for event in records)


def test_loop_emits_budget_soft_warning_before_model_call(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=budgets.BudgetConfig(max_wall_seconds=100, soft_warn_fraction=0.5),
    )

    runner_mod.run_loop(config, runner, budget_state=budgets.BudgetState(started_at_monotonic=time.monotonic() - 60))

    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert truncated is False
    assert any(
        event.kind == "warning" and event.payload.get("reason") == "wall_budget_soft_warning"
        for event in records
    )


def test_loop_records_token_charge_and_stops_before_next_model_call(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: findings\n", tokens=10)

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=budgets.BudgetConfig(max_tokens=10),
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert len(calls) == 1
    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"
    assert summary["budgets"]["tokens"] == 10
    assert summary["budgets"]["usd"] is None
    assert (tmp_path / "artifacts" / "review-1.txt").read_text(encoding="utf-8") == "REVIEW_STATUS: findings\n"
    assert truncated is False
    assert any(event.kind == "cost_charge" and event.payload["tokens"] == 10 for event in records)
    assert any(event.kind == "cost_ceiling_hit" and event.payload["ceiling"] == "tokens" for event in records)


def test_loop_records_usd_charge_and_stops_before_next_model_call(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(
            list(args),
            0,
            stdout="REVIEW_STATUS: findings\n",
            usd=Decimal("1.25"),
        )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=budgets.BudgetConfig(max_usd=Decimal("1.25")),
    )

    with pytest.raises(RunLoopFailed):
        runner_mod.run_loop(config, runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    records, _truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert summary["budgets"]["tokens"] is None
    assert summary["budgets"]["usd"] == "1.25"
    assert any(event.kind == "cost_charge" and event.payload["usd"] == "1.25" for event in records)
    assert any(event.kind == "cost_ceiling_hit" and event.payload["ceiling"] == "usd" for event in records)


def test_main_returns_exit_code_3_for_budget_ceiling(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    summary = {
        "run_id": "run-1",
        "final_status": "error",
        "stopped_reason": "budget_ceiling_hit",
        "iterations": [],
    }

    def fake_run_loop(_config, **_kwargs):
        raise RunLoopFailed(
            summary,
            "wall budget exceeded",
            outcome=OutcomeFailed(reason="budget_ceiling_hit", error="wall budget exceeded"),
        )

    monkeypatch.setattr(application, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--max-wall-seconds", "0", "--no-run-history"])

    assert exit_code == 3
    assert "wall budget exceeded" in capsys.readouterr().err


def test_loop_writes_cancellation_summary_when_interrupted(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        raise KeyboardInterrupt

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    diagnostics_payload = json.loads(
        (tmp_path / "artifacts" / "diagnostics.json").read_text(encoding="utf-8")
    )
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert str(excinfo.value) == "cancelled by operator"
    assert summary["final_status"] == "error"
    assert summary["stopped_reason"] == "cancelled"
    assert summary["error"] == "cancelled by operator"
    assert summary["artifact_paths"]["summary"] == str(tmp_path / "artifacts" / "summary.json")
    assert summary["artifact_paths"]["diagnostics"] == [str(tmp_path / "artifacts" / "diagnostics.json")]
    assert diagnostics_payload["issues"][0]["code"] == "revrem.run.cancelled"
    assert truncated is False
    assert any(
        event.kind == "cancellation" and event.payload.get("reason") == "operator_interrupt"
        for event in records
    )
    assert any(event.kind == "summary" and event.payload.get("summary") == "cancelled" for event in records)
