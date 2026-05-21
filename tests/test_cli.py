from __future__ import annotations

import io
import json
import os
import re
import time
from decimal import Decimal
from pathlib import Path

import pytest

from code_review_loop import cli as MODULE
from code_review_loop import events, profiles, suppressions


def make_git_worktree(tmp_path: Path, cwd_rel: str | None = "work") -> tuple[Path, Path]:
    (tmp_path / ".git").mkdir(exist_ok=True)
    cwd = tmp_path if cwd_rel is None else tmp_path / cwd_rel
    cwd.mkdir(parents=True, exist_ok=True)
    return tmp_path, cwd


def test_main_reports_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        MODULE.main(["--version"])

    captured = capsys.readouterr()

    assert excinfo.value.code == 0
    assert captured.out.strip() == f"revrem {MODULE.__version__}"
    assert captured.err == ""


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
            "I did not find any discrete, actionable correctness issues in the changes."
        )
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
            "I did not find a discrete introduced bug that should block the patch."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I did not identify any discrete introduced bugs that would block the patch. "
            "The changed code compiles and the repository's dev-check suite passes."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I did not identify any discrete introduced bugs that should block the patch. "
            "The repository's dev-check suite passes locally."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "The diff was reviewed against the merge base and the changed implementation "
            "has corresponding tests and documentation. I did not identify a discrete "
            "introduced correctness, security, or maintainability issue that should block "
            "the patch."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "The changed code and accompanying tests pass the repository's dev-check suite, "
            "and I did not identify any discrete introduced correctness, security, or "
            "maintainability issue that should block the patch."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "The diff was reviewed and the repository verification suite passes. "
            "I did not identify any discrete introduced correctness, security, or "
            "maintainability issues that should block the patch."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "The changes pass locally without revealing any discrete correctness issue."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I did not identify any actionable correctness, security, or maintainability issues introduced by the diff."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I did not identify any introduced correctness, security, or maintainability issues that warrant an inline finding."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I reviewed the diff against the specified merge base and did not identify "
            "any discrete introduced correctness, security, or maintainability issues "
            "that warrant inline findings. The test suite also passes locally."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I did not identify any blocking defects in this patch. The tests pass."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            "I did not find any new regressions in the changed paths."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status("This would warrant an inline finding.") == "unknown"
    )
    assert (
        MODULE.detect_review_status(
            "The changes add the alias and tests without any clear regressions or actionable bugs."
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            '{\n'
            '  "findings": [],\n'
            '  "explanation": "I did not identify any discrete introduced bugs that should '
            'block the patch."\n'
            '}\n'
        )
        == "clear"
    )
    assert (
        MODULE.detect_review_status(
            '{"findings": [], "overall_correctness": "patch is correct"}\n'
        )
        == "clear"
    )


def test_detect_review_status_does_not_generalize_negated_clear_with_findings():
    assert (
        MODULE.detect_review_status(
            "I did not identify any broad design problem.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix the actual bug — src/example.py:10\n"
        )
        == "findings"
    )
    assert (
        MODULE.detect_review_status(
            "The patch has a concrete issue. I did not identify any alternative approach.\n"
            "Please fix the failure described above."
        )
        == "unknown"
    )
    assert (
        MODULE.detect_review_status(
            "I did not identify any broad design problem.\n\n"
            "- [P3] Tighten docs — docs/example.md:1\n"
        )
        == "findings"
    )


def test_run_loop_treats_structured_empty_findings_review_as_clear(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout='{"findings": [], "overall_correctness": "patch is correct"}\n',
            )
        raise AssertionError(f"unexpected command: {args}")

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
    assert [call[0][1] for call in calls] == ["review"]
    assert not (tmp_path / "artifacts" / "remediation-1.txt").exists()


def test_run_loop_writes_replayable_events_jsonl(tmp_path, capsys):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout='{"findings": [], "overall_correctness": "patch is correct"}\n',
            )
        raise AssertionError(f"unexpected command: {args}")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)
    replay_code = MODULE.main(["replay", str(tmp_path / "artifacts")])
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert summary["final_status"] == "clear"
    assert replay_code == 0
    assert truncated is False
    assert [event.kind for event in records] == [
        "phase_start",
        "phase_result",
        "artifact_write",
        "artifact_write",
        "summary",
    ]
    assert [event.payload.get("kind") for event in records if event.kind == "artifact_write"] == [
        "summary",
        "reviews",
    ]
    assert capsys.readouterr().out == (
        "0001|review|1|phase_start: codex review --base main\n"
        "0002|review|1|phase_result: clear\n"
        f"0003|artifacts|artifact_write: {tmp_path / 'artifacts' / 'summary.json'}\n"
        f"0004|artifacts|artifact_write: {tmp_path / 'artifacts' / 'review-1.txt'}\n"
        "0005|summary|summary: review_clear\n"
    )


def test_progress_warning_status_emits_warning_event(tmp_path):
    sink = events.InMemorySink("run-1")
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        event_sink=sink,
    )

    MODULE.progress_event(config, "triage", "1", "warning", "suppressions unavailable")

    assert sink.events[0].kind == "warning"
    assert sink.events[0].payload["message"] == "suppressions unavailable"


def test_detect_review_status_does_not_treat_scoped_clear_prose_as_clear_when_issue_follows():
    assert (
        MODULE.detect_review_status(
            "I did not find any issue in the docs, but there is a bug in the CLI."
        )
        == "unknown"
    )
    assert (
        MODULE.detect_review_status(
            "I did not find any issue in the docs; however, there is a bug in the CLI."
        )
        == "unknown"
    )
    assert (
        MODULE.detect_review_status(
            "I did not find any discrete issue in the docs.\n\n"
            "However, there is a bug in the parser."
        )
        == "unknown"
    )
    assert (
        MODULE.detect_review_status(
            "I did not find any actionable bugs.\n\n"
            "No validation prevents this regression."
        )
        == "unknown"
    )
    assert (
        MODULE.detect_review_status(
            "I did not identify any introduced correctness, security, or maintainability "
            "issues that warrant an inline finding\n"
            "There is a regression in the parser."
        )
        == "unknown"
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
        "The changes add the alias and tests without any clear regressions or actionable bugs.\n\n"
        "[stderr]\n"
        "review comments:\n- [P2] stale transcript example\n"
    )

    diagnostics = MODULE.review_status_diagnostics(output)

    assert diagnostics["status"] == "clear"
    assert diagnostics["clear_phrase_present"] is True
    assert diagnostics["stderr_present"] is True
    assert diagnostics["explicit_status"] is None
    assert diagnostics["finding_line_count"] == 0
    assert diagnostics["actionable_chars"] > 0


def test_config_show_accepts_reserved_harnesses(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.future.review]
harness = "claude"

[profiles.future.triage]
enabled = true
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(home))

    exit_code = MODULE.config_main(["show", "future"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert 'harness = "claude"' in captured.out
    assert "enabled = true" in captured.out
    assert captured.err == ""


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


def test_non_codex_review_receives_explicit_review_prompt(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return MODULE.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="claude",
        review_model="sonnet",
    )

    MODULE.run_loop(config, runner)

    assert calls[0][0] == [
        "claude",
        "--print",
        "--permission-mode",
        "auto",
        "--model",
        "sonnet",
    ]
    assert calls[0][1] is not None
    assert "Review the current repository changes" in calls[0][1]
    assert "REVIEW_STATUS: findings" in calls[0][1]


def test_opencode_review_prompt_is_passed_as_message_argument(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return MODULE.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )

    MODULE.run_loop(config, runner)

    assert calls[0][0][:5] == [
        "opencode",
        "run",
        "--dangerously-skip-permissions",
        "--model",
        "provider/model",
    ]
    assert "Review the current repository changes" in calls[0][0][-1]
    assert calls[0][1] is None


def test_harness_bin_override_controls_non_codex_executable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".revrem.toml").write_text(
        """
[profiles.multi.review]
harness = "claude"
model = "sonnet"
""",
        encoding="utf-8",
    )
    captured: list[MODULE.LoopConfig] = []

    def fake_run_loop(config):
        captured.append(config)
        return {"final_status": "clear", "stopped_reason": "review_clear"}

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    exit_code = MODULE.main(
        [
            "--profile",
            "multi",
            "--harness-bin",
            "claude=/tmp/claude-dev",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured[0].harness_executables == {"claude": "/tmp/claude-dev"}
    assert MODULE.build_review_command(captured[0])[0] == "/tmp/claude-dev"


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
        review_reasoning_effort="medium",
        remediation_reasoning_effort="low",
    )

    review_command = MODULE.build_review_command(config)
    remediation_command = MODULE.build_remediation_command(config)

    assert review_command[:5] == [
        "codex",
        "-c",
        'model_reasoning_effort="medium"',
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


def test_triage_command_uses_read_only_exec_with_phase_model(tmp_path):
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_model="gpt-5.4-mini",
        triage_reasoning_effort="low",
    )

    command = MODULE.build_triage_command(config)

    assert command[:4] == ["codex", "exec", "-c", 'model_reasoning_effort="low"']
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-5.4-mini"
    assert "--full-auto" not in command
    assert command[-1] == "-"


def test_commit_message_command_uses_read_only_exec_with_configured_model(tmp_path):
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-5.3-codex-spark",
        commit_reasoning_effort="minimal",
    )

    command = MODULE.build_commit_message_command(config)

    assert command == [
        "codex",
        "exec",
        "-c",
        'model_reasoning_effort="minimal"',
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--model",
        "gpt-5.3-codex-spark",
        "-",
    ]


def test_sanitize_commit_message_uses_first_plain_subject():
    assert (
        MODULE.sanitize_commit_message(
            'Commit message: "Harden RevRem commit flow"\n\nExplanation...',
            fallback="fallback",
        )
        == "chore: Harden RevRem commit flow (RevRem)"
    )
    assert (
        MODULE.sanitize_commit_message("fix(cli): stop on no-op remediation", fallback="fallback")
        == "fix(cli): stop on no-op remediation (RevRem)"
    )
    assert MODULE.sanitize_commit_message("", fallback="fallback") == "chore: fallback (RevRem)"
    assert (
        MODULE.sanitize_commit_message(
            "Use custom format",
            fallback="fallback",
            enforce_revrem_conventional=False,
        )
        == "Use custom format"
    )


def test_commit_message_for_staged_changes_respects_profile_prompt_override(tmp_path):
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-test-commit",
        commit_message_prompt="Write a custom subject.",
        commit_message_prompt_overridden=True,
        timeout_seconds=30,
    )
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return MODULE.CommandResult(list(args), 0, stdout=" file.py | 2 +-\n")
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return MODULE.CommandResult(list(args), 0, stdout="file.py\n")
        if args[:2] == ["codex", "exec"]:
            return MODULE.CommandResult(list(args), 0, stdout="Use custom format\n")
        raise AssertionError(f"unexpected command: {args!r}")

    message = MODULE.commit_message_for_staged_changes(config, runner, 1)

    assert message == "Use custom format"
    assert "Write a custom subject." in next(
        prompt for args, prompt in calls if args[:2] == ["codex", "exec"]
    )


def test_normalize_revrem_conventional_subject_preserves_suffix_when_truncated():
    subject = "fix(cli): " + "x" * 200

    normalized = MODULE.normalize_revrem_conventional_subject(subject)

    assert normalized.endswith(" (RevRem)")
    assert len(normalized) == 120
    assert normalized.startswith("fix(cli): ")


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


def test_loop_runs_optional_triage_between_review_and_remediation(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(list(args), 0, stdout="Confirmed: fix profile merge first.\n")
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        triage_model="gpt-5.4-mini",
        triage_reasoning_effort="low",
        triage_timeout_seconds=60,
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert [call[0][1] for call in calls] == ["review", "exec", "exec", "review"]
    assert calls[1][2] == 60
    assert "Do not edit files" in (calls[1][1] or "")
    assert "Confirmed: fix profile merge first." in (calls[2][1] or "")
    assert "Original review/check context" in (calls[2][1] or "")
    assert (tmp_path / "artifacts" / "triage-1.txt").exists()
    assert summary["artifact_paths"]["triage"] == [str(tmp_path / "artifacts" / "triage-1.txt")]


def test_loop_writes_structured_triage_artifact_and_handoff(tmp_path):
    calls = []
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
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)

    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))
    assert triage_json["run_id"] == summary["run_id"]
    assert triage_json["source_review_artifact"] == "review-1.txt"
    assert triage_json["prompt_version"] == "triage-v1"
    assert "Structured triage handoff" in (calls[2][1] or "")
    assert "Original review/check context" in (calls[2][1] or "")
    assert str(tmp_path / "artifacts" / "triage-1.json") in summary["artifact_paths"]["triage"]


def test_loop_skips_remediation_when_structured_triage_finding_is_suppressed(tmp_path):
    calls = []
    (tmp_path / ".git").mkdir()
    suppression = suppressions.make_entry(
        fingerprint="f1:abc123",
        summary="Accepted finding",
        rationale="Tracked in issue 123.",
        severity="medium",
        scope="repo",
        expires_at=None,
        critical_override=False,
        created_at="2026-05-12T00:00:00Z",
    )
    suppressions.write_entries(suppressions.repo_suppressions_path(tmp_path), [suppression])
    triage_payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1:abc123",
                "summary": "Fix profile merge",
                "severity": "medium",
                "affected_paths": ["src/code_review_loop/profiles.py"],
                "rationale": "Merge drops fields.",
            }
        ],
        "implementation_order": ["f1:abc123"],
        "needs_more_info": [],
        "parsing_warnings": [],
        "rejected_findings": [],
        "verification_commands": ["pytest -q"],
    }

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        raise AssertionError(f"remediation/check should not run after suppression: {args!r}")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)

    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))
    assert triage_json["confirmed_findings"] == []
    assert triage_json["suppressed_findings"][0]["fingerprint"] == "f1:abc123"
    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "all_findings_suppressed"
    assert summary["suppressed_findings_count"] == 1
    assert summary["iterations"][0]["suppressed_findings"] is True
    assert summary["iterations"][0]["suppressed_findings_count"] == 1
    assert len(calls) == 2


def test_loop_does_not_clear_when_structured_triage_still_needs_more_info(tmp_path):
    calls = []
    (tmp_path / ".git").mkdir()
    suppression = suppressions.make_entry(
        fingerprint="f1:abc123",
        summary="Accepted finding",
        rationale="Tracked in issue 123.",
        severity="medium",
        scope="repo",
        expires_at=None,
        critical_override=False,
        created_at="2026-05-12T00:00:00Z",
    )
    suppressions.write_entries(suppressions.repo_suppressions_path(tmp_path), [suppression])
    triage_payload = {
        "confirmed_findings": [
            {
                "fingerprint": "f1:abc123",
                "summary": "Fix profile merge",
                "severity": "medium",
                "affected_paths": ["src/code_review_loop/profiles.py"],
                "rationale": "Merge drops fields.",
            }
        ],
        "implementation_order": ["f1:abc123"],
        "needs_more_info": [
            {
                "fingerprint": "f2:def456",
                "summary": "Clarify config precedence",
                "severity": "low",
                "affected_paths": ["src/code_review_loop/cli.py"],
                "rationale": "The suppression path depends on runtime config.",
                "info_requested": "Document whether config values can override suppressions.",
            }
        ],
        "parsing_warnings": [],
        "rejected_findings": [],
        "verification_commands": ["pytest -q"],
    }

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)

    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))
    assert triage_json["confirmed_findings"] == []
    assert triage_json["needs_more_info"][0]["fingerprint"] == "f2:def456"
    assert triage_json["suppressed_findings"][0]["fingerprint"] == "f1:abc123"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert summary["final_status"] == "unknown"
    assert "Structured triage handoff" in (calls[2][1] or "")
    assert len(calls) == 3


def test_loop_skips_remediation_when_structured_triage_only_rejects_findings(tmp_path):
    calls = []
    (tmp_path / ".git").mkdir()
    triage_payload = {
        "confirmed_findings": [],
        "implementation_order": [],
        "needs_more_info": [],
        "parsing_warnings": [],
        "rejected_findings": [
            {
                "fingerprint": "f1:abc123",
                "summary": "Fix profile merge",
                "severity": "medium",
                "affected_paths": ["src/code_review_loop/profiles.py"],
                "rationale": "The review comment is a false positive.",
                "rejection_reason": "Not reproducible in the current code path.",
            }
        ],
        "verification_commands": ["pytest -q"],
    }

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        raise AssertionError(f"remediation/check should not run after rejected-only triage: {args!r}")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)

    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))
    assert triage_json["rejected_findings"][0]["fingerprint"] == "f1:abc123"
    assert triage_json["confirmed_findings"] == []
    assert triage_json["needs_more_info"] == []
    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "triage_rejected_all_findings"
    assert len(calls) == 2


def test_loop_keeps_check_failure_gate_when_structured_triage_rejects_findings(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )
    triage_outputs = iter(
        [
            {
                "confirmed_findings": [
                    {
                        "fingerprint": "f1:abc123",
                        "summary": "Fix profile merge",
                        "severity": "medium",
                        "affected_paths": ["src/code_review_loop/profiles.py"],
                        "rationale": "The review comment is a real issue.",
                    }
                ],
                "implementation_order": ["f1:abc123"],
                "needs_more_info": [],
                "parsing_warnings": [],
                "rejected_findings": [],
                "verification_commands": ["pytest -q"],
            },
            {
                "confirmed_findings": [],
                "implementation_order": [],
                "needs_more_info": [],
                "parsing_warnings": [],
                "rejected_findings": [
                    {
                        "fingerprint": "f2:def456",
                        "summary": "Suppress the false positive",
                        "severity": "low",
                        "affected_paths": ["src/code_review_loop/cli.py"],
                        "rationale": "The remaining review item is not actionable.",
                        "rejection_reason": "Not reproducible in the current code path.",
                    }
                ],
                "verification_commands": ["pytest -q"],
            },
        ]
    )
    check_attempts = 0
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"fixture\"\n", encoding="utf-8")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        nonlocal check_attempts
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(list(args), 0, stdout=json.dumps(next(triage_outputs)))
        if args[0] == "pytest":
            check_attempts += 1
            if check_attempts == 1:
                return MODULE.CommandResult(list(args), 1, stdout="FAILED\n")
            return MODULE.CommandResult(list(args), 0, stdout="passed\n")
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
        check_commands=("pytest -q",),
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert summary["pending_check_failures"] is False
    assert len(calls) == 8
    assert "Check failures from the previous iteration:" in (calls[6][1] or "")
    assert "Structured triage handoff" not in (calls[6][1] or "")


def test_suppress_cli_add_check_remove_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("REVREM_SUPPRESSION_ACTOR", "tester")

    assert MODULE.main(
        [
            "suppress",
            "add",
            "f1:abc123",
            "--summary",
            "Accepted finding",
            "--rationale",
            "Tracked in issue 123.",
            "--severity",
            "medium",
        ]
    ) == 0
    assert MODULE.main(["suppress", "check", "f1:abc123"]) == 0
    assert MODULE.main(["suppress", "remove", "f1:abc123"]) == 0
    assert MODULE.main(["suppress", "check", "f1:abc123"]) == 2
    assert "added f1:abc123" in capsys.readouterr().out


def test_doctor_warns_about_expired_and_unsupported_suppressions(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    suppressions.write_entries(
        suppressions.repo_suppressions_path(tmp_path),
        [
            suppressions.make_entry(
                fingerprint="f1:expired",
                summary="Expired finding",
                rationale="No longer valid.",
                severity="medium",
                scope="repo",
                expires_at="2026-05-01T00:00:00Z",
                critical_override=False,
                created_at="2026-04-01T00:00:00Z",
            ),
            suppressions.make_entry(
                fingerprint="f2:future",
                summary="Unsupported version",
                rationale="Created by a future migration.",
                severity="medium",
                scope="repo",
                expires_at=None,
                critical_override=False,
                created_at="2026-05-12T00:00:00Z",
            ),
        ],
    )

    code = MODULE.main(["doctor", "--format", "json", "--base", "HEAD"])

    assert code in {4, 6}
    output = capsys.readouterr().out
    assert "revrem.suppressions.expired" in output
    assert "revrem.suppressions.unsupported_fingerprint_version" in output


def test_doctor_warns_about_unreadable_optional_suppression_state(
    tmp_path, monkeypatch, capsys
):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    unreadable_path = suppressions.user_suppressions_path(home)

    def fake_stale_entries(path, *, now=None):
        if path == unreadable_path:
            raise PermissionError("blocked")
        return ([], [])

    monkeypatch.setattr(suppressions, "stale_entries", fake_stale_entries)

    exit_code = MODULE.main(["doctor", "--base", "HEAD", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert "revrem.suppressions.invalid_file" in captured.out


def test_loop_invalid_structured_triage_continues_with_original_review(tmp_path):
    calls = []
    triage_attempts = 0

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        nonlocal triage_attempts
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            triage_attempts += 1
            return MODULE.CommandResult(list(args), 0, stdout='{"confirmed_findings": []')
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    MODULE.run_loop(config, runner)

    diagnostics_one = json.loads((tmp_path / "artifacts" / "diagnostics-1.json").read_text(encoding="utf-8"))
    diagnostics_two = json.loads((tmp_path / "artifacts" / "diagnostics-2.json").read_text(encoding="utf-8"))
    assert diagnostics_one["issues"][0]["code"] == "revrem.triage.invalid_output"
    assert diagnostics_two["issues"][0]["code"] == "revrem.triage.invalid_output"
    assert triage_attempts == 2
    assert "Structured triage handoff" not in (calls[2][1] or "")
    assert "Full review comments:\n\n- [P2] Fix profile merge" in (calls[2][1] or "")
    assert "diagnostics-1.json" in {Path(path).name for path in (tmp_path / "artifacts").iterdir()}
    assert "diagnostics-2.json" in {Path(path).name for path in (tmp_path / "artifacts").iterdir()}
    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    assert str(tmp_path / "artifacts" / "diagnostics-1.json") in summary["artifact_paths"]["diagnostics"]
    assert str(tmp_path / "artifacts" / "diagnostics-2.json") in summary["artifact_paths"]["diagnostics"]


def test_loop_failed_triage_command_writes_diagnostics(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(
                list(args),
                -1,
                stderr="Command timed out after 1 second\n",
            )
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        triage_timeout_seconds=1,
        final_review=False,
    )

    with pytest.raises(MODULE.RunLoopFailed):
        MODULE.run_loop(config, runner)

    diagnostics_payload = json.loads(
        (tmp_path / "artifacts" / "diagnostics-1.json").read_text(encoding="utf-8")
    )
    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    assert diagnostics_payload["issues"][0]["code"] == "revrem.triage.command_failed"
    assert diagnostics_payload["issues"][0]["evidence"]["returncode"] == -1
    assert summary["stopped_reason"] == "triage_failed"
    assert str(tmp_path / "artifacts" / "diagnostics-1.json") in summary["artifact_paths"]["diagnostics"]
    assert calls[1][2] == 1


def test_loop_malformed_suppressions_fail_open_for_structured_triage(tmp_path):
    repo_root, cwd = make_git_worktree(tmp_path)
    suppressions_path = suppressions.repo_suppressions_path(cwd)
    suppressions_path.parent.mkdir(parents=True, exist_ok=True)
    suppressions_path.write_text("schema_version = \"1.0\"\nsuppressions = [\n", encoding="utf-8")

    calls = []
    remediation_inputs = []
    run_count = 0

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        nonlocal run_count
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(
                list(args),
                0,
                stdout=json.dumps(
                    {
                        "confirmed_findings": [
                            {
                                "affected_paths": ["src/code.py"],
                                "fingerprint": "f1:abc123",
                                "rationale": "Need fix",
                                "severity": "medium",
                                "summary": "Need fix",
                            }
                        ],
                        "implementation_order": ["f1:abc123"],
                        "needs_more_info": [],
                        "parsing_warnings": [],
                        "rejected_findings": [],
                        "verification_commands": ["pytest -q"],
                    }
                ),
            )
        if args[0] == "codex" and "exec" in args:
            run_count += 1
            remediation_inputs.append(input_text or "")
            return MODULE.CommandResult(list(args), 0, stdout="remediated\n")
        if args[:3] == ["git", "add", "-A"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return MODULE.CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"] and "--stat" in args:
            return MODULE.CommandResult(list(args), 0, stdout=" src/code.py | 1 +\n")
        if args[:3] == ["git", "diff", "--cached"] and "--name-only" in args:
            return MODULE.CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            return MODULE.CommandResult(list(args), 0, stdout="[branch abc] fix(cli): harden RevRem commit flow\n")
        return MODULE.CommandResult(list(args), 0, stdout="passed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
        check_commands=(),
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert run_count == 1
    assert remediation_inputs and "Structured triage handoff" in remediation_inputs[0]
    assert "Fix profile merge" in remediation_inputs[0]
    assert len([call for call in calls if "--sandbox" in call[0]]) == 2


def test_loop_writes_failure_summary_when_triage_fails(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="Full review comments:\n\n- [P2] Fix profile merge\n")
        return MODULE.CommandResult(list(args), 1, stderr="Error: triage failed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        triage_timeout_seconds=60,
    )

    try:
        MODULE.run_loop(config, runner)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected triage failure")

    summary = (tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8")
    assert '"final_status": "error"' in summary
    assert '"stopped_reason": "triage_failed"' in summary
    assert '"artifact_paths"' in summary
    assert "triage-1.txt" in summary
    assert '"1.txt"' not in summary


def test_loop_commits_after_passing_checks(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return MODULE.CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            return MODULE.CommandResult(list(args), 0, stdout="1 passed\n")
        if args[:3] == ["git", "add", "-A"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return MODULE.CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"] and "--stat" in args:
            return MODULE.CommandResult(list(args), 0, stdout=" src/code.py | 2 +-\n")
        if args[:3] == ["git", "diff", "--cached"] and "--name-only" in args:
            return MODULE.CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[0:2] == ["codex", "exec"] and "--sandbox" in args:
            return MODULE.CommandResult(list(args), 0, stdout="fix(cli): harden RevRem commit flow\n")
        if args[:3] == ["git", "commit", "-m"]:
            return MODULE.CommandResult(list(args), 0, stdout="[branch abc] fix(cli): harden RevRem commit flow\n")
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        commit_after_remediation=True,
        commit_message_model="gpt-5.3-codex-spark",
    )

    summary = MODULE.run_loop(config, runner)

    commands = [call[0] for call in calls]
    assert ["git", "add", "-A"] in commands
    assert ["git", "-C", str(repo_root), "reset", "--", "artifacts"] in commands
    assert ["git", "commit", "-m", "fix(cli): harden RevRem commit flow (RevRem)"] in commands
    assert any(command[:6] == ["codex", "exec", "--sandbox", "read-only", "--color", "never"] for command in commands)
    assert summary["iterations"][0]["commit_status"] == "committed"
    assert set(summary["artifact_paths"]["commits"]) == {
        str(tmp_path / "artifacts" / "commit-1-add.txt"),
        str(tmp_path / "artifacts" / "commit-1-reset-artifacts.txt"),
        str(tmp_path / "artifacts" / "commit-1-message-draft.txt"),
        str(tmp_path / "artifacts" / "commit-1.txt"),
        str(tmp_path / "artifacts" / "commit-1-message.txt"),
    }
    commit_prompt = next(
        input_text
        for command, input_text, _timeout in calls
        if command[:6] == ["codex", "exec", "--sandbox", "read-only", "--color", "never"]
    )
    assert commit_prompt is not None and "Files:" in commit_prompt
    assert "Conventional Commit" in commit_prompt
    assert "(RevRem)" in commit_prompt


def test_git_staging_commands_for_commit_reset_relative_artifact_dir(tmp_path):
    repo_root, cwd = make_git_worktree(tmp_path)
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=Path("../artifacts/revrem"),
    )

    assert MODULE.git_add_command_for_commit(config) == ["git", "add", "-A"]
    assert MODULE.git_reset_artifact_command_for_commit(config) == [
        "git",
        "-C",
        str(repo_root),
        "reset",
        "--",
        "artifacts/revrem",
    ]


def test_git_staging_commands_skip_relative_artifact_dir_outside_cwd(tmp_path):
    _repo_root, cwd = make_git_worktree(tmp_path)
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=Path("../../revrem-artifacts"),
    )

    assert MODULE.git_add_command_for_commit(config) == ["git", "add", "-A"]
    assert MODULE.git_reset_artifact_command_for_commit(config) is None


def test_run_commit_refuses_repo_root_artifact_dir_before_staging(tmp_path):
    calls = []
    make_git_worktree(tmp_path, cwd_rel=None)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        return MODULE.CommandResult(list(args), 0, stdout="unexpected\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=Path("."),
        commit_after_remediation=True,
    )

    with pytest.raises(RuntimeError, match="artifact-dir resolves to the repository root"):
        MODULE.run_commit(config, runner, 1)

    assert calls == []


def test_loop_skips_commit_when_checks_fail(tmp_path):
    calls = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "No actionable findings.\nREVIEW_STATUS: clear\n",
        ]
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return MODULE.CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            return MODULE.CommandResult(list(args), 1, stdout="1 failed\n")
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        commit_after_remediation=True,
        commit_message_model="gpt-5.3-codex-spark",
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["iterations"][0]["check_failures"] == 1
    assert "commit_status" not in summary["iterations"][0]
    assert [command for command, _input_text, _timeout in calls if command[0] == "git"] == [
        ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    ]


def test_pytest_check_is_skipped_for_typescript_repo_without_python_surface(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        raise AssertionError("pytest should be skipped before subprocess execution")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
    )

    results, _failed = MODULE.run_checks(config, runner, 1)

    assert calls == []
    assert results[0].returncode == 0

    assert "appears to be non-Python" in results[0].stdout
    assert "SKIPPED adaptive check" in (tmp_path / "artifacts" / "check-1-1.txt").read_text(
        encoding="utf-8"
    )


def test_pytest_check_is_skipped_for_typescript_repo_with_incidental_python_file(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    (tmp_path / "helper.py").write_text("print('helper')\n", encoding="utf-8")
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        raise AssertionError("pytest should be skipped before subprocess execution")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
    )

    results, _failed = MODULE.run_checks(config, runner, 1)

    assert calls == []
    assert results[0].returncode == 0

    assert "appears to be non-Python" in results[0].stdout


@pytest.mark.parametrize("returncode", [2, 4, 5])
def test_pytest_in_typescript_repo_is_normalized_when_subprocess_returns_non_python_codes(
    tmp_path,
    returncode,
):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}\n', encoding="utf-8")
    command = ["pytest", "-q"]
    result = MODULE.CommandResult(command, returncode, stdout="pytest output\n", stderr="pytest error\n")

    normalized = MODULE.normalize_adaptive_check_result(command, tmp_path, result)

    assert normalized.returncode == 0
    assert f"pytest exited {returncode}" in normalized.stdout
    assert "pytest output" in normalized.stdout
    assert "pytest error" in normalized.stdout


def test_pytest_failure_is_preserved_for_python_repo(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    command = ["pytest", "-q"]
    result = MODULE.CommandResult(command, 5, stdout="no tests ran\n")

    assert MODULE.adaptive_check_skip_reason(command, tmp_path) is None
    assert MODULE.normalize_adaptive_check_result(command, tmp_path, result) is result


def test_loop_refuses_to_auto_commit_from_dirty_worktree(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return MODULE.CommandResult(
                list(args),
                0,
                stdout=" M src/other.py\n?? notes.txt\n",
            )
        raise AssertionError(f"unexpected command: {args!r}")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
    )

    with pytest.raises(RuntimeError) as excinfo:
        MODULE.run_loop(config, runner)

    assert "--commit-after-remediation" in str(excinfo.value)
    assert "src/other.py" in str(excinfo.value)
    assert "notes.txt" in str(excinfo.value)
    assert [command for command, _input_text, _timeout in calls] == [
        ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    ]


def test_loop_stops_after_unknown_review_when_remediation_has_no_staged_changes(tmp_path):
    calls = []
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return MODULE.CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return MODULE.CommandResult(list(args), 0, stdout="The implementation appears sound.\n")
        if args[0] == "pytest":
            return MODULE.CommandResult(list(args), 0, stdout="1 passed\n")
        if args[:3] == ["git", "add", "-A"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return MODULE.CommandResult(list(args), 0)
        return MODULE.CommandResult(list(args), 0, stdout="No edits were needed.\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=3,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest -q",),
        commit_after_remediation=True,
    )

    summary = MODULE.run_loop(config, runner)

    review_calls = [command for command, _input_text, _timeout in calls if command[0] == "codex" and "review" in command]
    assert len(review_calls) == 1
    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "no_changes_after_remediation"
    assert summary["iterations"][0]["review_status"] == "unknown"
    assert summary["iterations"][0]["commit_status"] == "skipped_no_changes"


def test_loop_writes_failure_summary_when_commit_fails(tmp_path):
    review_outputs = iter(["Full review comments:\n\n- [P2] Fix profile merge\n"])
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return MODULE.CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[:3] == ["git", "add", "-A"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return MODULE.CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return MODULE.CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            return MODULE.CommandResult(list(args), 1, stderr="nothing to commit\n")
        return MODULE.CommandResult(list(args), 0, stdout="ok\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
    )

    with pytest.raises(MODULE.RunLoopFailed):
        MODULE.run_loop(config, runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == "error"
    assert summary["stopped_reason"] == "commit_failed"
    assert summary["iterations"][0]["commit_failed"] is True
    assert str(tmp_path / "artifacts" / "commit-1.txt") in summary["artifact_paths"]["commits"]


def test_loop_remediates_commit_hook_failure_by_default(tmp_path):
    calls = []
    remediation_prompts = []
    review_outputs = iter(
        [
            "Full review comments:\n\n- [P2] Fix profile merge\n",
            "Full review comments:\n\n- [P2] Fix commit-hook mypy failure\n",
        ]
    )
    commit_attempts = 0
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        nonlocal commit_attempts
        calls.append((list(args), input_text, timeout_seconds))
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return MODULE.CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0:2] == ["codex", "exec"]:
            remediation_prompts.append(input_text or "")
            return MODULE.CommandResult(list(args), 0, stdout="remediated\n")
        if args[:3] == ["git", "add", "-A"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return MODULE.CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return MODULE.CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            commit_attempts += 1
            if commit_attempts == 1:
                return MODULE.CommandResult(
                    list(args),
                    1,
                    stdout=(
                        "Running mypy on staged Python files...\n"
                        "tests/unit/test_loop.py:195: error: Module has no attribute\n"
                        "Found 1 error in 1 file\n"
                    ),
                )
            return MODULE.CommandResult(list(args), 0, stdout="[branch abc] fix\n")
        return MODULE.CommandResult(list(args), 0, stdout="ok\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["iterations"][0]["commit_status"] == "hook_failed"
    assert summary["iterations"][0]["commit_failed"] is True
    assert summary["iterations"][1]["commit_status"] == "committed"
    assert summary["pending_check_failures"] is False
    assert summary["commit_on_hook_failure"] == "remediate"
    assert summary["commit_no_verify"] is False
    assert "Commit hook failure" in remediation_prompts[1]
    assert "Running mypy on staged Python files" in remediation_prompts[1]
    assert str(tmp_path / "artifacts" / "commit-1.txt") in summary["artifact_paths"]["commits"]


def test_loop_stops_on_commit_hook_failure_when_policy_is_stop(tmp_path):
    review_outputs = iter(["Full review comments:\n\n- [P2] Fix profile merge\n"])
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return MODULE.CommandResult(list(args), 0, stdout="")
        if args[0] == "codex" and "review" in args:
            return MODULE.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[:3] == ["git", "add", "-A"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return MODULE.CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return MODULE.CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            return MODULE.CommandResult(
                list(args),
                1,
                stderr="pre-commit hook failed: mypy found 1 error\n",
            )
        return MODULE.CommandResult(list(args), 0, stdout="ok\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
        commit_on_hook_failure="stop",
    )

    with pytest.raises(MODULE.RunLoopFailed):
        MODULE.run_loop(config, runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    assert summary["stopped_reason"] == "commit_hook_failed"
    assert summary["staged_changes_left"] is True
    assert summary["pending_check_failures"] is True
    assert summary["iterations"][0]["commit_status"] == "hook_failed"


def test_run_commit_uses_no_verify_only_on_retry(tmp_path):
    calls = []
    repo_root, cwd = make_git_worktree(tmp_path)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if args[:3] == ["git", "add", "-A"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:4] == ["git", "-C", str(repo_root), "reset"]:
            return MODULE.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return MODULE.CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"]:
            return MODULE.CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "--no-verify"]:
            return MODULE.CommandResult(list(args), 0, stdout="[branch abc] fix\n")
        return MODULE.CommandResult(list(args), 0, stdout="ok\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        commit_message_model=None,
        commit_on_hook_failure="no-verify",
    )

    assert MODULE.run_commit(config, runner, 1) == "committed"
    assert ["git", "commit", "-m", "chore: remediate review iteration 1 (RevRem)"] in calls
    assert ["git", "commit", "--no-verify", "-m", "chore: remediate review iteration 1 (RevRem)"] not in calls

    calls.clear()
    assert MODULE.run_commit(config, runner, 1, retrying=True) == "committed"
    assert ["git", "commit", "--no-verify", "-m", "chore: remediate review iteration 1 (RevRem)"] in calls


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


def test_loop_uses_phase_specific_timeouts_for_review_remediation_and_checks(tmp_path):
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
        timeout_seconds=300,
        review_timeout_seconds=300,
        remediation_timeout_seconds=1800,
    )

    MODULE.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, 1800, 300, 300]


def test_loop_keeps_checks_on_global_timeout_when_remediation_is_disabled(tmp_path):
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
        timeout_seconds=300,
        review_timeout_seconds=300,
        remediation_timeout_seconds=0,
    )

    MODULE.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, None, 300, 300]


def test_loop_preserves_disabled_global_timeout_for_remediation_and_checks(tmp_path):
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
        timeout_seconds=None,
        review_timeout_seconds=300,
        remediation_timeout_seconds=None,
    )

    MODULE.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, None, None, 300]


def test_loop_uses_default_timeout_when_phase_timeouts_are_unset(tmp_path):
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
    )

    MODULE.run_loop(config, runner)

    assert [call[2] for call in calls] == [300, 300, 300, 300]


def test_subprocess_refresh_loop_kills_child_on_interrupt(tmp_path, monkeypatch):
    refresh_calls = []

    class FakeProcess:
        def __init__(self):
            self.killed = False
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise KeyboardInterrupt
            assert self.killed is True
            assert input is None
            return ("stdout", "stderr")

        def kill(self):
            self.killed = True

        def poll(self):
            return None if not self.killed else 0

    fake_process = FakeProcess()

    def fake_popen(*args, **kwargs):
        return fake_process

    def fake_refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr(MODULE.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(MODULE, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(MODULE, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    with pytest.raises(KeyboardInterrupt):
        MODULE.run_subprocess_with_terminal_title_refresh(
            ["codex", "exec"],
            cwd=tmp_path,
            input="prompt",
            timeout=1,
        )

    assert fake_process.killed is True
    assert fake_process.communicate_calls == 2
    assert len(refresh_calls) == 1


def test_repeated_cancellation_signal_within_window_is_marked_forced(monkeypatch):
    monkeypatch.setattr(MODULE, "_LAST_CANCELLATION_SIGNAL_AT", None)

    first = MODULE.cancellation_interrupt_for_signal(MODULE.signal.SIGINT, now=100.0)
    second = MODULE.cancellation_interrupt_for_signal(MODULE.signal.SIGINT, now=103.0)

    assert "controlled cancellation" in str(first)
    assert "forced cancellation" in str(second)


def test_cancellation_signal_after_window_starts_new_controlled_stop(monkeypatch):
    monkeypatch.setattr(MODULE, "_LAST_CANCELLATION_SIGNAL_AT", None)

    MODULE.cancellation_interrupt_for_signal(MODULE.signal.SIGTERM, now=100.0)
    later = MODULE.cancellation_interrupt_for_signal(MODULE.signal.SIGTERM, now=106.0)

    assert "controlled cancellation" in str(later)


def test_kill_process_tree_targets_child_process_group(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 12345

        def kill(self):
            calls.append(("kill", self.pid))

    def fake_killpg(pid, sig):
        calls.append(("killpg", pid, sig))

    monkeypatch.setattr(MODULE.os, "killpg", fake_killpg)

    MODULE.kill_process_tree(FakeProcess())

    assert calls == [("killpg", 12345, MODULE.signal.SIGKILL)]


def test_subprocess_refresh_loop_does_not_resend_input_after_timeout(tmp_path, monkeypatch):
    refresh_calls = []

    class FakeProcess:
        def __init__(self):
            self.communicate_calls = 0
            self.returncode = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                assert input == "prompt"
                raise MODULE.subprocess.TimeoutExpired(["codex", "exec"], timeout)
            assert input is None
            return ("stdout", "stderr")

        def kill(self):
            raise AssertionError("kill should not be called for a normal timeout retry")

        def poll(self):
            return None

    fake_process = FakeProcess()

    def fake_popen(*args, **kwargs):
        return fake_process

    def fake_refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr(MODULE.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(MODULE, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(MODULE, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    completed = MODULE.run_subprocess_with_terminal_title_refresh(
        ["codex", "exec"],
        cwd=tmp_path,
        input="prompt",
        timeout=1,
    )

    assert completed.stdout == "stdout"
    assert completed.stderr == "stderr"
    assert fake_process.communicate_calls == 2
    assert len(refresh_calls) == 2


def test_resolve_timeout_seconds_allows_disabling_timeout():
    assert MODULE.resolve_timeout_seconds(0) is None
    assert MODULE.resolve_timeout_seconds(900) == 900


def test_main_rejects_negative_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = MODULE.main(["--timeout-seconds", "-1"])

    assert exit_code == 1
    assert "--timeout-seconds must be 0 or greater" in capsys.readouterr().err


def test_main_rejects_nonpositive_max_iterations(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = MODULE.main(["--max-iterations", "0"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "--max-iterations must be at least 1" in captured.err
    assert "Traceback" not in captured.err


def test_main_handles_keyboard_interrupt_without_traceback(tmp_path, monkeypatch, capsys):
    def interrupted_run_loop(config):
        raise KeyboardInterrupt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(MODULE, "run_loop", interrupted_run_loop)

    exit_code = MODULE.main([])

    assert exit_code == 5
    assert capsys.readouterr().err == "Cancelled by user.\n"


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
            return MODULE.CommandResult(list(args), 0, stdout="REVIEW_STATUS: findings\n")
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return MODULE.CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        return MODULE.CommandResult(list(args), 0, stdout="remediated\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        initial_review_file=initial_review,
        triage_enabled=True,
        final_review=False,
    )

    summary = MODULE.run_loop(config, runner)

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

    assert MODULE.resolve_initial_review_file("latest", tmp_path) == newer_review


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

    assert MODULE.resolve_initial_review_file("latest", tmp_path) is None


def test_resolve_initial_review_file_latest_returns_none_for_only_clean_runs(tmp_path):
    clean_run = tmp_path / "20260428T020000Z"
    clean_run.mkdir()
    (clean_run / "review-final.txt").write_text("clean", encoding="utf-8")
    (clean_run / "summary.json").write_text(
        json.dumps({"final_status": "clear", "stopped_reason": "review_clear"}),
        encoding="utf-8",
    )

    assert MODULE.resolve_initial_review_file("latest", tmp_path) is None


def test_resolve_initial_review_file_latest_returns_none_without_previous_runs(tmp_path):
    assert MODULE.resolve_initial_review_file("latest", tmp_path) is None


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

    assert MODULE.resolve_initial_review_file("latest", tmp_path) == unresolved_review


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
    (tmp_path / ".git").mkdir()
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


def test_main_save_profile_writes_project_config_and_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    project_config = profiles.project_config_path(tmp_path)
    project_config.write_text("[defaults.pipeline]\nfinal_review = false\n", encoding="utf-8")

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(MODULE, "run_loop", fail_run_loop)

    exit_code = MODULE.main(
        [
            "--base",
            "trunk",
            "--max-iterations",
            "7",
            "--final-review",
            "--review-model",
            "gpt-5.5",
            "--remediation-model",
            "gpt-5.4-mini",
            "--reasoning-effort",
            "medium",
            "--timeout-seconds",
            "1800",
            "--summary-format",
            "text",
            "--debug-status-detection",
            "--terminal-title",
            "--check",
            "pytest -q",
            "--check",
            "git diff --check",
            "--progress-style",
            "rich",
            "--commit-after-remediation",
            "--commit-message-model",
            "gpt-5.3-codex-spark",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    project_config = profiles.project_config_path(tmp_path)
    saved = project_config.read_text(encoding="utf-8")
    assert "[profiles.final-pr]" in saved
    assert "base = \"trunk\"" in saved
    assert "max_iterations = 7" in saved
    assert "\"pytest -q\"" in saved
    assert "\"git diff --check\"" in saved
    assert "model = \"gpt-5.5\"" in saved
    assert "final_review = true" in saved
    assert "progress_style = \"rich\"" in saved
    assert "terminal_title = true" in saved
    assert "enabled = true" in saved


def test_main_save_profile_preserves_disabled_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_run_loop(config):
        raise AssertionError("--save-profile should exit before running the loop")

    monkeypatch.setattr(MODULE, "run_loop", fail_run_loop)

    exit_code = MODULE.main(
        [
            "--timeout-seconds",
            "0",
            "--save-profile",
            "final-pr",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "saved final-pr in" in captured.out
    saved = profiles.project_config_path(tmp_path).read_text(encoding="utf-8")
    assert saved.count("timeout_seconds = 0") == 2


def test_main_save_profile_is_non_destructive_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    project_config = profiles.project_config_path(tmp_path)
    project_config.write_text("[profiles.final-pr]\ndescription = \"Keep me\"\n", encoding="utf-8")

    exit_code = MODULE.main(["--save-profile", "final-pr"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "profile already exists: final-pr" in captured.err
    assert "Keep me" in project_config.read_text(encoding="utf-8")


def test_main_resolves_latest_initial_review_from_profile_artifact_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    custom_root = tmp_path / "custom-artifacts"
    custom_run = custom_root / "20260428T010000Z"
    sibling_root = tmp_path / "other-artifacts"
    sibling_run = sibling_root / "20260428T020000Z"
    custom_run.mkdir(parents=True)
    sibling_run.mkdir(parents=True)

    custom_review = custom_run / "review-final.txt"
    sibling_review = sibling_run / "review-final.txt"
    custom_review.write_text("custom", encoding="utf-8")
    sibling_review.write_text("sibling", encoding="utf-8")
    os.utime(custom_review, (1_000_000, 1_000_000))
    os.utime(sibling_review, (2_000_000, 2_000_000))

    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"""
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.output]
artifact_dir = "{custom_root}"
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

    exit_code = MODULE.main(
        [
            "--profile",
            "final-pr",
            "--initial-review-file",
            "latest",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].artifact_dir == custom_root
    assert captured_configs[0].initial_review_file == custom_review
    assert captured_configs[0].initial_review_file != sibling_review


def test_main_uses_profile_defaults_and_cli_overrides(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
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
reasoning_effort = "low"

[profiles.final-pr.commit]
enabled = true

[profiles.final-pr.output]
summary_format = "json"
debug_status_detection = true
quiet_progress = true

[profiles.final-pr.budgets]
max_wall_seconds = 120
max_tokens = 1000
max_usd = "0.75"
soft_warn_fraction = 0.5
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
    assert config.reasoning_effort is None
    assert config.review_reasoning_effort == "medium"
    assert config.remediation_reasoning_effort == "low"
    assert config.commit_after_remediation is True
    assert config.commit_message_model == "gpt-5.3-codex-spark"
    assert config.timeout_seconds == 300
    assert config.check_commands == ("pytest -q", "git diff --check")
    assert config.debug_status_detection is True
    assert config.progress is False
    assert config.budget_config.max_wall_seconds == 120
    assert config.budget_config.max_tokens == 1000
    assert str(config.budget_config.max_usd) == "0.75"
    assert config.budget_config.soft_warn_fraction == 0.5


def test_default_artifact_dir_uses_revrem_namespace():
    artifact_dir = MODULE.default_artifact_dir()

    assert artifact_dir.parts[:2] == (".revrem", "runs")
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{32}", artifact_dir.name)


def test_run_loop_creates_repo_local_revrem_gitignore_for_default_artifacts(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    MODULE.run_loop(config, runner)

    assert (tmp_path / ".revrem" / ".gitignore").read_text(encoding="utf-8") == "runs/\n"


def test_run_loop_uses_git_info_exclude_for_default_artifacts_in_git_repo(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    git_info = tmp_path / ".git" / "info"
    git_info.mkdir(parents=True)
    (git_info / "exclude").write_text("# local excludes\n", encoding="utf-8")
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    MODULE.run_loop(config, runner)

    assert (git_info / "exclude").read_text(encoding="utf-8") == "# local excludes\n.revrem/runs/\n"
    assert not (tmp_path / ".revrem" / ".gitignore").exists()


def test_run_loop_uses_repo_root_exclude_for_default_artifacts_from_subdirectory(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path / "repo"
    worktree = repo_root / "work"
    git_info = repo_root / ".git" / "info"
    git_info.mkdir(parents=True)
    (git_info / "exclude").write_text("# local excludes\n", encoding="utf-8")
    worktree.mkdir(parents=True)
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=worktree,
        artifact_dir=worktree / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    MODULE.run_loop(config, runner)

    assert (git_info / "exclude").read_text(encoding="utf-8") == (
        "# local excludes\nwork/.revrem/runs/\n"
    )
    assert not (worktree / ".revrem" / ".gitignore").exists()


def test_run_loop_uses_common_exclude_for_default_artifacts_in_linked_worktree(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path / "repo"
    common_git_dir = repo_root / ".git"
    worktrees_dir = common_git_dir / "worktrees"
    linked_git_dir = worktrees_dir / "linked"
    linked_worktree = tmp_path / "linked"

    common_git_dir.mkdir(parents=True)
    (common_git_dir / "info").mkdir()
    (common_git_dir / "info" / "exclude").write_text("# local excludes\n", encoding="utf-8")
    linked_git_dir.mkdir(parents=True)
    linked_worktree.mkdir()
    (linked_worktree / ".git").write_text(f"gitdir: {linked_git_dir}\n", encoding="utf-8")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=linked_worktree,
        artifact_dir=linked_worktree / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    MODULE.run_loop(config, runner)

    assert (common_git_dir / "info" / "exclude").read_text(encoding="utf-8") == (
        "# local excludes\n.revrem/runs/\n"
    )
    assert not (linked_worktree / ".revrem" / ".gitignore").exists()


def test_run_loop_appends_repo_root_exclude_when_existing_longer_entry_contains_substring(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path
    git_info = repo_root / ".git" / "info"
    git_info.mkdir(parents=True)
    (git_info / "exclude").write_text("work/.revrem/runs/\n", encoding="utf-8")
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=repo_root,
        artifact_dir=repo_root / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    MODULE.run_loop(config, runner)

    assert (git_info / "exclude").read_text(encoding="utf-8") == (
        "work/.revrem/runs/\n.revrem/runs/\n"
    )


def test_run_loop_falls_back_to_workspace_gitignore_for_symlinked_default_artifacts(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return MODULE.CommandResult(list(args), 0, stdout="No findings.\n")
        return MODULE.CommandResult(list(args), 0, stdout="fixed\n")

    repo_root = tmp_path / "repo"
    repo_git_info = repo_root / ".git" / "info"
    repo_git_info.mkdir(parents=True)
    (repo_git_info / "exclude").write_text("# local excludes\n", encoding="utf-8")
    (repo_root / "nested").mkdir(parents=True)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    linked_cwd = workspace / "linked"
    linked_cwd.symlink_to(repo_root / "nested", target_is_directory=True)

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=linked_cwd,
        artifact_dir=linked_cwd / ".revrem" / "runs" / "run-1",
        progress=False,
    )

    MODULE.run_loop(config, runner)

    assert (workspace / "linked" / ".revrem" / ".gitignore").read_text(encoding="utf-8") == "runs/\n"
    assert (repo_git_info / "exclude").read_text(encoding="utf-8") == "# local excludes\n"


def test_main_cli_boolean_negations_override_profile_enabled_values(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.runtime]
exec_json = true

[profiles.final-pr.output]
debug_status_detection = true
quiet_progress = true
terminal_title = true
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

    exit_code = MODULE.main(
        [
            "--profile",
            "final-pr",
            "--dry-run",
            "--no-exec-json",
            "--no-debug-status-detection",
            "--no-quiet-progress",
            "--no-terminal-title",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.exec_json is False
    assert config.debug_status_detection is False
    assert config.progress is True
    assert config.terminal_title is False


def test_main_uses_profile_commit_message_harness(tmp_path, monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "profile_or_default",
        lambda name, cwd: profiles.Profile(
            name="final-pr",
            commit=profiles.CommitConfig(
                enabled=True,
                harness="claude",
                message_model="fast-commit",
            ),
        ),
    )
    args = MODULE.parse_args(["--profile", "final-pr", "--dry-run"])

    config, _summary_format = MODULE.build_loop_config(args, tmp_path)

    assert config.commit_message_harness == "claude"
    assert config.commit_message_model == "fast-commit"





def test_run_loop_skips_commit_cleanliness_check_during_dry_run(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        return MODULE.CommandResult(list(args), 0, stdout="should not be used\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
        dry_run=True,
        final_review=False,
        check_commands=("pytest -q",),
    )

    summary = MODULE.run_loop(config, runner)

    assert calls == []
    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "max_iterations_reached"


def test_main_can_reenable_profile_disabled_true_by_default_booleans(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.pipeline]
final_review = false

[profiles.final-pr.runtime]
full_auto = false
output_last_message = false
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

    exit_code = MODULE.main(
        [
            "--profile",
            "final-pr",
            "--full-auto",
            "--output-last-message",
            "--final-review",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.full_auto is True
    assert config.output_last_message is True
    assert config.final_review is True


def test_main_can_disable_profile_commit_with_negative_flag(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.commit]
enabled = true
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

    exit_code = MODULE.main(
        ["--profile", "final-pr", "--no-commit-after-remediation", "--dry-run"]
    )

    assert exit_code == 0
    assert captured_configs[0].commit_after_remediation is False


def test_main_commit_message_model_override_wins_over_profile_default(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.review]
model = "gpt-5.5"

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"

[profiles.final-pr.commit]
enabled = true
message_model = "gpt-5.3-codex-spark"
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

    exit_code = MODULE.main(
        [
            "--profile",
            "final-pr",
            "--commit-message-model",
            "gpt-test-commit",
            "--commit-message-prompt",
            "Write a custom subject.",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured_configs[0].commit_after_remediation is True
    assert captured_configs[0].commit_message_model == "gpt-test-commit"
    assert captured_configs[0].commit_message_prompt == "Write a custom subject."
    assert captured_configs[0].commit_message_prompt_overridden is True


def test_main_commit_message_prompt_override_applies_when_profile_sets_prompt(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.commit]
message_prompt = "Write a custom subject."
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

    exit_code = MODULE.main(["--profile", "final-pr", "--commit-message-model", "gpt-test-commit", "--dry-run"])

    assert exit_code == 0
    assert captured_configs[0].commit_message_prompt == "Write a custom subject."
    assert captured_configs[0].commit_message_prompt_overridden is True


def test_main_reasoning_effort_override_applies_to_review_and_remediation_only(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
reasoning_effort = "medium"

[profiles.final-pr.remediation]
reasoning_effort = "low"

[profiles.final-pr.triage]
enabled = true
model = "gpt-4.1"
reasoning_effort = "minimal"
timeout_seconds = 30
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

    exit_code = MODULE.main(
        ["--profile", "final-pr", "--reasoning-effort", "high", "--dry-run"]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.reasoning_effort == "high"
    assert config.review_reasoning_effort == "high"
    assert config.remediation_reasoning_effort == "high"
    assert config.triage_enabled is True
    assert config.triage_model == "gpt-4.1"
    assert config.triage_reasoning_effort == "minimal"


def test_main_phase_reasoning_effort_overrides_win_independently(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr.triage]
enabled = true
reasoning_effort = "minimal"

[profiles.final-pr.remediation]
reasoning_effort = "low"
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

    exit_code = MODULE.main(
        [
            "--profile",
            "final-pr",
            "--reasoning-effort",
            "medium",
            "--review-reasoning-effort",
            "high",
            "--triage-reasoning-effort",
            "low",
            "--remediation-reasoning-effort",
            "minimal",
            "--commit-reasoning-effort",
            "high",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    config = captured_configs[0]
    assert config.review_reasoning_effort == "high"
    assert config.triage_reasoning_effort == "low"
    assert config.remediation_reasoning_effort == "minimal"
    assert config.commit_reasoning_effort == "high"


def test_main_records_non_dry_run_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return {
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
        }

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)
    monkeypatch.setattr(MODULE, "write_summary", lambda config, summary: None)

    assert MODULE.main(["--base", "main"]) == 0
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
        raise MODULE.RunLoopFailed(summary, "codex exec triage failed for iteration 1")

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    assert MODULE.main(["--base", "main", "--artifact-dir", str(tmp_path / "artifacts")]) == 1
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
        return {
            "run_id": "run-1",
            "started_at": "2026-05-02T10:00:00Z",
            "base": config.base,
            "artifact_dir": str(config.artifact_dir),
            "max_iterations": config.max_iterations,
            "iterations": [],
            "final_status": "clear",
            "stopped_reason": "review_clear",
        }

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    assert MODULE.main(["--dry-run"]) == 0
    assert MODULE.main(["--no-run-history"]) == 0
    assert not (home / ".local" / "share" / "revrem" / "runs.jsonl").exists()


def test_main_skips_history_when_summary_has_no_run_id(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fake_run_loop(config):
        return {
            "artifact_dir": str(config.artifact_dir),
            "iterations": [],
            "final_status": "clear",
            "stopped_reason": "review_clear",
        }

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    assert MODULE.main([]) == 0
    assert not (home / ".local" / "share" / "revrem" / "runs.jsonl").exists()


def test_history_list_command_outputs_recent_runs(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        '{"run_id":"old","final_status":"findings","stopped_reason":"max_iterations_reached","base":"main","artifact_dir":"tmp/old"}\n'
        '{"run_id":\n'
        '{"run_id":"new","final_status":"clear","stopped_reason":"review_clear","base":"main","artifact_dir":"tmp/new"}\n',
        encoding="utf-8",
    )

    assert MODULE.main(["history", "list", "--limit", "1"]) == 0
    text = capsys.readouterr().out
    assert "new clear (review_clear) base=main artifacts=tmp/new" in text
    assert "old" not in text

    assert MODULE.main(["history", "--format", "json", "list", "--limit", "1"]) == 0
    json_text = capsys.readouterr().out
    assert '"run_id": "new"' in json_text
    assert '"run_id": "old"' not in json_text


def test_main_model_override_applies_to_review_and_remediation_only(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
model = "gpt-5.5"

[profiles.final-pr.remediation]
model = "gpt-5.4-mini"

[profiles.final-pr.triage]
enabled = true
model = "gpt-triage"
reasoning_effort = "minimal"
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

    exit_code = MODULE.main(["--profile", "final-pr", "--model", "gpt-test", "--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.model == "gpt-test"
    assert config.review_model == "gpt-test"
    assert config.remediation_model == "gpt-test"
    assert config.triage_enabled is True
    assert config.triage_model == "gpt-triage"
    assert config.triage_reasoning_effort == "minimal"


def test_main_uses_shared_defaults_without_an_explicit_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[defaults.pipeline]
base = "trunk"
max_iterations = 4
checks = ["pytest -q"]

[defaults.review]
model = "gpt-5.5"
timeout_seconds = 300

[defaults.remediation]
model = "gpt-5.4-mini"
timeout_seconds = 1800

[defaults.output]
summary_format = "both"
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

    exit_code = MODULE.main(["--dry-run"])

    assert exit_code == 0
    config = captured_configs[0]
    assert config.base == "trunk"
    assert config.max_iterations == 4
    assert config.check_commands == ("pytest -q",)
    assert config.review_model == "gpt-5.5"
    assert config.remediation_model == "gpt-5.4-mini"
    assert config.review_timeout_seconds == 300
    assert config.remediation_timeout_seconds == 1800
    assert config.timeout_seconds == 300
    assert config.progress is False
    assert config.progress_style == "compact"


def test_main_preserves_zero_timeout_from_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
timeout_seconds = 0

[profiles.final-pr.remediation]
timeout_seconds = 1800
""",
        encoding="utf-8",
    )
    args = MODULE.parse_args(["--profile", "final-pr", "--base", "main"])
    config, summary_format = MODULE.build_loop_config(args, tmp_path)
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text, timeout_seconds))
        return MODULE.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    assert summary_format == "text"
    assert config.timeout_seconds == 300
    assert config.review_timeout_seconds == 0
    assert config.remediation_timeout_seconds == 1800

    object.__setattr__(config, "preflight_enabled", False)
    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert len(calls) == 1
    assert calls[0][2] is None


def test_build_loop_config_rejects_negative_profile_timeout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.review]
timeout_seconds = -1
""",
        encoding="utf-8",
    )

    args = MODULE.parse_args(["--profile", "final-pr", "--base", "main"])

    with pytest.raises(ValueError, match="review.timeout_seconds must be 0 or greater"):
        MODULE.build_loop_config(args, tmp_path)





def test_main_uses_default_timeout_for_unset_phase_specific_timeout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    config_path = home / ".config" / "revrem" / "profiles.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.final-pr]
description = "Final PR"

[profiles.final-pr.remediation]
timeout_seconds = 1800
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
    assert captured_configs[0].timeout_seconds == 300
    assert captured_configs[0].review_timeout_seconds == 300
    assert captured_configs[0].remediation_timeout_seconds == 1800


def test_config_commands_create_show_list_and_delete_profile(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    assert MODULE.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0

    editor = tmp_path / "editor.sh"
    editor.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$1\" > \"$EDITOR_LOG\"\n"
        "sed -i.bak 's/Smoke profile/Edited profile/' \"$1\"\n"
        "rm -f \"$1.bak\"\n",
        encoding="utf-8",
    )
    editor.chmod(0o755)
    editor_log = tmp_path / "editor.log"
    monkeypatch.setenv("EDITOR", str(editor))
    monkeypatch.setenv("EDITOR_LOG", str(editor_log))

    assert MODULE.main(["config", "edit", "smoke"]) == 0
    assert f"edited smoke in {home / '.config' / 'revrem' / 'profiles.toml'}" in capsys.readouterr().out
    assert editor_log.read_text(encoding="utf-8").strip() == str(home / ".config" / "revrem" / "profiles.toml")
    assert "Edited profile" in (home / ".config" / "revrem" / "profiles.toml").read_text(encoding="utf-8")
    assert MODULE.main(["config", "show", "smoke", "--format", "json"]) == 0
    assert '"description": "Edited profile"' in capsys.readouterr().out

    assert MODULE.main(["config", "list"]) == 0
    assert "smoke - Edited profile" in capsys.readouterr().out
    assert MODULE.main(["config", "list", "--format", "json"]) == 0
    assert '"name": "smoke"' in capsys.readouterr().out

    assert MODULE.main(["config", "show", "smoke", "--format", "json"]) == 0
    assert '"name": "smoke"' in capsys.readouterr().out

    assert MODULE.main(["config", "clone", "smoke", "smoke-copy"]) == 0
    assert "cloned smoke to smoke-copy" in capsys.readouterr().out
    assert MODULE.main(["config", "show", "smoke-copy", "--format", "json"]) == 0
    assert '"description": "Edited profile"' in capsys.readouterr().out

    assert MODULE.main(["config", "doctor", "--profile", "smoke", "--format", "json"]) == 0
    assert '"resolved_profile"' in capsys.readouterr().out

    assert MODULE.main(["config", "delete", "smoke", "--yes"]) == 0
    assert MODULE.main(["config", "show", "smoke"]) == 1


def test_config_new_prompts_for_common_fields_when_interactive(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    answers = iter(
        [
            "Interactive profile",
            "codex",
            "gpt-5.5",
            "gpt-5.4-mini",
            "high",
            "1800",
            "git diff --check",
        ]
    )

    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert MODULE.main(["config", "new", "interactive", "--interactive"]) == 0

    assert "created interactive" in capsys.readouterr().out
    resolved = profiles.resolve_profile("interactive", cwd=tmp_path, home=home)
    assert resolved.description == "Interactive profile"
    assert resolved.review.harness == "codex"
    assert resolved.review.model == "gpt-5.5"
    assert resolved.review.reasoning_effort == "high"
    assert resolved.review.timeout_seconds == 1800
    assert resolved.remediation.model == "gpt-5.4-mini"
    assert resolved.pipeline.checks == ("git diff --check",)


def test_config_new_auto_prompts_when_default_invocation_is_tty(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(MODULE.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(MODULE.sys.stdout, "isatty", lambda: True)
    answers = iter(
        [
            "TTY profile",
            "codex",
            "gpt-5.5",
            "gpt-5.4-mini",
            "medium",
            "0",
            "pytest -q",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert MODULE.main(["config", "new", "tty-profile"]) == 0

    resolved = profiles.resolve_profile("tty-profile", cwd=tmp_path, home=home)
    assert resolved.description == "TTY profile"
    assert resolved.review.model == "gpt-5.5"
    assert resolved.remediation.model == "gpt-5.4-mini"
    assert resolved.review.timeout_seconds is None
    assert resolved.pipeline.checks == ("pytest -q",)


def test_config_new_auto_skips_prompt_when_default_invocation_is_not_tty(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(MODULE.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(MODULE.sys.stdout, "isatty", lambda: False)

    def fail_input(_prompt):
        raise AssertionError("non-TTY default config new must not prompt")

    monkeypatch.setattr("builtins.input", fail_input)

    assert MODULE.main(["config", "new", "non-tty-profile"]) == 0

    resolved = profiles.resolve_profile("non-tty-profile", cwd=tmp_path, home=home)
    assert resolved.description == ""
    assert resolved.review.model is None
    assert resolved.pipeline.checks == ()


def test_config_new_no_interactive_preserves_scriptable_minimal_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_input(_prompt):
        raise AssertionError("--no-interactive must not prompt")

    monkeypatch.setattr("builtins.input", fail_input)

    assert MODULE.main(["config", "new", "scripted", "--no-interactive"]) == 0

    resolved = profiles.resolve_profile("scripted", cwd=tmp_path, home=home)
    assert resolved.description == ""
    assert resolved.review.model is None
    assert resolved.pipeline.checks == ()


def test_config_import_rejects_missing_source_file(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    missing = tmp_path / "missing.toml"

    assert MODULE.main(["config", "import", str(missing)]) == 1
    assert "profile import file not found" in capsys.readouterr().err
    assert not (home / ".config" / "revrem" / "profiles.toml").exists()


def test_config_list_includes_last_used_from_run_history(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    assert MODULE.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0

    history_path = home / ".local" / "share" / "revrem" / "runs.jsonl"
    history_path.parent.mkdir(parents=True)
    history_path.write_text(
        "\n".join(
            [
                json.dumps({"profile": "smoke", "finished_at": "2026-05-01T08:00:00Z"}),
                json.dumps({"profile": "other", "finished_at": "2026-05-01T09:00:00Z"}),
                json.dumps({"profile": "smoke", "finished_at": "2026-05-02T10:00:00Z"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert MODULE.main(["config", "list"]) == 0
    output = capsys.readouterr().out
    assert "smoke - Smoke profile" in output
    assert str(home / ".config" / "revrem" / "profiles.toml") in output
    assert "last used 2026-05-02T10:00:00Z" in output

    assert MODULE.main(["config", "list", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == [
        {
            "description": "Smoke profile",
            "last_used_at": "2026-05-02T10:00:00Z",
            "name": "smoke",
            "source": str(home / ".config" / "revrem" / "profiles.toml"),
        }
    ]


def test_config_new_reports_profile_write_oserror(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    def fail_write_user_profile(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(MODULE.profiles, "write_user_profile", fail_write_user_profile)

    assert MODULE.main(["config", "new", "smoke"]) == 1
    assert "ERROR: permission denied" in capsys.readouterr().err


def test_config_global_format_applies_before_subcommand_defaults(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()

    assert MODULE.main(["config", "new", "smoke", "--description", "Smoke profile"]) == 0
    assert MODULE.main(["config", "--format", "json", "doctor", "--profile", "smoke"]) == 0

    output = capsys.readouterr().out
    assert '"resolved_profile"' in output
    assert '"user_config"' in output


def test_config_edit_requires_editor(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    assert MODULE.main(["config", "new", "smoke"]) == 0

    monkeypatch.delenv("EDITOR", raising=False)

    assert MODULE.main(["config", "edit", "smoke"]) == 1
    assert "EDITOR is not set" in capsys.readouterr().err


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
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    check_events = [event for event in records if event.kind == "check_result"]
    assert truncated is False
    assert [event.payload["status"] for event in check_events] == ["failed", "passed"]
    assert check_events[0].payload["command"] == "pytest tests/"
    assert check_events[0].payload["artifact"] == "check-1-1.txt"


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


def test_review_base_preflight_reports_unrelated_local_base_and_origin_hint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "local-main.txt").write_text("local main\n", encoding="utf-8")
    run_git(repo, "add", "local-main.txt")
    run_git(repo, "commit", "-m", "local main")
    run_git(repo, "checkout", "--orphan", "public-launch")
    run_git(repo, "rm", "-rf", ".")
    (repo / "launch.txt").write_text("launch\n", encoding="utf-8")
    run_git(repo, "add", "launch.txt")
    run_git(repo, "commit", "-m", "public launch")
    run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=repo,
        artifact_dir=repo / "artifacts",
    )

    error = MODULE.review_base_preflight_error(config)

    assert error is not None
    assert "HEAD and base 'main' do not share a merge base" in error
    assert "Retry with --base origin/main" in error


def test_run_codex_review_fails_fast_when_base_has_no_merge_base(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    run_git(repo, "add", "main.txt")
    run_git(repo, "commit", "-m", "main")
    run_git(repo, "checkout", "--orphan", "feature")
    run_git(repo, "rm", "-rf", ".")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    run_git(repo, "add", "feature.txt")
    run_git(repo, "commit", "-m", "feature")

    def runner(*_args, **_kwargs):
        raise AssertionError("codex review should not run when base preflight fails")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=repo,
        artifact_dir=repo / "artifacts",
    )

    with pytest.raises(RuntimeError, match="codex review failed for review-1"):
        MODULE.run_codex_review(config, runner, "review-1", display_label="1")

    artifact_text = (repo / "artifacts" / "review-1.txt").read_text(encoding="utf-8")
    assert "Review base preflight failed" in artifact_text
    assert "git merge-base HEAD main" in artifact_text


def test_doctor_json_reports_invalid_base_without_invoking_runner(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    def runner(*_args, **_kwargs):
        raise AssertionError("revrem doctor must not invoke the Codex runner")

    monkeypatch.setattr(MODULE, "default_runner", runner)

    exit_code = MODULE.main(
        ["doctor", "--base", "missing", "--codex-bin", "git", "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {"revrem.preflight.invalid_base"}
    assert captured.err == ""


def test_live_cli_preflight_blocks_before_review_invocation(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    def fail_review(*_args, **_kwargs):
        raise AssertionError("review must not run when live preflight blocks")

    monkeypatch.setattr(MODULE, "run_codex_review", fail_review)

    exit_code = MODULE.main(
        ["--base", "missing", "--codex-bin", "git", "--artifact-dir", "artifacts"]
    )

    diagnostics_payload = json.loads((repo / "artifacts" / "diagnostics.json").read_text(encoding="utf-8"))
    summary = json.loads((repo / "artifacts" / "summary.json").read_text(encoding="utf-8"))

    assert exit_code == 4
    assert diagnostics_payload["status"] == "blocking"
    assert {issue["code"] for issue in diagnostics_payload["issues"]} == {
        "revrem.preflight.invalid_base"
    }
    assert diagnostics_payload["issues"][0]["fingerprint"].startswith("f1:")
    assert summary["stopped_reason"] == "setup_failed"
    assert "preflight diagnostics found blocking issue" in capsys.readouterr().err


def test_doctor_json_reports_missing_git_as_blocking_issue(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(MODULE.diagnostics.subprocess, "run", fake_run)

    exit_code = MODULE.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {"revrem.preflight.git_not_found"}
    assert captured.err == ""


def test_doctor_text_reports_ok_for_valid_repo(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    exit_code = MODULE.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "text"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK: revrem.preflight.ok" in captured.out
    assert captured.err == ""


def test_doctor_validates_default_artifact_dir_when_unset(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    blocked_artifact_dir = repo / ".revrem" / "runs" / "blocked-default"
    blocked_artifact_dir.parent.mkdir(parents=True)
    blocked_artifact_dir.write_text("blocked\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "default_artifact_dir", lambda: blocked_artifact_dir)

    exit_code = MODULE.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {
        "revrem.preflight.artifact_dir_not_writable",
    }
    assert payload["issues"][0]["evidence"]["artifact_dir"] == str(blocked_artifact_dir)
    assert captured.err == ""


def test_doctor_does_not_create_default_artifact_dir_on_clean_repo(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    monkeypatch.chdir(repo)

    default_artifact_dir = repo / ".revrem" / "runs" / "default-run"
    monkeypatch.setattr(MODULE, "default_artifact_dir", lambda: default_artifact_dir)

    exit_code = MODULE.main(["doctor", "--base", "main", "--codex-bin", "git", "--format", "json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert not (repo / ".revrem").exists()
    assert captured.err == ""


def test_doctor_strict_returns_exit_code_6_for_warnings(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.unbounded]
description = "Explicitly unbounded review timeout"

[profiles.unbounded.review]
timeout_seconds = 0
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    exit_code = MODULE.main(
        [
            "doctor",
            "--profile",
            "unbounded",
            "--base",
            "main",
            "--codex-bin",
            "git",
            "--strict",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 6
    assert payload["status"] == "ok"
    assert {issue["code"] for issue in payload["issues"]} == {
        "revrem.preflight.timeout_disabled",
    }
    assert captured.err == ""


def test_doctor_profile_blocks_repo_root_artifact_dir_in_commit_mode(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.commit-root]
description = "Commit mode with a root artifact dir"

[profiles.commit-root.commit]
enabled = true

[profiles.commit-root.output]
artifact_dir = "."
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    exit_code = MODULE.main(
        ["doctor", "--profile", "commit-root", "--base", "main", "--codex-bin", "git", "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 4
    assert payload["status"] == "blocking"
    assert {issue["code"] for issue in payload["issues"]} == {
        "revrem.preflight.artifact_dir_resolves_to_repo_root",
    }
    assert payload["issues"][0]["evidence"]["artifact_dir"] == "."
    assert captured.err == ""


def test_doctor_profile_allows_reserved_harnesses_without_profile_error(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("HOME", str(home))
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "test@example.com")
    run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "initial")
    config_path = profiles.user_config_path(home)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[profiles.smoke]
description = "Smoke profile"

[profiles.smoke.review]
harness = "claude"

[profiles.smoke.remediation]
harness = "gemini"
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    exit_code = MODULE.main(
        ["doctor", "--profile", "smoke", "--base", "main", "--codex-bin", "git", "--format", "json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert {issue["code"] for issue in payload["issues"]} == {"revrem.preflight.ok"}
    assert captured.err == ""


def test_bundle_bug_report_cli_blocks_no_redact_without_explicit_risk_ack(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    exit_code = MODULE.main(["bundle-bug-report", str(run_dir), "--no-redact"])

    captured = capsys.readouterr()
    assert exit_code == 4
    assert "--no-redact requires --i-understand-the-risks" in captured.err


def test_bundle_bug_report_cli_writes_output_path(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        '{"schema_version":"1.0","run_id":"run-123"}\n',
        encoding="utf-8",
    )
    (run_dir / "check-1.txt").write_text("Authorization: Bearer secret-token\n", encoding="utf-8")
    output = tmp_path / "bundle.tar.gz"

    exit_code = MODULE.main(["bundle-bug-report", str(run_dir), "--output", str(output)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == str(output.resolve())
    assert output.is_file()


def run_git(cwd: Path, *args: str) -> None:
    result = MODULE.subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=MODULE.subprocess.PIPE,
        stderr=MODULE.subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr


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


def test_terminal_summary_omits_latest_review_excerpt_when_clear():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "clear",
        "stopped_reason": "review_clear",
        "iterations": [
            {"iteration": 1, "review_status": "clear", "check_failures": None},
        ],
        "artifact_paths": {
            "reviews": ["tmp/run/review-1.txt"],
            "summary": "tmp/run/summary.json",
        },
        "latest_review_excerpt": "I did not find any discrete, actionable bugs.",
    }

    text = MODULE.format_terminal_summary(summary)

    assert "Review-remediation loop: clear (review_clear)" in text
    assert "Latest review: tmp/run/review-1.txt" in text
    assert "Latest actionable review output:" not in text
    assert "discrete, actionable bugs" not in text


def test_terminal_summary_prefers_commit_output_artifact():
    summary = {
        "artifact_dir": "tmp/run",
        "final_status": "findings",
        "stopped_reason": "max_iterations_reached",
        "iterations": [
            {"iteration": 1, "review_status": "findings", "check_failures": 0, "commit_status": "committed"},
        ],
        "artifact_paths": {
            "reviews": ["tmp/run/review-1.txt"],
            "commits": [
                "tmp/run/commit-1-add.txt",
                "tmp/run/commit-1-message-draft.txt",
                "tmp/run/commit-1.txt",
                "tmp/run/commit-1-message.txt",
            ],
            "summary": "tmp/run/summary.json",
        },
    }

    text = MODULE.format_terminal_summary(summary)

    assert "1: review=findings, check failures: 0, commit=committed" in text
    assert "Latest commit artifact: tmp/run/commit-1.txt" in text


def test_summary_records_unknown_review_warning_and_bug_report(tmp_path):
    review_outputs = iter(
        [
            "This review output is ambiguous.\n",
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
        debug_status_detection=True,
    )

    summary = MODULE.run_loop(config, runner)
    text = MODULE.format_terminal_summary(summary)
    report_path = tmp_path / "artifacts" / "unexpected-behavior-report.txt"

    assert summary["final_status"] == "clear"
    assert summary["unexpected_behaviors"] == [
        {
            "kind": "unknown_review_status",
            "iteration": 1,
            "review_path": str(tmp_path / "artifacts" / "review-1.txt"),
            "status_diagnostics_path": str(tmp_path / "artifacts" / "review-1-status.json"),
        }
    ]
    assert summary["bug_report_path"] == str(report_path)
    assert report_path.is_file()
    assert "iteration 1" in report_path.read_text(encoding="utf-8")
    assert "WARNING: unexpected loop behavior detected." in text
    assert f"Bug report details: {report_path}" in text


def test_unknown_final_review_is_recorded_in_diagnostics(tmp_path):
    review_outputs = iter(
        [
            "Needs work.\nREVIEW_STATUS: findings\n",
            "This final review is ambiguous.\n",
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
        debug_status_detection=True,
    )

    summary = MODULE.run_loop(config, runner)
    report_path = tmp_path / "artifacts" / "unexpected-behavior-report.txt"
    final_status_path = tmp_path / "artifacts" / "review-final-status.json"

    assert summary["final_status"] == "unknown"
    assert summary["unexpected_behaviors"] == [
        {
            "kind": "unknown_review_status",
            "iteration": "final",
            "review_path": str(tmp_path / "artifacts" / "review-final.txt"),
            "status_diagnostics_path": str(final_status_path),
        }
    ]
    assert summary["bug_report_path"] == str(report_path)
    assert report_path.is_file()
    assert final_status_path.is_file()


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


def test_compact_progress_uses_local_wall_time(monkeypatch):
    class FakeNow:
        def strftime(self, fmt):
            assert fmt == "%H:%M:%S"
            return "12:34:56"

    class FakeDateTime:
        @classmethod
        def now(cls):
            return FakeNow()

    monkeypatch.setattr(MODULE, "datetime", FakeDateTime)

    assert MODULE.compact_progress_prefix("review", "1") == "12:34:56|rev|1   |"


def test_rich_progress_falls_back_to_compact_once(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(MODULE.progress, "print_rich_event", lambda *args, **kwargs: False)
    monkeypatch.setattr(MODULE, "_RICH_UNAVAILABLE_WARNED", False)
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
    )

    MODULE.progress_event(config, "review", "1", "start", "codex review --base main")
    MODULE.progress_event(config, "review", "1", "clear")
    captured = capsys.readouterr()

    assert captured.err.count("rich progress unavailable; using compact output") == 1
    assert "start: codex review --base main" in captured.err
    assert "|rev|1   |clear" in captured.err


def test_rich_progress_renderer_is_used_when_available(tmp_path, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(
        MODULE.progress,
        "print_rich_event",
        lambda phase, label, status, detail="": calls.append((phase, label, status, detail)) or True,
    )
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
    )

    MODULE.progress_event(config, "review", "1", "start", "codex review --base main")

    assert calls == [("review", "1", "start", "codex review --base main")]
    assert capsys.readouterr().err == ""


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
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE + MODULE.CURSOR_SHOW)


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
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE + MODULE.CURSOR_SHOW)


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


def test_terminal_title_is_suppressed_in_rich_mode_to_avoid_escape_leaks(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    tty_sequences = []
    monkeypatch.setattr(MODULE.sys, "stderr", stderr)
    monkeypatch.setattr(MODULE, "write_terminal_control_to_tty", lambda sequence: tty_sequences.append(sequence) or True)
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
        terminal_title=True,
    )

    with MODULE.terminal_title_context(config):
        MODULE.set_terminal_title(config, "rev 1/1 RevRem")
        MODULE.refresh_terminal_title()

    assert stderr.getvalue() == "".join(
        (
        MODULE.TERMINAL_TITLE_SAVE,
        MODULE.CURSOR_SHOW,
        MODULE.TERMINAL_TITLE_RESTORE,
        )
    )
    assert tty_sequences == []


def test_terminal_title_context_restores_cursor_on_exit(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(MODULE.sys, "stderr", stderr)
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

    output = stderr.getvalue()
    assert MODULE.CURSOR_SHOW in output
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE)


def test_progress_warning_context_resets_rich_unavailable_latch(tmp_path, capsys):
    MODULE._RICH_UNAVAILABLE_WARNED = True

    with MODULE.progress_warning_context():
        MODULE.warn_rich_unavailable("review", "1")
        MODULE.warn_rich_unavailable("review", "1")

    captured = capsys.readouterr()
    assert captured.err.count("rich progress unavailable") == 1
    assert MODULE._RICH_UNAVAILABLE_WARNED is True


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
            10,
        )

    output = stderr.getvalue()
    title_sequence = "\033]0;rev 1/1 RevRem\007\033]2;rev 1/1 RevRem\007"
    assert result.returncode == 0
    assert result.stdout == "done\n"
    assert output.count(title_sequence) >= 2
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE)


def test_default_runner_does_not_refresh_terminal_title_during_rich_progress(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(MODULE.sys, "stderr", stderr)
    monkeypatch.setattr(MODULE, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
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
            10,
        )

    output = stderr.getvalue()
    title_sequence = "\033]0;rev 1/1 RevRem\007\033]2;rev 1/1 RevRem\007"
    assert result.returncode == 0
    assert result.stdout == "done\n"
    assert title_sequence not in output
    assert output.endswith(MODULE.TERMINAL_TITLE_RESTORE)


def test_subprocess_refresh_loop_stops_resending_stdin_after_timeout(tmp_path, monkeypatch):
    refresh_calls = []

    class FakeStdin:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.returncode = 0
            self.communicate_calls = 0
            self.inputs = []

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            self.inputs.append(input)
            if self.communicate_calls == 1:
                assert input == "prompt"
                raise MODULE.subprocess.TimeoutExpired(["codex", "exec"], timeout)
            assert input is None
            assert not self.stdin.closed, "stdin should stay open while waiting on the same child"
            return ("stdout", "stderr")

        def kill(self):
            raise AssertionError("deadline branch is not expected in this test")

    fake_process = FakeProcess()

    def fake_popen(*args, **kwargs):
        return fake_process

    def fake_refresh():
        refresh_calls.append("refresh")

    monkeypatch.setattr(MODULE.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(MODULE, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(MODULE, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    result = MODULE.run_subprocess_with_terminal_title_refresh(
        ["codex", "exec"],
        cwd=tmp_path,
        input="prompt",
        timeout=1,
    )

    assert result.stdout == "stdout"
    assert result.stderr == "stderr"
    assert fake_process.stdin.closed is False
    assert fake_process.communicate_calls == 2
    assert fake_process.inputs == ["prompt", None]
    assert len(refresh_calls) == 2


def test_default_runner_timeout_records_command_cwd_and_partial_output(tmp_path, monkeypatch):
    def fake_run_subprocess(*args, **kwargs):
        raise MODULE.subprocess.TimeoutExpired(
            ["codex", "exec"],
            12,
            output="partial stdout\n",
            stderr="partial stderr\n",
        )

    monkeypatch.setattr(MODULE, "run_subprocess_with_terminal_title_refresh", fake_run_subprocess)

    result = MODULE.default_runner(["codex", "exec"], tmp_path, "prompt", 12)

    assert result.returncode == -1
    assert result.stdout == "partial stdout\n"
    assert "Command timed out after 12 seconds" in result.stderr
    assert "Command: codex exec" in result.stderr
    assert f"cwd: {tmp_path}" in result.stderr
    assert "[partial stderr]\npartial stderr" in result.stderr


def test_default_runner_timeout_kills_process_group_with_pipe_holding_child(tmp_path):
    start = time.monotonic()

    result = MODULE.default_runner(
        ["bash", "-lc", "sleep 30 & wait"],
        tmp_path,
        None,
        0.2,
    )

    assert time.monotonic() - start < 5
    assert result.returncode == -1
    assert "Command timed out after 0.2 seconds" in result.stderr


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
        return MODULE.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=MODULE.budgets.BudgetConfig(max_wall_seconds=0),
        budget_state=MODULE.budgets.BudgetState(started_at_monotonic=0),
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

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
        return MODULE.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=MODULE.budgets.BudgetConfig(max_wall_seconds=100, soft_warn_fraction=0.5),
        budget_state=MODULE.budgets.BudgetState(started_at_monotonic=time.monotonic() - 60),
    )

    MODULE.run_loop(config, runner)

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
        return MODULE.CommandResult(list(args), 0, stdout="REVIEW_STATUS: findings\n", tokens=10)

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=MODULE.budgets.BudgetConfig(max_tokens=10),
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

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
        return MODULE.CommandResult(
            list(args),
            0,
            stdout="REVIEW_STATUS: findings\n",
            usd=Decimal("1.25"),
        )

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=MODULE.budgets.BudgetConfig(max_usd=Decimal("1.25")),
    )

    with pytest.raises(MODULE.RunLoopFailed):
        MODULE.run_loop(config, runner)

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

    def fake_run_loop(_config):
        raise MODULE.RunLoopFailed(summary, "wall budget exceeded")

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    exit_code = MODULE.main(["--max-wall-seconds", "0", "--no-run-history"])

    assert exit_code == 3
    assert "wall budget exceeded" in capsys.readouterr().err


def test_loop_writes_cancellation_summary_when_interrupted(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        raise KeyboardInterrupt

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

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


def test_fake_harness_can_drive_clear_review_without_shelling_out(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        return MODULE.default_runner(args, cwd, input_text, timeout_seconds)

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="review_clear",
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert summary["harness"] == "fake"
    assert calls == [["revrem-fake-harness", "review", "--scenario", "review_clear"]]
    assert (tmp_path / "artifacts" / "review-1.txt").read_text(encoding="utf-8") == (
        "No actionable findings.\nREVIEW_STATUS: clear\n"
    )


def test_fake_harness_can_drive_remediation_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if list(args) == ["revrem-fake-harness", "review", "--scenario", "review_findings"]:
            object.__setattr__(config, "review_model", "review_clear")
        return MODULE.default_runner(args, cwd, input_text, timeout_seconds)

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        remediation_harness="fake",
        review_model="review_findings",
        remediation_model="remediation",
    )

    summary = MODULE.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert summary["iterations"][0]["review_status"] == "findings"
    assert "Fake remediation completed." in (
        tmp_path / "artifacts" / "remediation-1.txt"
    ).read_text(encoding="utf-8")


def test_fake_harness_partial_remediation_surfaces_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        remediation_harness="fake",
        review_model="review_findings",
        remediation_model="remediation_partial",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, MODULE.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "remediation_failed"
    assert "partial progress" in (
        tmp_path / "artifacts" / "remediation-1.txt"
    ).read_text(encoding="utf-8")


def test_fake_harness_can_drive_structured_triage(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if list(args) == ["revrem-fake-harness", "review", "--scenario", "review_findings"]:
            object.__setattr__(config, "review_model", "review_clear")
        return MODULE.default_runner(args, cwd, input_text, timeout_seconds)

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        triage_harness="fake",
        remediation_harness="fake",
        review_model="review_findings",
        triage_model="triage_valid",
        remediation_model="remediation",
        triage_enabled=True,
    )

    summary = MODULE.run_loop(config, runner)
    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))

    assert summary["final_status"] == "clear"
    assert triage_json["confirmed_findings"][0]["fingerprint"] == "f1:fake"


def test_fake_and_codex_summary_shapes_are_structurally_equivalent(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    fake_dir = tmp_path / "fake"
    codex_dir = tmp_path / "codex"
    fake_dir.mkdir()
    codex_dir.mkdir()

    fake_config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=fake_dir,
        artifact_dir=fake_dir / "artifacts",
        review_harness="fake",
        review_model="review_clear",
    )
    codex_config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=codex_dir,
        artifact_dir=codex_dir / "artifacts",
        review_model="review_clear",
    )

    def codex_runner(args, cwd, input_text=None, timeout_seconds=None):
        return MODULE.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    fake_summary = MODULE.run_loop(fake_config, MODULE.default_runner)
    codex_summary = MODULE.run_loop(codex_config, codex_runner)

    assert summary_shape(fake_summary) == summary_shape(codex_summary)
    assert fake_summary["harness"] == "fake"
    assert codex_summary["harness"] == "codex"
    assert fake_summary["final_status"] == codex_summary["final_status"] == "clear"


def test_fake_harness_timeout_surfaces_as_review_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="timeout",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, MODULE.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "review_failed"
    assert "Fake harness timeout" in (
        tmp_path / "artifacts" / "review-1.txt"
    ).read_text(encoding="utf-8")


def test_fake_harness_cancellation_uses_controlled_cancellation_path(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="cancellation",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, MODULE.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "cancelled"
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")
    assert truncated is False
    assert any(event.kind == "cancellation" for event in records)


def test_fake_harness_unsupported_surfaces_as_review_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="unsupported",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, MODULE.default_runner)

    assert excinfo.value.summary["stopped_reason"] == "review_failed"
    assert "unsupported" in (tmp_path / "artifacts" / "review-1.txt").read_text(encoding="utf-8")


def test_fake_harness_token_charge_drives_budget_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv(MODULE.harnesses.FAKE_HARNESS_ENV, "1")
    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="fake",
        review_model="cost_ceiling",
        budget_config=MODULE.budgets.BudgetConfig(max_tokens=10),
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, MODULE.default_runner)

    summary = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))
    records, truncated = events.read_events(tmp_path / "artifacts" / "events.jsonl")

    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"
    assert summary["budgets"]["tokens"] == 10
    assert summary["budgets"]["usd"] is None
    assert truncated is False
    assert any(event.kind == "cost_charge" and event.payload["tokens"] == 10 for event in records)
    assert any(event.kind == "cost_ceiling_hit" and event.payload["ceiling"] == "tokens" for event in records)


def test_summary_records_git_state_for_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "lexical_git_repo_root", lambda _cwd: tmp_path)

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

    summary = MODULE.run_loop(
        MODULE.LoopConfig(
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
    monkeypatch.setattr(MODULE, "lexical_git_repo_root", lambda _cwd: tmp_path)

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
        full_auto=False,
        budget_config=MODULE.budgets.BudgetConfig(
            max_wall_seconds=12.5,
            max_tokens=100,
            max_usd=Decimal("1.25"),
            soft_warn_fraction=0.5,
        ),
    )

    summary = MODULE.run_loop(config, runner)
    resumed = MODULE.resume_loop_config(summary, run_dir=tmp_path / "artifacts")

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

    resumed = MODULE.resume_loop_config(summary, run_dir=tmp_path)

    assert resumed.budget_state is not None
    assert resumed.budget_state.tokens_used == 73
    assert resumed.budget_state.tokens_reported is True
    assert resumed.budget_state.usd_used == Decimal("0.45")
    assert resumed.budget_state.usd_reported is True


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

    resumed = MODULE.resume_loop_config(summary, run_dir=tmp_path)

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
        MODULE.resume_loop_config(summary, run_dir=tmp_path)


def test_summary_records_unavailable_git_state_outside_git(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "lexical_git_repo_root", lambda _cwd: None)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return MODULE.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")

    summary = MODULE.run_loop(
        MODULE.LoopConfig(
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


def summary_shape(value):
    if isinstance(value, dict):
        return {key: summary_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [summary_shape(value[0])] if value else []
    if value is None:
        return None
    return type(value).__name__


def test_main_returns_exit_code_5_for_controlled_cancellation(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    summary = {
        "run_id": "run-1",
        "final_status": "error",
        "stopped_reason": "cancelled",
        "iterations": [],
    }

    def fake_run_loop(_config):
        raise MODULE.RunLoopFailed(summary, "cancelled by operator")

    monkeypatch.setattr(MODULE, "run_loop", fake_run_loop)

    exit_code = MODULE.main(["--no-run-history"])

    assert exit_code == 5
    assert "cancelled by operator" in capsys.readouterr().err


def test_loop_writes_failure_summary_when_initial_review_invocation_fails(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return MODULE.CommandResult(list(args), 1, stderr="Error: failed to create session\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

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
                return MODULE.CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
            return MODULE.CommandResult(list(args), 1, stderr="Error: failed to create session\n")
        return MODULE.CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

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
            return MODULE.CommandResult(
                list(args), 0, stdout="No findings.\nREVIEW_STATUS: clear\n", tokens=500, usd=Decimal("0.03")
            )
        return MODULE.CommandResult(list(args), 0, stdout="ok\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = MODULE.run_loop(config, runner)
    budgets_before = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))["budgets"]

    assert budgets_before["tokens"] == 500
    assert budgets_before["usd"] == "0.03"

    history_path = MODULE.append_run_history(summary, config)
    budgets_after = json.loads((tmp_path / "artifacts" / "summary.json").read_text(encoding="utf-8"))["budgets"]

    assert history_path == home / ".local" / "share" / "revrem" / "runs.jsonl"
    assert budgets_after["tokens"] == budgets_before["tokens"]
    assert budgets_after["usd"] == budgets_before["usd"]


def test_budget_exceeded_propagates_through_triage(tmp_path, monkeypatch):
    exc = MODULE.budgets.BudgetExceeded(ceiling="tokens", limit=100, actual=150)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return MODULE.CommandResult(
            list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n"
        )

    monkeypatch.setattr(MODULE, "run_triage", lambda *a, **kw: (_ for _ in ()).throw(exc))

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"


def test_budget_exceeded_propagates_through_remediation(tmp_path, monkeypatch):
    exc = MODULE.budgets.BudgetExceeded(ceiling="tokens", limit=100, actual=150)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return MODULE.CommandResult(
            list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n"
        )

    monkeypatch.setattr(MODULE, "run_remediation", lambda *a, **kw: (_ for _ in ()).throw(exc))

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

    assert excinfo.value.summary["stopped_reason"] == "budget_ceiling_hit"


def test_budget_exceeded_propagates_through_commit(tmp_path, monkeypatch):
    exc = MODULE.budgets.BudgetExceeded(ceiling="tokens", limit=100, actual=150)

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if "status" in args:
            return MODULE.CommandResult(list(args), 0, stdout="")
        return MODULE.CommandResult(
            list(args), 0, stdout="## Finding\nbad code\nREVIEW_STATUS: findings\n"
        )

    monkeypatch.setattr(MODULE, "run_commit", lambda *a, **kw: (_ for _ in ()).throw(exc))

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_after_remediation=True,
    )

    with pytest.raises(MODULE.RunLoopFailed) as excinfo:
        MODULE.run_loop(config, runner)

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
        return MODULE.CommandResult(list(args), 0, stdout="No findings.\nREVIEW_STATUS: clear\n")

    config = MODULE.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=artifact_dir,
    )

    MODULE.run_loop(config, runner)

    preserved = artifact_dir / "events-original-run.jsonl"
    assert preserved.is_file()
    original_lines = preserved.read_text(encoding="utf-8").strip().splitlines()
    assert len(original_lines) == 3

    new_events = artifact_dir / "events.jsonl"
    assert new_events.is_file()
    new_first = json.loads(new_events.read_text(encoding="utf-8").splitlines()[0])
    assert new_first["run_id"] != "original-run"
