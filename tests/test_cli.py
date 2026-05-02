from __future__ import annotations

import io
import re

from code_review_loop import cli as MODULE


def test_detect_review_status_prefers_explicit_status_line():
    assert MODULE.detect_review_status("Looks good\nREVIEW_STATUS: clear\n") == "clear"
    assert MODULE.detect_review_status("One blocker\nREVIEW_STATUS: findings\n") == "findings"


def test_detect_review_status_treats_ambiguous_output_as_unknown():
    assert MODULE.detect_review_status("This review has a detailed discussion.") == "unknown"


def test_detect_review_status_accepts_exact_clear_review_lines():
    assert MODULE.detect_review_status("No findings.\n") == "clear"
    assert MODULE.detect_review_status("summary\nNo actionable findings\n") == "clear"
    assert (
        MODULE.detect_review_status("I did not find any discrete, actionable bugs in the diff.")
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I did not find any discrete introduced bug that would break existing behavior."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "The changes add the alias and tests without any clear regressions or actionable bugs."
        )
        == "clear"
    )


def test_detect_review_status_ignores_stderr_transcript_noise():
    output = (
        "I did not find any discrete, actionable bugs in the diff.\n\n"
        "[stderr]\n"
        "tool output mentions review comments and examples like - [P2] historical note\n"
    )

    assert MODULE.detect_review_status(output) == "clear"


def test_detect_review_status_recognizes_codex_review_findings():
    output = """The patch has a bug.

Full review comments:

- [P2] Count filtered summaries after filtering — src/example.py:10-12
  This reports misleading data.
"""
    assert MODULE.detect_review_status(output) == "findings"


def test_review_status_diagnostics_explain_clear_with_stderr_noise():
    output = (
        "I did not find any discrete, actionable bugs in the diff.\n\n"
        "[stderr]\n"
        "review comments:\n- [P2] stale transcript example\n"
    )

    diagnostics = MODULE.review_status_diagnostics(output)

    assert diagnostics == {
        "actionable_chars": 57,
        "clear_phrase_present": True,
        "explicit_status": None,
        "finding_line_count": 0,
        "status": "clear",
        "stderr_present": True,
    }


def test_extract_finding_summaries_limits_codex_findings():
    output = """Full review comments:

- [P1] First bug — src/a.py:1
  Detail.
- [P2] Second bug — src/b.py:2
- [P3] Third bug — src/c.py:3
"""
    assert MODULE.extract_finding_summaries(output, limit=2) == [
        "[P1] First bug — src/a.py:1",
        "[P2] Second bug — src/b.py:2",
    ]


def test_extract_finding_blocks_includes_short_detail():
    output = """Full review comments:

- [P1] First bug — src/a.py:1
  The first detail line.
  The second detail line.
  The third detail line.
- [P2] Second bug — src/b.py:2
  Another detail.
"""
    assert MODULE.extract_finding_blocks(output, limit=2, detail_lines=2) == [
        [
            "[P1] First bug — src/a.py:1",
            "The first detail line.",
            "The second detail line.",
        ],
        ["[P2] Second bug — src/b.py:2", "Another detail."],
    ]


def test_extract_review_summary_uses_leading_review_prose():
    output = """The loop can omit the only review transcript path in a failure summary.

Full review comments:

- [P2] Prefix iteration review artifact labels — scripts/loop.py:1
  Detail.
"""

    assert (
        MODULE.extract_review_summary(output)
        == "The loop can omit the only review transcript path in a failure summary."
    )


def test_review_model_is_top_level_codex_option(tmp_path):
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        model="gpt-test",
    )

    command = MODULE.build_review_command(config)

    assert command[:5] == ["codex", "--model", "gpt-test", "review", "--base"]
    assert command == ["codex", "--model", "gpt-test", "review", "--base", "main"]


def test_model_overrides_and_reasoning_effort_are_passed_to_codex(tmp_path):
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        model="gpt-5.4-mini",
        review_model="gpt-5.5",
        remediation_model="gpt-5.4-mini",
        reasoning_effort="low",
    )

    review_command = MODULE.build_review_command(config)
    remediation_command = MODULE.build_remediation_command(config)

    assert review_command[:5] == [
        "codex",
        "-c",
        'model_reasoning_effort="low"',
        "--model",
        "gpt-5.5",
    ]
    assert remediation_command[:5] == [
        "codex",
        "exec",
        "-c",
        'model_reasoning_effort="low"',
        "--full-auto",
    ]
    assert remediation_command[remediation_command.index("--model") + 1] == "gpt-5.4-mini"


def test_remediation_command_uses_deterministic_output_options(tmp_path):
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        exec_json=True,
    )

    command = MODULE.build_remediation_command(config, tmp_path / "last-message.txt")

    assert "--color" in command
    assert command[command.index("--color") + 1] == "never"
    assert "--json" in command
    assert "--output-last-message" in command
    assert command[-1] == "-"


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
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
    )

    summary = MODULE.run_loop(config, runner)

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
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert [call[0][1] for call in calls] == ["review", "exec", "review"]


def test_debug_status_detection_writes_diagnostic_artifact(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        debug_status_detection=True,
    )

    summary = MODULE.run_loop(config, runner)

    diagnostic_path = tmp_path / "artifacts" / "review-1-status.json"
    assert diagnostic_path.exists()
    assert summary["artifact_paths"]["diagnostics"] == [str(diagnostic_path)]
    assert summary["artifact_paths"]["reviews"] == [str(tmp_path / "artifacts" / "review-1.txt")]


def test_loop_passes_configured_timeout_to_all_subprocess_phases(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Finding: add regression coverage.\nREVIEW_STATUS: findings\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="ok\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
        timeout_seconds=900,
    )

    MODULE.run_loop(config, runner)

    assert [call[2] for call in calls] == [900, 900, 900, 900]


def test_resolve_timeout_seconds_allows_disabling_timeout():
    assert MODULE.resolve_timeout_seconds(0) is None
    assert MODULE.resolve_timeout_seconds(900) == 900


def test_main_rejects_negative_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = MODULE.main(["--timeout-seconds", "-1"])

    assert exit_code == 1
    assert "--timeout-seconds must be 0 or greater" in capsys.readouterr().err


def test_main_handles_keyboard_interrupt_without_traceback(tmp_path, monkeypatch, capsys):
    def interrupted_run_loop(config):
        raise KeyboardInterrupt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(MODULE, "run_loop", interrupted_run_loop)

    exit_code = MODULE.main([])

    assert exit_code == 130
    assert capsys.readouterr().err == "Interrupted by user.\n"


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
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        initial_review_file=initial_review,
    )

    summary = MODULE.run_loop(config, runner)

    assert [call[0][1] for call in calls] == ["exec", "review"]
    assert calls[0][1] is not None and "Carry this forward" in calls[0][1]
    assert summary["iterations"][0]["review_source"] == str(initial_review)
    assert (tmp_path / "artifacts" / "review-initial.txt").exists()


def test_resolve_initial_review_file_latest(tmp_path):
    older = tmp_path / "20260428T000000Z"
    newer = tmp_path / "20260428T010000Z"
    older.mkdir()
    newer.mkdir()
    older_review = older / "review-final.txt"
    newer_review = newer / "review-final.txt"
    older_review.write_text("old", encoding="utf-8")
    newer_review.write_text("new", encoding="utf-8")

    assert MODULE.resolve_initial_review_file("latest", tmp_path) == newer_review


def test_main_resolves_latest_initial_review_from_custom_artifact_dir(tmp_path, monkeypatch):
    custom_root = tmp_path / "custom-artifacts"
    custom_run = custom_root / "20260428T010000Z"
    default_run = tmp_path / "tmp" / "code-review-loop" / "20260428T020000Z"
    custom_run.mkdir(parents=True)
    default_run.mkdir(parents=True)
    custom_review = custom_run / "review-final.txt"
    default_review = default_run / "review-final.txt"
    custom_review.write_text("custom", encoding="utf-8")
    default_review.write_text("default", encoding="utf-8")
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    exit_code = MODULE.main(
        [
            "--initial-review-file",
            "latest",
            "--artifact-dir",
            str(custom_root),
            "--quiet-progress",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].artifact_dir == custom_root
    assert captured_configs[0].initial_review_file == custom_review
    assert captured_configs[0].initial_review_file != default_review


def test_main_uses_profile_defaults_and_cli_overrides(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.pipeline]
base = "trunk"
max_iterations = 3
checks = ["pytest -q", "git diff --check"]

[profiles.final-pr.review]
model = "gpt-5.5"
reasoning_effort = "medium"
timeout_seconds = 1800

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"

[profiles.final-pr.output]
summary_format = "json"
debug_status_detection = true
quiet_progress = true
""",
        encoding="utf-8",
    )
    captured_configs = []

    def fake_run_loop(config):
        captured_configs.append(config)
        return {
            "artifact_dir": str(config.artifact_dir),
            "final_status": "clear",
            "stopped_reason": "review_clear",
            "iterations": [],
        }

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    exit_code = MODULE.main(["--profile", "final-pr", "--base", "main", "--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.base == "main"
    assert config.max_iterations == 3
    assert config.review_model == "gpt-5.5"
    assert config.remediation_model == "gpt-5.4-mini"
    assert config.reasoning_effort == "medium"
    assert config.timeout_seconds == 1800
    assert config.check_commands == ("pytest -q", "git diff --check")
    assert config.debug_status_detection is True
    assert config.progress is False


def test_config_commands_create_show_list_and_delete_profile(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    assert MODULE.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0
    assert MODULE.main(["config", "list"]) == 0
    assert "smoke - Smoke profile" in capsys.readouterr().out
    assert MODULE.main(["config", "list", "--format", "json"]) == 0
    assert '"name": "smoke"' in capsys.readouterr().out

    assert MODULE.main(["config", "show", "smoke", "--format", "json"]) == 0
    assert '"name": "smoke"' in capsys.readouterr().out

    assert MODULE.main(["config", "doctor", "--profile", "smoke", "--format", "json"]) == 0
    assert '"resolved_profile"' in capsys.readouterr().out

    assert MODULE.main(["config", "delete", "smoke", "--yes"]) == 0
    assert MODULE.main(["config", "show", "smoke"]) == 1


def test_loop_caps_remediation_passes_and_runs_final_review(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
        return MODULE.CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "findings"
    assert summary["stopped_reason"] == "max_iterations_reached"
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
                return MODULE.CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
            return MODULE.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")
        return MODULE.CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = MODULE.run_loop(config, runner)

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
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            rc, out = next(check_outputs)
            return MODULE.CommandResult(list(args), rc, stdout=out)
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest tests/",),
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "clear"

    # Both remediation passes ran (loop was not aborted by the check failure)
    exec_calls = [c for c in calls if c[0][0] == "codex" and c[0][1] == "exec"]
    assert len(exec_calls) == 2, f"expected 2 exec calls, got {len(exec_calls)}"

    # The second remediation prompt must include the check-failure output from iter-1
    second_prompt = exec_calls[1][1]
    assert second_prompt is not None and "1 FAILED" in second_prompt


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
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            rc, out = next(check_outputs)
            return MODULE.CommandResult(list(args), rc, stdout=out)
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest tests/",),
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "findings"
    assert summary["pending_check_failures"] is True
    assert summary["stopped_reason"] == "max_iterations_reached_with_check_failures"

    exec_calls = [c for c in calls if c[0][0] == "codex" and c[0][1] == "exec"]
    assert len(exec_calls) == 2
    assert exec_calls[1][1] is not None and "1 FAILED" in exec_calls[1][1]


def test_skip_final_review_reports_unknown_status(tmp_path):
    """With --skip-final-review the loop must not report a stale pre-remediation status."""
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="Issues found.\nREVIEW_STATUS: findings\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "unknown", (
        "status after last remediation is unknowable without a follow-up review"
    )
    assert summary["stopped_reason"] == "max_iterations_reached"


def test_final_check_failure_prevents_clear_status(tmp_path):
    config = MODULE.LoopConfig(
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
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            return MODULE.CommandResult(list(args), 1, stdout="1 FAILED\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    summary = MODULE.run_loop(config, sequenced_runner)

    assert summary["final_status"] == "findings"
    assert summary["pending_check_failures"] is True
    assert summary["stopped_reason"] == "max_iterations_reached_with_check_failures"


def test_detect_review_status_requires_explicit_status_line():
    """Fuzzy patterns must not flip ambiguous output to clear."""
    assert MODULE.detect_review_status("no findings about style, but several about logic") == "unknown"
    assert MODULE.detect_review_status("review is clear of syntax errors but not semantic") == "unknown"
    assert MODULE.detect_review_status("") == "unknown"


def test_review_failure_detection_allows_nonzero_findings_without_stderr():
    assert (
        MODULE.review_failed_to_run(
            MODULE.CommandResult(["codex", "review"], -9, stdout="", stderr="")
        )
        is True
    )
    assert (
        MODULE.review_failed_to_run(
            MODULE.CommandResult(["codex", "review"], 1, stdout="Finding\n", stderr="")
        )
        is False
    )
    assert (
        MODULE.review_failed_to_run(
            MODULE.CommandResult(["codex", "review"], 1, stdout="", stderr="Error: thread/start failed")
        )
        is True
    )
    assert (
        MODULE.review_failed_to_run(
            MODULE.CommandResult(["codex", "review"], 2, stdout="", stderr="error: bad args")
        )
        is True
    )


def test_actionable_review_output_drops_verbose_stderr_transcript():
    output = "Full review comments:\n\n- [P1] Fix the bug\n\n[stderr]\n" + ("diff --git a/x b/x\n" * 100)

    assert MODULE.actionable_review_output(output) == "Full review comments:\n\n- [P1] Fix the bug"


def test_trim_for_prompt_caps_large_review_text():
    text = "a" * 100 + "MIDDLE" + "z" * 100

    trimmed = MODULE.trim_for_prompt(text, 80)

    assert len(trimmed) <= 80
    assert "omitted" in trimmed
    assert trimmed.startswith("a")
    assert trimmed.endswith("z")


def test_remediation_prompt_uses_actionable_output_and_cap(tmp_path):
    calls = []
    huge_stderr = "tool transcript\n" * 20_000
    review_outputs = iter(
        [
            f"Full review comments:\n\n- [P1] Fix state init\n\n[stderr]\n{huge_stderr}",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        max_remediation_input_chars=200,
    )

    MODULE.run_loop(config, runner)

    exec_prompts = [prompt for args, prompt in calls if args[1] == "exec"]
    assert len(exec_prompts) == 1
    assert exec_prompts[0] is not None
    assert "[P1] Fix state init" in exec_prompts[0]
    assert "tool transcript" not in exec_prompts[0]


def test_summary_includes_latest_review_excerpt_and_artifact_paths(tmp_path):
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P1] Fix init\n",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["latest_review_excerpt"] == "No findings."
    assert "artifact_paths" in summary
    assert summary["artifact_paths"]["summary"].endswith("summary.json")


def test_terminal_summary_surfaces_latest_findings_and_paths():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "iterations": [
            {"iteration": 1, "review_status": "findings", "check_failures": 0},
            {"iteration": 2, "review_status": "findings", "check_failures": 1},
        ],
        "artifact_paths": {
            "reviews": ["tmp/run/review-1.txt", "tmp/run/review-final.txt"],
            "last_messages": ["tmp/run/remediation-2-last-message.txt"],
            "checks": ["tmp/run/check-2-1.txt", "tmp/run/check-2-2.txt"],
            "summary": "tmp/run/summary.json",
        },
        "latest_review_excerpt": "Full review comments:\n\n- [P2] Fix summary counts",
    }

    text = MODULE.format_terminal_summary(summary)

    assert "Review-remediation loop: findings (max_iterations_reached)" in text
    assert "Latest review: tmp/run/review-final.txt" in text
    assert "Continue from latest review: --initial-review-file tmp/run/review-final.txt" in text
    assert "Latest remediation summary: tmp/run/remediation-2-last-message.txt" in text
    assert "- [P2] Fix summary counts" in text


def test_progress_logs_review_and_finding_summaries(tmp_path, capsys):
    review_outputs = iter(
        [
            "The query surfaces disagree.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix queue parity — src/state.py:1\n",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    MODULE.run_loop(config, runner)
    captured = capsys.readouterr()

    assert re.search(r"\d{2}:\d{2}:\d{2}\|rev\|1\s{3}\|start: codex review --base main", captured.err)
    assert re.search(r"\d{2}:\d{2}:\d{2}\|rev\|1\s{3}\|issue: The query surfaces disagree\.", captured.err)
    assert "findings-summary" not in captured.err
    assert "|rev|1   |[P2]   Fix queue parity" in captured.err
    assert "|rem|1   |done" in captured.err


def test_compact_progress_wraps_to_terminal_width(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(MODULE, "terminal_columns", lambda default=120: 70)
    review_outputs = iter(
        [
            "This review summary is long enough to wrap onto another aligned line.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix queue parity — src/state.py:1\n"
            "  This detail is also long enough to wrap under the same text column.\n",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    MODULE.run_loop(config, runner)
    captured = capsys.readouterr()

    assert re.search(r"\n\s{25}onto another aligned line\.", captured.err)
    assert re.search(r"\n\s{25}the same text column\.", captured.err)


def test_progress_logs_finding_detail_lines(tmp_path, capsys):
    review_outputs = iter(
        [
            "Full review comments:\n\n"
            "- [P2] Fix queue parity — src/state.py:1\n"
            "  This is the important detail.\n",
            "No findings.\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    MODULE.run_loop(config, runner)
    captured = capsys.readouterr()

    assert "This is the important detail." in captured.err
    assert re.search(r"\n\s{25}This is the important detail\.", captured.err)


def test_quiet_progress_suppresses_progress_logs(tmp_path, capsys):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
    )

    MODULE.run_loop(config, runner)
    captured = capsys.readouterr()

    assert captured.err == ""


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


def test_terminal_title_tracks_review_and_remediation_phases(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(MODULE.sys, "stderr", stderr)
    review_outputs = iter(
        [
            "Needs work.\nREVIEW_STATUS: findings\n",
            "No findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    summary = MODULE.run_loop(config, runner)
    output = stderr.getvalue()

    assert summary["final_status"] == "clear"
    assert output.startswith(MODULE.TERMINAL_TITLE_SAVE)
    assert "\033]0;rev 1/2 RevRem\007\033]2;rev 1/2 RevRem\007" in output
    assert "\033]0;rem 1/2 RevRem\007\033]2;rem 1/2 RevRem\007" in output
    assert "\033]0;rev 2/2 RevRem\007\033]2;rev 2/2 RevRem\007" in output
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE)


def test_terminal_title_restores_after_remediation_failure(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(MODULE.sys, "stderr", stderr)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="Needs work.\nREVIEW_STATUS: findings\n")
        return MODULE.CommandResult(list(args), 1, stderr="failed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    try:
        MODULE.run_loop(config, runner)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected remediation failure")

    output = stderr.getvalue()
    assert "\033]0;rev 1/1 RevRem\007\033]2;rev 1/1 RevRem\007" in output
    assert "\033]0;rem 1/1 RevRem\007\033]2;rem 1/1 RevRem\007" in output
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE)


def test_terminal_title_never_writes_to_stdout(tmp_path, monkeypatch):
    stderr = io.StringIO()
    stdout = TtyBuffer()
    monkeypatch.setattr(MODULE.sys, "stderr", stderr)
    monkeypatch.setattr(MODULE.sys, "stdout", stdout)
    monkeypatch.setattr(MODULE.Path, "exists", lambda self: False)

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    MODULE.set_terminal_title(config, "rev 1/1 RevRem")

    assert stderr.getvalue() == ""
    assert stdout.getvalue() == ""


def test_default_runner_refreshes_active_terminal_title_during_child_process(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(MODULE.sys, "stderr", stderr)
    monkeypatch.setattr(MODULE, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    with MODULE.terminal_title_context(config):
        MODULE.set_terminal_title(config, "rev 1/1 RevRem")
        result = MODULE.default_runner(
            [
                MODULE.sys.executable,
                "-c",
                "import time; time.sleep(0.05); print('done')",
            ],
            tmp_path,
            None,
            2,
        )

    output = stderr.getvalue()
    title_sequence = "\033]0;rev 1/1 RevRem\007\033]2;rev 1/1 RevRem\007"
    assert result.returncode == 0
    assert result.stdout == "done\n"
    assert output.count(title_sequence) >= 2
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE)


def test_loop_writes_failure_summary_when_remediation_fails(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="Full review comments:\n\n- [P1] Fix\n")
        return MODULE.CommandResult(list(args), 1, stderr="Error: turn/start failed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    try:
        MODULE.run_loop(config, runner)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected remediation failure")

    summary = (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    assert '"final_status": "error"' in summary
    assert '"stopped_reason": "remediation_failed"' in summary
    assert '"artifact_paths"' in summary
    assert "review-1.txt" in summary
    assert '"1.txt"' not in summary
