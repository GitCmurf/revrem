from __future__ import annotations

import json
import os
from decimal import Decimal
from importlib import import_module

import pytest

import code_review_loop.runner as runner_mod
from code_review_loop import application as application_mod
from code_review_loop import events
from code_review_loop import resume as resume_mod
from code_review_loop.adapters import git as git_adapter
from code_review_loop.adapters import phase_support

cli_main = import_module("code_review_loop.cli.main")


def test_summary_records_git_state_for_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_support, "lexical_git_repo_root", lambda _cwd: tmp_path)

    def fake_run_git_preflight(cwd, args):
        if list(args) == ["rev-parse", "HEAD"]:
            return runner_mod.CommandResult(["git", *args], 0, stdout="head-sha\n")
        if list(args) == ["rev-parse", "--verify", "main^{commit}"]:
            return runner_mod.CommandResult(["git", *args], 0, stdout="base-sha\n")
        if list(args) == ["merge-base", "HEAD", "main"]:
            return runner_mod.CommandResult(["git", *args], 0, stdout="merge-sha\n")
        return runner_mod.CommandResult(["git", *args], 1, stderr="unexpected")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return runner_mod.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)

    summary = runner_mod.run_loop(
        runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        ),
        runner,
    )

    assert summary["git_state"] == {
        "head": "head-sha",
        "base": "main",
        "base_commit": "base-sha",
        "merge_base": "merge-sha",
        "available": True,
    }


def test_resume_payload_preserves_full_auto_and_budget_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_support, "lexical_git_repo_root", lambda _cwd: tmp_path)

    def fake_run_git_preflight(cwd, args):
        if list(args) == ["rev-parse", "HEAD"]:
            return runner_mod.CommandResult(["git", *args], 0, stdout="head-sha\n")
        if list(args) == ["rev-parse", "--verify", "main^{commit}"]:
            return runner_mod.CommandResult(["git", *args], 0, stdout="base-sha\n")
        if list(args) == ["merge-base", "HEAD", "main"]:
            return runner_mod.CommandResult(["git", *args], 0, stdout="merge-sha\n")
        return runner_mod.CommandResult(["git", *args], 1, stderr="unexpected")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return runner_mod.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        full_auto=False,
        budget_config=runner_mod.budgets.BudgetConfig(
            max_wall_seconds=12.5,
            max_tokens=100,
            max_usd=Decimal("1.25"),
            soft_warn_fraction=0.5,
        ),
    )

    summary = runner_mod.run_loop(config, runner)
    resumed, _budget_state = resume_mod.resume_loop_config(summary, run_dir=tmp_path / "artifacts")

    assert summary["resume_config"]["full_auto"] is False
    assert summary["resume_config"]["max_wall_seconds"] == 12.5
    assert summary["resume_config"]["max_tokens"] == 100
    assert summary["resume_config"]["max_usd"] == "1.25"
    assert summary["resume_config"]["soft_warn_fraction"] == 0.5
    assert resumed.full_auto is False
    assert resumed.budget_config.max_wall_seconds == 12.5
    assert resumed.budget_config.max_tokens == 100
    assert str(resumed.budget_config.max_usd) == "1.25"
    assert resumed.budget_config.soft_warn_fraction == 0.5


def test_resume_loop_config_seeds_budget_state_from_summary_totals(tmp_path):
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

    _config, resumed_budget = resume_mod.resume_loop_config(summary, run_dir=tmp_path)

    assert resumed_budget is not None
    assert resumed_budget.tokens_used == 73
    assert resumed_budget.tokens_reported is True
    assert resumed_budget.usd_used == Decimal("0.45")
    assert resumed_budget.usd_reported is True


def test_resume_loop_config_uses_supplied_cwd(tmp_path):
    review_path = tmp_path / "review-1.txt"
    review_path.write_text("REVIEW_STATUS: findings\n", encoding="utf-8")
    cwd = tmp_path / "work"
    cwd.mkdir()
    summary = {
        "resume_config": {
            "base": "main",
            "max_iterations": 1,
            "codex_bin": "codex",
        },
        "artifact_paths": {"reviews": [str(review_path)]},
    }

    resumed, _budget_state = resume_mod.resume_loop_config(summary, run_dir=tmp_path, cwd=cwd)

    assert resumed.cwd == cwd


def test_resume_loop_config_defaults_legacy_missing_full_auto_to_true(tmp_path):
    review_path = tmp_path / "review-1.txt"
    review_path.write_text("REVIEW_STATUS: findings\n", encoding="utf-8")
    summary = {
        "resume_config": {
            "base": "main",
            "max_iterations": 1,
            "codex_bin": "codex",
        },
        "artifact_paths": {"reviews": [str(review_path)]},
    }

    resumed, _budget_state = resume_mod.resume_loop_config(summary, run_dir=tmp_path)

    assert resumed.full_auto is True


def test_resume_loop_config_rejects_float_max_usd(tmp_path):
    review_path = tmp_path / "review-1.txt"
    review_path.write_text("REVIEW_STATUS: findings\n", encoding="utf-8")
    summary = {
        "resume_config": {
            "base": "main",
            "max_iterations": 1,
            "codex_bin": "codex",
            "max_usd": 1.25,
        },
        "artifact_paths": {"reviews": [str(review_path)]},
    }

    with pytest.raises(ValueError, match="resume_config.max_usd must be a decimal string, not float"):
        resume_mod.resume_loop_config(summary, run_dir=tmp_path)


def test_summary_records_unavailable_git_state_outside_git(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_support, "lexical_git_repo_root", lambda _cwd: None)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return runner_mod.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    summary = runner_mod.run_loop(
        runner_mod.LoopConfig(
            base="main",
            max_iterations=1,
            codex_bin="codex",
            cwd=tmp_path,
            artifact_dir=tmp_path / "artifacts",
        ),
        runner,
    )

    assert summary["git_state"] == {
        "head": None,
        "base": "main",
        "base_commit": None,
        "merge_base": None,
        "available": False,
    }


def test_main_returns_exit_code_5_for_controlled_cancellation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    summary = {
        "run_id": "run-1",
        "final_status": "error",
        "stopped_reason": "cancelled",
        "iterations": [],
    }

    def fake_run_loop(_config):
        raise runner_mod.RunLoopFailed(
            summary,
            "cancelled by operator",
            outcome=runner_mod.OutcomeFailed(reason="cancelled", error="cancelled by operator"),
        )

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    exit_code = cli_main.main(["--no-run-history"])

    assert exit_code == 5
    assert "cancelled by operator" in capsys.readouterr().err


def test_loop_writes_failure_summary_when_initial_review_invocation_fails(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return runner_mod.CommandResult(list(args), 1, stderr="Error: failed to create session\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(runner_mod.RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    review_path = tmp_path / "artifacts" / "review-1.txt"

    assert "review-1" in str(excinfo.value)
    assert summary["final_status"] == "error"
    assert summary["stopped_reason"] == "review_failed"
    assert summary["error"].startswith("codex review failed for review-1; see ")
    assert summary["iterations"] == [{"iteration": 1, "review_failed": True}]
    assert summary["artifact_paths"]["summary"] == str(tmp_path / "artifacts" / "summary.json")
    assert summary["artifact_paths"]["reviews"] == [str(review_path)]
    assert review_path.is_file()
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    assert truncated is False
    assert any(
        event.kind == "failure" and event.payload.get("reason") == "review_failed"
        for event in records
    )


def test_loop_writes_failure_summary_when_final_review_invocation_fails(tmp_path):
    review_calls = 0

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        nonlocal review_calls
        if args[1] == "review":
            review_calls += 1
            if review_calls == 1:
                return runner_mod.CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
            return runner_mod.CommandResult(list(args), 1, stderr="Error: failed to create session\n")
        return runner_mod.CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(runner_mod.RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    review_path = tmp_path / "artifacts" / "review-final.txt"

    assert "review-final" in str(excinfo.value)
    assert summary["final_status"] == "error"
    assert summary["stopped_reason"] == "review_failed"
    assert summary["error"].startswith("codex review failed for review-final; see ")
    assert summary["iterations"] == [
        {"iteration": 1, "review_status": "findings", "check_failures": 0},
        {"iteration": "final", "review_failed": True},
    ]
    assert summary["artifact_paths"]["reviews"] == [
        str(tmp_path / "artifacts" / "review-1.txt"),
        str(review_path),
    ]
    assert review_path.is_file()


def test_append_run_history_preserves_budget_totals(tmp_path, monkeypatch):
    from decimal import Decimal

    home = tmp_path / "home"
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(home))

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(
                list(args), 0, stdout="No findings.\nREVIEW_STATUS: clear\n", tokens=500, usd=Decimal("0.03")
            )
        return runner_mod.CommandResult(list(args), 0, stdout="ok\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner)
    budgets_before = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))["budgets"]

    assert budgets_before["tokens"] == 500
    assert budgets_before["usd"] == "0.03"

    history_path = runner_mod.append_run_history(summary, config)
    budgets_after = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))["budgets"]

    assert history_path == home / ".local" / "share" / "revrem" / "runs.jsonl"
    assert budgets_after["tokens"] == budgets_before["tokens"]
    assert budgets_after["usd"] == budgets_before["usd"]


def test_budget_exceeded_propagates_through_triage(tmp_path, monkeypatch):
    exc = runner_mod.budgets.BudgetExceeded(ceiling="tokens", limit=100, actual=150)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return runner_mod.CommandResult(
            list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n"
        )

    # B2e: patch TriageAdapter.execute instead of the legacy run_triage shim
    import code_review_loop.adapters.triage as _triage_mod
    monkeypatch.setattr(_triage_mod.TriageAdapter, "execute", lambda *a, **kw: (_ for _ in ()).throw(exc))

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
    )

    with pytest.raises(runner_mod.RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner)

    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"


def test_budget_exceeded_propagates_through_remediation(tmp_path, monkeypatch):
    exc = runner_mod.budgets.BudgetExceeded(ceiling="tokens", limit=100, actual=150)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return runner_mod.CommandResult(
            list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n"
        )

    # B2d: patch RemediationAdapter.execute instead of the legacy run_remediation shim
    import code_review_loop.adapters.remediation as _rem_mod
    monkeypatch.setattr(_rem_mod.RemediationAdapter, "execute", lambda *a, **kw: (_ for _ in ()).throw(exc))

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(runner_mod.RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner)

    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"


def test_budget_exceeded_propagates_through_commit(tmp_path, monkeypatch):
    exc = runner_mod.budgets.BudgetExceeded(ceiling="tokens", limit=100, actual=150)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if "status" in args:
            return runner_mod.CommandResult(list(args), 0, stdout="")
        return runner_mod.CommandResult(
            list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n"
        )

    # B2c: patch CommitAdapter.execute instead of the legacy run_commit shim
    import code_review_loop.adapters.commit as _commit_mod
    monkeypatch.setattr(_commit_mod.CommitAdapter, "execute", lambda *a, **kw: (_ for _ in ()).throw(exc))

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
    )

    with pytest.raises(runner_mod.RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner)

    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"


def test_run_loop_preserves_existing_events_on_resume(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    first_events = artifact_dir / "events.jsonl"
    for i in range(1, 4):
        event = events.make_event(run_id="original-run", seq=i, kind="phase_start", phase="review")
        with first_events.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return runner_mod.CommandResult(list(args), 0, stdout="No findings.\nREVIEW_STATUS: clear\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=artifact_dir,
    )

    runner_mod.run_loop(config, runner)

    preserved = artifact_dir / "events-original-run.jsonl"
    assert preserved.is_file()
    original_lines = preserved.read_text(encoding="utf-8").strip().splitlines()
    assert len(original_lines) == 3

    new_events = artifact_dir / "events.jsonl"
    assert new_events.is_file()
    new_first = json.loads(new_events.read_text(encoding="utf-8").splitlines()[0])
    assert new_first["run_id"] != "original-run"

def test_loop_can_start_from_initial_review_file(tmp_path):
    calls = []
    initial_review = tmp_path / "previous-review-final.txt"
    initial_review.write_text(
        "Full review comments:\n\n- [P2] Carry this forward — src/state.py:1\n",
        encoding="utf-8",
    )
    review_outputs = iter(["No findings.\n"])

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        initial_review_file=initial_review,
    )

    summary = runner_mod.run_loop(config, runner)

    assert [call[0][1] for call in calls] == ["exec", "review"]
    assert calls[0][1] is not None and "Carry this forward" in calls[0][1]
    assert summary["iterations"][0]["review_source"] == str(initial_review)
    assert (tmp_path / "artifacts" / "review-initial.txt").exists()


def test_loop_writes_structured_triage_source_for_initial_review_file(tmp_path):
    calls = []
    initial_review = tmp_path / "previous-review-final.txt"
    initial_review.write_text(
        "Full review comments:\n\n- [P2] Carry this forward — src/state.py:1\n",
        encoding="utf-8",
    )
    triage_payload = {
        "confirmed_findings": [
            {
                "affected_paths": ["src/app.py"],
                "fingerprint": "f1:abc123",
                "rationale": "The review finding is actionable.",
                "severity": "medium",
                "summary": "Fix the bug.",
            }
        ],
        "implementation_order": ["f1:abc123"],
        "needs_more_info": [],
        "parsing_warnings": [],
        "rejected_findings": [],
        "verification_commands": ["pytest -q"],
    }

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="REVIEW_STATUS: findings\n")
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return runner_mod.CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        initial_review_file=initial_review,
        triage_enabled=True,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner)

    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))
    assert triage_json["source_review_artifact"] == "review-initial.txt"
    assert summary["artifact_paths"]["reviews"] == [str(tmp_path / "artifacts" / "review-initial.txt")]
    assert (tmp_path / "artifacts" / "review-initial.txt").exists()
    assert "Structured triage handoff" in (calls[1][1] or "")


def test_resolve_initial_review_file_latest(tmp_path):
    older = tmp_path / "20260428T000000Z"
    newer = tmp_path / "20260428T010000Z"
    older.mkdir()
    newer.mkdir()
    older_review = older / "review-final.txt"
    newer_review = newer / "review-final.txt"
    older_review.write_text("old", encoding="utf-8")
    newer_review.write_text("new", encoding="utf-8")

    assert runner_mod.resolve_initial_review_file("latest", tmp_path) == newer_review


def test_resolve_initial_review_file_latest_returns_none_when_newest_run_is_clean(tmp_path):
    clean_run = tmp_path / "20260428T020000Z"
    unresolved_run = tmp_path / "20260428T010000Z"
    clean_run.mkdir()
    unresolved_run.mkdir()
    clean_review = clean_run / "review-final.txt"
    unresolved_review = unresolved_run / "review-final.txt"
    clean_review.write_text("clean", encoding="utf-8")
    unresolved_review.write_text("findings", encoding="utf-8")
    (clean_run / "summary.json").write_text(
        json.dumps({"final_status": "clear", "stopped_reason": "review_clear"}),
        encoding="utf-8",
    )
    (unresolved_run / "summary.json").write_text(
        json.dumps({"final_status": "findings", "stopped_reason": "max_iterations_reached"}),
        encoding="utf-8",
    )
    os.utime(unresolved_review, (1, 1))
    os.utime(clean_review, (2, 2))

    assert runner_mod.resolve_initial_review_file("latest", tmp_path) is None


def test_resolve_initial_review_file_latest_returns_none_for_only_clean_runs(tmp_path):
    clean_run = tmp_path / "20260428T020000Z"
    clean_run.mkdir()
    (clean_run / "review-final.txt").write_text("clean", encoding="utf-8")
    (clean_run / "summary.json").write_text(
        json.dumps({"final_status": "clear", "stopped_reason": "review_clear"}),
        encoding="utf-8",
    )

    assert runner_mod.resolve_initial_review_file("latest", tmp_path) is None


def test_resolve_initial_review_file_latest_returns_none_without_previous_runs(tmp_path):
    assert runner_mod.resolve_initial_review_file("latest", tmp_path) is None


def test_resolve_initial_review_file_latest_skips_dry_run_review_stubs(tmp_path):
    dry_run = tmp_path / "20260428T020000Z"
    unresolved_run = tmp_path / "20260428T010000Z"
    dry_run.mkdir()
    unresolved_run.mkdir()
    dry_review = dry_run / "review-final.txt"
    unresolved_review = unresolved_run / "review-final.txt"
    dry_review.write_text("DRY_RUN\nREVIEW_STATUS: findings\n", encoding="utf-8")
    unresolved_review.write_text(
        "Full review comments:\n\n- [P2] Fix the real issue\n",
        encoding="utf-8",
    )
    (dry_run / "summary.json").write_text(
        json.dumps({"final_status": "findings", "stopped_reason": "max_iterations_reached"}),
        encoding="utf-8",
    )
    (unresolved_run / "summary.json").write_text(
        json.dumps({"final_status": "findings", "stopped_reason": "max_iterations_reached"}),
        encoding="utf-8",
    )
    os.utime(unresolved_review, (1, 1))
    os.utime(dry_review, (2, 2))

    assert runner_mod.resolve_initial_review_file("latest", tmp_path) == unresolved_review
