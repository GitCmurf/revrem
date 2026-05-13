from __future__ import annotations

import json
from pathlib import Path

from code_review_loop import cli as MODULE
from code_review_loop import events


def write_resume_run(
    run_dir: Path,
    *,
    stopped_reason: str = "cancelled",
    git_state: dict[str, object] | None = None,
    truncated: bool = False,
) -> None:
    run_dir.mkdir(parents=True)
    summary = {
        "run_id": "run-1",
        "base": "main",
        "final_status": "error",
        "stopped_reason": stopped_reason,
        "iterations": [],
        "git_state": git_state
        or {
            "head": "head-sha",
            "base": "main",
            "base_commit": "base-sha",
            "merge_base": "merge-sha",
            "available": True,
        },
    }
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
