from __future__ import annotations

from importlib import import_module

import pytest

import code_review_loop.runner as runner_mod

cli_main = import_module("code_review_loop.cli.main")


def test_main_reports_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(["--version"])

    captured = capsys.readouterr()

    assert excinfo.value.code == 0
    assert captured.out.strip() == f"revrem {runner_mod.__version__}"
    assert captured.err == ""


def test_loop_stops_after_review_reports_clear(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Finding: add regression coverage.\nREVIEW_STATUS: findings\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
    )

    summary = runner_mod.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "review_clear"
    assert [call[0][1] for call in calls] == ["review", "exec", "-m", "review"]
    assert calls[0][1] is None
    assert (tmp_path / "artifacts" / "summary.json").exists()


def test_loop_stops_when_clear_review_has_noisy_stderr(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Finding: add regression coverage.\nREVIEW_STATUS: findings\n",
            (
                "I did not find any discrete, actionable bugs in the diff.\n\n"
                "[stderr]\n"
                "transcript mentions review comments and a historical - [P2] example\n"
            ),
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert [call[0][1] for call in calls] == ["review", "exec", "review"]
