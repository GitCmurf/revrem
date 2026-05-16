from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_review_loop import cli as MODULE
from code_review_loop import events


def write_resume_run(
    run_dir: Path,
    *,
    stopped_reason: str = "cancelled",
    git_state: dict[str, object] | None = None,
    truncated: bool = False,
    budgets: dict[str, object] | None = None,
    resume_config: dict[str, object] | None = None,
    copy_budget_limits_into_resume_config: bool = True,
) -> None:
    run_dir.mkdir(parents=True)
    resume_config_payload = dict(
        resume_config
        or {
            "base": "main",
            "max_iterations": 1,
            "codex_bin": "codex",
            "review_harness": "fake",
            "remediation_harness": "fake",
            "review_model": "review_clear",
            "remediation_model": "remediation",
            "final_review": True,
            "check_commands": [],
        }
    )
    if budgets is not None and copy_budget_limits_into_resume_config:
        if "max_tokens" in budgets and "max_tokens" not in resume_config_payload:
            resume_config_payload["max_tokens"] = budgets["max_tokens"]
        if "max_usd" in budgets and "max_usd" not in resume_config_payload:
            resume_config_payload["max_usd"] = budgets["max_usd"]
    summary = {
        "run_id": "run-1",
        "base": "main",
        "final_status": "error",
        "stopped_reason": stopped_reason,
        "iterations": [],
        "artifact_paths": {"reviews": [str(run_dir / "review-1.txt")]},
        "resume_config": resume_config_payload,
        "git_state": git_state
        or {
            "head": "head-sha",
            "base": "main",
            "base_commit": "base-sha",
            "merge_base": "merge-sha",
            "available": True,
        },
    }
    if budgets is not None:
        summary["budgets"] = budgets
    (run_dir / "review-1.txt").write_text(
        "Full review comments:\n\n- [P2] Resume this finding.\nREVIEW_STATUS: findings\n",
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    sink = events.JsonlSink(run_dir, "run-1")
    sink.emit("cancellation", phase="run", payload={"reason": "operator_interrupt"})
    sink.emit("summary", payload={"summary": stopped_reason})
    sink.close()
    if truncated:
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"schema_version": "1.0", "run_id": ')


def install_matching_git(monkeypatch, *, head: str = "head-sha", base: str = "base-sha") -> None:
    def fake_git(cwd, args):
        if list(args) == ["rev-parse", "HEAD"]:
            return MODULE.CommandResult(["git", *args], 0, stdout=f"{head}\n")
        if list(args) == ["rev-parse", "--verify", "main^{commit}"]:
            return MODULE.CommandResult(["git", *args], 0, stdout=f"{base}\n")
        return MODULE.CommandResult(["git", *args], 1, stderr="unexpected")

    monkeypatch.setattr(MODULE, "run_git_preflight", fake_git)


def test_resume_preconditions_pass_for_matching_git_state(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(run_dir)
    install_matching_git(monkeypatch)

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert issues == []


def test_resume_preconditions_pass_for_relative_artifact_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = Path(".revrem/runs/run-1")
    write_resume_run(run_dir)
    install_matching_git(monkeypatch)

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert issues == []


def test_resume_preconditions_block_persisted_budget_ceiling(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(
        run_dir,
        stopped_reason="budget_ceiling_hit",
        budgets={
            "max_wall_seconds": 10,
            "max_tokens": 100,
            "max_usd": "1.25",
            "soft_warn_fraction": 0.8,
            "tokens": 100,
            "usd": "0.45",
        },
    )
    install_matching_git(monkeypatch)

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert [issue.code for issue in issues][:1] == ["revrem.resume.token_budget_exhausted"]
    assert any(issue.code == "revrem.resume.token_budget_exhausted" for issue in issues)


def test_resume_preconditions_block_persisted_usd_ceiling(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(
        run_dir,
        stopped_reason="budget_ceiling_hit",
        budgets={
            "max_wall_seconds": 10,
            "max_tokens": 100,
            "max_usd": "0.45",
            "soft_warn_fraction": 0.8,
            "tokens": 42,
            "usd": "0.45",
        },
    )
    install_matching_git(monkeypatch)

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert any(issue.code == "revrem.resume.usd_budget_exhausted" for issue in issues)


def test_resume_preconditions_block_persisted_wall_ceiling(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(
        run_dir,
        stopped_reason="max_iterations_reached",
        budgets={
            "max_wall_seconds": 10,
            "wall_elapsed_seconds": 10,
        },
    )
    install_matching_git(monkeypatch)

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert any(issue.code == "revrem.resume.wall_budget_exhausted" for issue in issues)


def test_resume_run_rejects_persisted_budget_ceiling(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(
        run_dir,
        stopped_reason="budget_ceiling_hit",
        budgets={
            "max_wall_seconds": 10,
            "max_tokens": 100,
            "max_usd": "1.25",
            "soft_warn_fraction": 0.8,
            "tokens": 100,
            "usd": "0.45",
        },
    )
    install_matching_git(monkeypatch)

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("run_loop should not be invoked when the budget ceiling is already exhausted")

    monkeypatch.setattr(MODULE, "run_loop", fail_if_called)

    with pytest.raises(ValueError, match="remaining token budget headroom"):
        MODULE.resume_run(run_dir)

    assert called is False


def test_resume_run_rejects_persisted_wall_budget_ceiling(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(
        run_dir,
        stopped_reason="max_iterations_reached",
        budgets={
            "max_wall_seconds": 10,
            "wall_elapsed_seconds": 10,
        },
    )
    install_matching_git(monkeypatch)

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("run_loop should not be invoked when the wall budget is already exhausted")

    monkeypatch.setattr(MODULE, "run_loop", fail_if_called)

    with pytest.raises(ValueError, match="remaining wall budget headroom"):
        MODULE.resume_run(run_dir)

    assert called is False


def test_resume_run_rejects_legacy_persisted_budget_ceiling(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(
        run_dir,
        stopped_reason="budget_ceiling_hit",
        budgets={
            "max_wall_seconds": 10,
            "max_tokens": 100,
            "max_usd": "1.25",
            "soft_warn_fraction": 0.8,
            "tokens": 100,
            "usd": "0.45",
        },
        copy_budget_limits_into_resume_config=False,
    )
    install_matching_git(monkeypatch)

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("run_loop should not be invoked when the budget ceiling is already exhausted")

    monkeypatch.setattr(MODULE, "run_loop", fail_if_called)

    with pytest.raises(ValueError, match="remaining token budget headroom"):
        MODULE.resume_run(run_dir)

    assert called is False


def test_resume_loop_config_seeds_cumulative_wall_budget_state(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "lexical_git_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(MODULE.budgets, "monotonic", lambda: 112.5)

    def fake_run_git_preflight(cwd, args):
        if list(args) == ["rev-parse", "HEAD"]:
            return MODULE.CommandResult(["git", *args], 0, stdout="head-sha\n")
        if list(args) == ["rev-parse", "--verify", "main^{commit}"]:
            return MODULE.CommandResult(["git", *args], 0, stdout="base-sha\n")
        if list(args) == ["merge-base", "HEAD", "main"]:
            return MODULE.CommandResult(["git", *args], 0, stdout="merge-sha\n")
        return MODULE.CommandResult(["git", *args], 1, stderr="unexpected")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return MODULE.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    monkeypatch.setattr(MODULE, "run_git_preflight", fake_run_git_preflight)

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=MODULE.budgets.BudgetConfig(max_wall_seconds=30),
        budget_state=MODULE.budgets.BudgetState(started_at_monotonic=100.0),
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["budgets"]["wall_elapsed_seconds"] == 12.5

    monkeypatch.setattr(MODULE.budgets, "monotonic", lambda: 200.0)
    resumed = MODULE.resume_loop_config(summary, run_dir=tmp_path / "artifacts")

    assert resumed.budget_state is not None
    assert resumed.budget_state.started_at_monotonic == 187.5


def test_resume_loop_config_uses_legacy_budget_ceiling(tmp_path):
    review_path = tmp_path / "review-1.txt"
    review_path.write_text("REVIEW_STATUS: findings\n", encoding="utf-8")
    summary = {
        "resume_config": {
            "base": "main",
            "max_iterations": 1,
            "codex_bin": "codex",
        },
        "artifact_paths": {"reviews": [str(review_path)]},
        "budgets": {
            "max_wall_seconds": 10,
            "max_tokens": 100,
            "max_usd": "1.25",
            "soft_warn_fraction": 0.8,
            "tokens": 73,
            "usd": "0.45",
        },
    }

    resumed = MODULE.resume_loop_config(summary, run_dir=tmp_path)

    assert resumed.budget_config.max_wall_seconds == 10
    assert resumed.budget_config.max_tokens == 100
    assert str(resumed.budget_config.max_usd) == "1.25"
    assert resumed.budget_config.soft_warn_fraction == 0.8


def test_resume_preconditions_block_head_mismatch(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(run_dir)
    install_matching_git(monkeypatch, head="different-head")

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert [issue.code for issue in issues] == ["revrem.resume.head_mismatch"]


def test_resume_preconditions_block_base_mismatch(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(run_dir)
    install_matching_git(monkeypatch, base="different-base")

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert [issue.code for issue in issues] == ["revrem.resume.base_mismatch"]


def test_resume_preconditions_block_truncated_events(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_resume_run(run_dir, truncated=True)
    install_matching_git(monkeypatch)

    issues = MODULE.resume_precondition_issues(run_dir, cwd=tmp_path)

    assert [issue.code for issue in issues] == ["revrem.resume.truncated_events"]


def test_resume_main_returns_code_4_for_missing_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = MODULE.main(["resume", str(tmp_path / "missing")])

    assert exit_code == 4
    assert "revrem.resume.missing_summary" in capsys.readouterr().out


def test_resume_continues_from_existing_review_artifact(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "run"
    write_resume_run(run_dir)
    install_matching_git(monkeypatch)

    exit_code = MODULE.main(["resume", str(run_dir)])
    resumed_summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert resumed_summary["final_status"] == "clear"
    assert resumed_summary["iterations"][0]["review_source"] == str(run_dir / "review-1.txt")
    assert (run_dir / "review-initial.txt").is_file()
    output = capsys.readouterr().out
    assert "revrem.resume" not in output
    assert "Review-remediation loop: clear" in output


def test_resume_and_uninterrupted_fake_run_have_same_final_status(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    monkeypatch.chdir(tmp_path)
    run_dir = tmp_path / "run"
    uninterrupted_dir = tmp_path / "uninterrupted"
    write_resume_run(run_dir)
    install_matching_git(monkeypatch)

    resumed = MODULE.resume_run(run_dir)
    uninterrupted = MODULE.run_loop(
        MODULE.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=uninterrupted_dir,
            review_harness="fake",
            review_model="review_clear",
        )
    )

    assert resumed["final_status"] == uninterrupted["final_status"] == "clear"
    assert resumed["stopped_reason"] == uninterrupted["stopped_reason"] == "review_clear"
