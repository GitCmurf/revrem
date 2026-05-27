from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace

import code_review_loop.runner as runner_mod
from code_review_loop import application as application_mod
from code_review_loop.core.outcome import OutcomeClear

cli_main = import_module("code_review_loop.cli.main")
config_command = import_module("code_review_loop.cli.commands.config")
history_command = import_module("code_review_loop.cli.commands.history")
suppress_command = import_module("code_review_loop.cli.commands.suppress")


def _clear_result(summary: dict[str, object]) -> application_mod.ReviewLoopResult:
    return application_mod.ReviewLoopResult(summary=summary, outcome=OutcomeClear(reason="review_clear"))



def test_main_records_non_dry_run_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return _clear_result({
            "run_id": "run-1",
            "started_at": "2026-05-02T10:00:00Z",
            "base": config.base,
            "profile": config.profile_name,
            "artifact_dir": str(config.artifact_dir),
            "max_iterations": config.max_iterations,
            "iterations": [{"iteration": 1, "review_status": "clear"}],
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "pending_check_failures": False,
            "artifact_paths": {"summary": str(config.artifact_dir / "summary.json")},
        })

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)
    monkeypatch.setattr(runner_mod, "write_summary", lambda config, summary: None)

    assert cli_main.main(["--base", "main"]) == 0
    output = capsys.readouterr().out
    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"

    assert history_path.is_file()
    assert f"Run history: {history_path}" in output
    assert '"run_id": "run-1"' in history_path.read_text(encoding="utf-8")


def test_main_records_failed_runs_in_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    summary = {
        "run_id": "run-1",
        "started_at": "2026-05-02T10:00:00Z",
        "base": "main",
        "profile": "final-pr",
        "artifact_dir": str(tmp_path / "artifacts"),
        "max_iterations": 1,
        "iterations": [{"iteration": 1, "review_status": "findings", "triage_failed": True}],
        "final_status": "error",
        "stopped_reason": "triage_failed",
        "pending_check_failures": False,
        "error": "codex exec triage failed for iteration 1",
    }

    def fake_run_loop(config):
        raise runner_mod.RunLoopFailed(summary, "codex exec triage failed for iteration 1")

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    assert cli_main.main(["--base", "main", "--artifact-dir", str(tmp_path / "artifacts")]) == 1
    capsys.readouterr()

    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"

    assert history_path.is_file()
    history_text = history_path.read_text(encoding="utf-8")
    summary_text = (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    assert '"run_id": "run-1"' in history_text
    assert '"final_status": "error"' in history_text
    assert '"stopped_reason": "triage_failed"' in history_text
    assert '"history_path": "' in summary_text


def test_main_skips_history_for_dry_run_and_explicit_opt_out(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return _clear_result({
            "run_id": "run-1",
            "started_at": "2026-05-02T10:00:00Z",
            "base": config.base,
            "artifact_dir": str(config.artifact_dir),
            "max_iterations": config.max_iterations,
            "iterations": [],
            "final_status": "clear",
            "stopped_reason": "review_clear",
        })

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    assert cli_main.main(["--dry-run"]) == 0
    assert cli_main.main(["--no-run-history"]) == 0
    assert not (home / ".local" / "share" / "revrem" / "runs.jsonl").exists()


def test_main_skips_history_when_summary_has_no_run_id(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return _clear_result({
            "artifact_dir": str(config.artifact_dir),
            "iterations": [],
            "final_status": "clear",
            "stopped_reason": "review_clear",
        })

    monkeypatch.setattr(application_mod, "run_review_loop", fake_run_loop)

    assert cli_main.main([]) == 0
    assert not (home / ".local" / "share" / "revrem" / "runs.jsonl").exists()


def test_history_list_command_outputs_recent_runs(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        '{"run_id":"old","final_status":"findings","stopped_reason":"max_iterations_reached","base":"main","artifact_dir":"tmp/old"}\n'
        '{"run_id":"new","final_status":"clear","stopped_reason":"review_clear","base":"main","artifact_dir":"tmp/new"}\n',
        encoding="utf-8",
    )

    assert cli_main.main(["history", "list", "--limit", "1"]) == 0
    text = capsys.readouterr().out
    assert "new clear (review_clear) base=main artifacts=tmp/new" in text
    assert "old" not in text

    assert cli_main.main(["history", "--format", "json", "list", "--limit", "1"]) == 0
    json_text = capsys.readouterr().out
    assert '"run_id": "new"' in json_text
    assert '"run_id": "old"' not in json_text


def test_history_unknown_command_reports_command_error(monkeypatch, capsys):
    monkeypatch.setattr(history_command, "parse_history_args", lambda _argv: SimpleNamespace(command="wat"))

    assert history_command.main([]) == 1
    assert "unhandled history command: wat" in capsys.readouterr().err

