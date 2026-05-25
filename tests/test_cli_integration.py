from __future__ import annotations

import io
import json
import os
import time
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest

import code_review_loop.runner as runner_mod
from code_review_loop import events, suppressions
from code_review_loop import resume as resume_mod
from code_review_loop.core.ports import RunContext
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs

cli_main = import_module("code_review_loop.cli.main")


def make_git_worktree(tmp_path: Path, cwd_rel: str | None = "work") -> tuple[Path, Path]:
    (tmp_path / ".git").mkdir(exist_ok=True)
    cwd = tmp_path if cwd_rel is None else tmp_path / cwd_rel
    cwd.mkdir(parents=True, exist_ok=True)
    return tmp_path, cwd


def make_run_context(runner) -> RunContext:
    return RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )


def test_main_reports_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(["--version"])

    captured = capsys.readouterr()

    assert excinfo.value.code == 0
    assert captured.out.strip() == f"revrem {runner_mod.__version__}"
    assert captured.err == ""


def test_detect_review_status_prefers_explicit_status_line():
    assert runner_mod.detect_review_status("Looks good\nREVIEW_STATUS: clear\n") == "clear"
    assert runner_mod.detect_review_status("One blocker\nREVIEW_STATUS: findings\n") == "findings"


def test_detect_review_status_treats_ambiguous_output_as_unknown():
    assert runner_mod.detect_review_status("This review has a detailed discussion.") == "unknown"


def test_detect_review_status_accepts_exact_clear_review_lines():
    assert runner_mod.detect_review_status("No findings.\n") == "clear"
    assert runner_mod.detect_review_status("summary\nNo actionable findings\n") == "clear"
    assert (
        runner_mod.detect_review_status("I did not find any discrete, actionable bugs in the diff.")
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not find any discrete, actionable correctness issues in the changes."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not find any discrete introduced bug that would break existing behavior."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not find a discrete introduced bug that should block the patch."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not identify any discrete introduced bugs that would block the patch. "
            "The changed code compiles and the repository's dev-check suite passes."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not identify any discrete introduced bugs that should block the patch. "
            "The repository's dev-check suite passes locally."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "The diff was reviewed against the merge base and the changed implementation "
            "has corresponding tests and documentation. I did not identify a discrete "
            "introduced correctness, security, or maintainability issue that should block "
            "the patch."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "The changed code and accompanying tests pass the repository's dev-check suite, "
            "and I did not identify any discrete introduced correctness, security, or "
            "maintainability issue that should block the patch."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "The diff was reviewed and the repository verification suite passes. "
            "I did not identify any discrete introduced correctness, security, or "
            "maintainability issues that should block the patch."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "The changes pass locally without revealing any discrete correctness issue."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not identify any actionable correctness, security, or maintainability issues introduced by the diff."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not identify any introduced correctness, security, or maintainability issues that warrant an inline finding."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I reviewed the diff against the specified merge base and did not identify "
            "any discrete introduced correctness, security, or maintainability issues "
            "that warrant inline findings. The test suite also passes locally."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not identify any blocking defects in this patch. The tests pass."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not find any new regressions in the changed paths."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status("This would warrant an inline finding.") == "unknown"
    )
    assert (
        runner_mod.detect_review_status(
            "The changes add the alias and tests without any clear regressions or actionable bugs."
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            '{\n'
            '  "findings": [],\n'
            '  "explanation": "I did not identify any discrete introduced bugs that should '
            'block the patch."\n'
            '}\n'
        )
        == "clear"
    )
    assert (
        runner_mod.detect_review_status(
            '{"findings": [], "overall_correctness": "patch is correct"}\n'
        )
        == "clear"
    )


def test_detect_review_status_does_not_generalize_negated_clear_with_findings():
    assert (
        runner_mod.detect_review_status(
            "I did not identify any broad design problem.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix the actual bug — src/example.py:10\n"
        )
        == "findings"
    )
    assert (
        runner_mod.detect_review_status(
            "The patch has a concrete issue. I did not identify any alternative approach.\n"
            "Please fix the failure described above."
        )
        == "unknown"
    )
    assert (
        runner_mod.detect_review_status(
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
            return runner_mod.CommandResult(
                list(args),
                0,
                stdout='{"findings": [], "overall_correctness": "patch is correct"}\n',
            )
        raise AssertionError(f"unexpected command: {args}")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner)

    assert summary["final_status"] == "clear"
    assert summary["stopped_reason"] == "review_clear"
    assert [call[0][1] for call in calls] == ["review"]
    assert not (tmp_path / "artifacts" / "remediation-1.txt").exists()


def test_run_loop_writes_replayable_events_jsonl(tmp_path, capsys):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(
                list(args),
                0,
                stdout='{"findings": [], "overall_correctness": "patch is correct"}\n',
            )
        raise AssertionError(f"unexpected command: {args}")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner)
    replay_code = cli_main.main(["replay", str(tmp_path / "artifacts")])
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
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
    )
    from support.phase_harnesses import phase_harness_kwargs

    ctx = RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=None,
        **phase_harness_kwargs(),
        event_sink=sink,
    )

    runner_mod.progress_event(config, "triage", "1", "warning", "suppressions unavailable", ctx=ctx)

    assert sink.events[0].kind == "warning"
    assert sink.events[0].payload["message"] == "suppressions unavailable"


def test_detect_review_status_does_not_treat_scoped_clear_prose_as_clear_when_issue_follows():
    assert (
        runner_mod.detect_review_status(
            "I did not find any issue in the docs, but there is a bug in the CLI."
        )
        == "unknown"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not find any issue in the docs; however, there is a bug in the CLI."
        )
        == "unknown"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not find any discrete issue in the docs.\n\n"
            "However, there is a bug in the parser."
        )
        == "unknown"
    )
    assert (
        runner_mod.detect_review_status(
            "I did not find any actionable bugs.\n\n"
            "No validation prevents this regression."
        )
        == "unknown"
    )
    assert (
        runner_mod.detect_review_status(
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

    assert runner_mod.detect_review_status(output) == "clear"


def test_detect_review_status_recognizes_codex_review_findings():
    output = """The patch has a bug.

Full review comments:

- [P2] Count filtered summaries after filtering — src/example.py:10-12
  This reports misleading data.
"""
    assert runner_mod.detect_review_status(output) == "findings"


def test_review_status_diagnostics_explain_clear_with_stderr_noise():
    output = (
        "The changes add the alias and tests without any clear regressions or actionable bugs.\n\n"
        "[stderr]\n"
        "review comments:\n- [P2] stale transcript example\n"
    )

    diagnostics = runner_mod.review_status_diagnostics(output)

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

    from code_review_loop.cli.commands.config import main as config_main

    exit_code = config_main(["show", "future"])
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
    assert runner_mod.extract_finding_summaries(output, limit=2) == [
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
    assert runner_mod.extract_finding_blocks(output, limit=2, detail_lines=2) == [
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
        runner_mod.extract_review_summary(output)
        == "The loop can omit the only review transcript path in a failure summary."
    )


def test_review_model_is_top_level_codex_option(tmp_path):
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        model="gpt-test",
    )

    command = runner_mod.build_review_command(config)

    assert command[:5] == ["codex", "--model", "gpt-test", "review", "--base"]
    assert command == ["codex", "--model", "gpt-test", "review", "--base", "main"]


def test_non_codex_review_receives_explicit_review_prompt(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return runner_mod.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="claude",
        review_model="sonnet",
    )

    runner_mod.run_loop(config, runner)

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
        return runner_mod.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )

    runner_mod.run_loop(config, runner)

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
    captured: list[runner_mod.LoopConfig] = []

    def fake_run_loop(config):
        captured.append(config)
        return {"final_status": "clear", "stopped_reason": "review_clear"}

    monkeypatch.setattr(runner_mod, "run_loop", fake_run_loop)

    exit_code = cli_main.main(
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
    assert runner_mod.build_review_command(captured[0])[0] == "/tmp/claude-dev"


def test_model_overrides_and_reasoning_effort_are_passed_to_codex(tmp_path):
    config = runner_mod.LoopConfig(
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

    review_command = runner_mod.build_review_command(config)
    remediation_command = runner_mod.build_remediation_command(config)

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
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        exec_json=True,
    )

    command = runner_mod.build_remediation_command(config, tmp_path / "last-message.txt")

    assert "--color" in command
    assert command[command.index("--color") + 1] == "never"
    assert "--json" in command
    assert "--output-last-message" in command
    assert command[-1] == "-"


def test_triage_command_uses_read_only_exec_with_phase_model(tmp_path):
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_model="gpt-5.4-mini",
        triage_reasoning_effort="low",
    )

    command = runner_mod.build_triage_command(config)

    assert command[:4] == ["codex", "exec", "-c", 'model_reasoning_effort="low"']
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-5.4-mini"
    assert "--full-auto" not in command
    assert command[-1] == "-"


def test_commit_message_command_uses_read_only_exec_with_configured_model(tmp_path):
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-5.3-codex-spark",
        commit_reasoning_effort="minimal",
    )

    command = runner_mod.build_commit_message_command(config)

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
        runner_mod.sanitize_commit_message(
            'Commit message: "Harden RevRem commit flow"\n\nExplanation...',
            fallback="fallback",
        )
        == "chore: Harden RevRem commit flow (RevRem)"
    )
    assert (
        runner_mod.sanitize_commit_message("fix(cli): stop on no-op remediation", fallback="fallback")
        == "fix(cli): stop on no-op remediation (RevRem)"
    )
    assert runner_mod.sanitize_commit_message("", fallback="fallback") == "chore: fallback (RevRem)"
    assert (
        runner_mod.sanitize_commit_message(
            "Use custom format",
            fallback="fallback",
            enforce_revrem_conventional=False,
        )
        == "Use custom format"
    )


def test_commit_message_for_staged_changes_respects_profile_prompt_override(tmp_path):
    config = runner_mod.LoopConfig(
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
            return runner_mod.CommandResult(list(args), 0, stdout=" file.py | 2 +-\n")
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return runner_mod.CommandResult(list(args), 0, stdout="file.py\n")
        if args[:2] == ["codex", "exec"]:
            return runner_mod.CommandResult(list(args), 0, stdout="Use custom format\n")
        raise AssertionError(f"unexpected command: {args!r}")

    message = runner_mod.commit_message_for_staged_changes(config, runner, 1, make_run_context(runner))

    assert message == "Use custom format"
    assert "Write a custom subject." in next(
        prompt for args, prompt in calls if args[:2] == ["codex", "exec"]
    )


def test_normalize_revrem_conventional_subject_preserves_suffix_when_truncated():
    subject = "fix(cli): " + "x" * 200

    normalized = runner_mod.normalize_revrem_conventional_subject(subject)

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


def test_suppress_cli_add_check_remove_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("REVREM_SUPPRESSION_ACTOR", "tester")

    assert cli_main.main(
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
    assert cli_main.main(["suppress", "check", "f1:abc123"]) == 0
    assert cli_main.main(["suppress", "remove", "f1:abc123"]) == 0
    assert cli_main.main(["suppress", "check", "f1:abc123"]) == 2
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

    code = cli_main.main(["doctor", "--format", "json", "--base", "HEAD"])

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

    exit_code = cli_main.main(["doctor", "--base", "HEAD", "--codex-bin", "git", "--format", "json"])

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
            return runner_mod.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            triage_attempts += 1
            return runner_mod.CommandResult(list(args), 0, stdout='{"confirmed_findings": []')
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return runner_mod.CommandResult(
                list(args),
                -1,
                stderr="Command timed out after 1 second\n",
            )
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        triage_timeout_seconds=1,
        final_review=False,
    )

    with pytest.raises(runner_mod.RunLoopFailed):
        runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return runner_mod.CommandResult(
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
            return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")
        if args[:3] == ["git", "add", "-A"]:
            return runner_mod.CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return runner_mod.CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"] and "--stat" in args:
            return runner_mod.CommandResult(list(args), 0, stdout=" src/code.py | 1 +\n")
        if args[:3] == ["git", "diff", "--cached"] and "--name-only" in args:
            return runner_mod.CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            return runner_mod.CommandResult(list(args), 0, stdout="[branch abc] fix(cli): harden RevRem commit flow\n")
        return runner_mod.CommandResult(list(args), 0, stdout="passed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
        check_commands=(),
    )

    summary = runner_mod.run_loop(config, runner)

    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert run_count == 1
    assert remediation_inputs and "Structured triage handoff" in remediation_inputs[0]
    assert "Fix profile merge" in remediation_inputs[0]
    assert len([call for call in calls if "--sandbox" in call[0]]) == 2


def test_loop_writes_failure_summary_when_triage_fails(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="Full review comments:\n\n- [P2] Fix profile merge\n")
        return runner_mod.CommandResult(list(args), 1, stderr="Error: triage failed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        triage_timeout_seconds=60,
    )

    try:
        runner_mod.run_loop(config, runner)
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


def test_debug_status_detection_writes_diagnostic_artifact(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="No findings.\n")
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        debug_status_detection=True,
    )

    summary = runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="ok\n")

    config = runner_mod.LoopConfig(
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

    runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="ok\n")

    config = runner_mod.LoopConfig(
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

    runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="ok\n")

    config = runner_mod.LoopConfig(
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

    runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="ok\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("python -m pytest tests/unit",),
    )

    runner_mod.run_loop(config, runner)

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

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_mod, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(runner_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    with pytest.raises(KeyboardInterrupt):
        runner_mod.run_subprocess_with_terminal_title_refresh(
            ["codex", "exec"],
            cwd=tmp_path,
            input="prompt",
            timeout=1,
        )

    assert fake_process.killed is True
    assert fake_process.communicate_calls == 2
    assert len(refresh_calls) == 1


def test_repeated_cancellation_signal_within_window_is_marked_forced(monkeypatch):
    monkeypatch.setattr(runner_mod, "_LAST_CANCELLATION_SIGNAL_AT", None)

    first = runner_mod.cancellation_interrupt_for_signal(runner_mod.signal.SIGINT, now=100.0)
    second = runner_mod.cancellation_interrupt_for_signal(runner_mod.signal.SIGINT, now=103.0)

    assert "controlled cancellation" in str(first)
    assert "forced cancellation" in str(second)


def test_cancellation_signal_after_window_starts_new_controlled_stop(monkeypatch):
    monkeypatch.setattr(runner_mod, "_LAST_CANCELLATION_SIGNAL_AT", None)

    runner_mod.cancellation_interrupt_for_signal(runner_mod.signal.SIGTERM, now=100.0)
    later = runner_mod.cancellation_interrupt_for_signal(runner_mod.signal.SIGTERM, now=106.0)

    assert "controlled cancellation" in str(later)


def test_kill_process_tree_targets_child_process_group(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 12345

        def kill(self):
            calls.append(("kill", self.pid))

    def fake_killpg(pid, sig):
        calls.append(("killpg", pid, sig))

    monkeypatch.setattr(runner_mod.os, "killpg", fake_killpg)

    runner_mod.kill_process_tree(FakeProcess())

    assert calls == [("killpg", 12345, runner_mod.signal.SIGKILL)]


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
                raise runner_mod.subprocess.TimeoutExpired(["codex", "exec"], timeout)
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

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_mod, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(runner_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    completed = runner_mod.run_subprocess_with_terminal_title_refresh(
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
    assert runner_mod.resolve_timeout_seconds(0) is None
    assert runner_mod.resolve_timeout_seconds(900) == 900


def test_main_rejects_negative_timeout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["--timeout-seconds", "-1"])

    assert exit_code == 1
    assert "--timeout-seconds must be 0 or greater" in capsys.readouterr().err


def test_main_rejects_nonpositive_max_iterations(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = cli_main.main(["--max-iterations", "0"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "--max-iterations must be at least 1" in captured.err
    assert "Traceback" not in captured.err


def test_main_handles_keyboard_interrupt_without_traceback(tmp_path, monkeypatch, capsys):
    def interrupted_run_loop(config):
        raise KeyboardInterrupt

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner_mod, "run_loop", interrupted_run_loop)

    exit_code = cli_main.main([])

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


def test_loop_caps_remediation_passes_and_runs_final_review(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return runner_mod.CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
        return runner_mod.CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner)

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
                return runner_mod.CommandResult(list(args), 0, stdout="Still failing.\nREVIEW_STATUS: findings\n")
            return runner_mod.CommandResult(list(args), 0, stdout="No actionable findings.\nREVIEW_STATUS: clear\n")
        return runner_mod.CommandResult(list(args), 0, stdout="attempted remediation\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            rc, out = next(check_outputs)
            return runner_mod.CommandResult(list(args), rc, stdout=out)
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest tests/",),
    )

    summary = runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            rc, out = next(check_outputs)
            return runner_mod.CommandResult(list(args), rc, stdout=out)
        return runner_mod.CommandResult(list(args), 0, stdout="remediated\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        check_commands=("pytest tests/",),
    )

    summary = runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout="Issues found.\nREVIEW_STATUS: findings\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner)

    assert summary["final_status"] == "unknown", (
        "status after last remediation is unknowable without a follow-up review"
    )
    assert summary["stopped_reason"] == "max_iterations_reached"


def test_final_check_failure_prevents_clear_status(tmp_path):
    config = runner_mod.LoopConfig(
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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        if args[0] == "pytest":
            return runner_mod.CommandResult(list(args), 1, stdout="1 FAILED\n")
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    summary = runner_mod.run_loop(config, sequenced_runner)

    assert summary["final_status"] == "findings"
    assert summary["pending_check_failures"] is True
    assert summary["stopped_reason"] == "max_iterations_reached_with_check_failures"


def test_detect_review_status_requires_explicit_status_line():
    """Fuzzy patterns must not flip ambiguous output to clear."""
    assert runner_mod.detect_review_status("no findings about style, but several about logic") == "unknown"
    assert runner_mod.detect_review_status("review is clear of syntax errors but not semantic") == "unknown"
    assert runner_mod.detect_review_status("") == "unknown"


def test_review_failure_detection_allows_nonzero_findings_without_stderr():
    assert (
        runner_mod.review_failed_to_run(
            runner_mod.CommandResult(["codex", "review"], -9, stdout="", stderr="")
        )
        is True
    )
    assert (
        runner_mod.review_failed_to_run(
            runner_mod.CommandResult(["codex", "review"], 1, stdout="Finding\n", stderr="")
        )
        is False
    )
    assert (
        runner_mod.review_failed_to_run(
            runner_mod.CommandResult(["codex", "review"], 1, stdout="", stderr="Error: thread/start failed")
        )
        is True
    )
    assert (
        runner_mod.review_failed_to_run(
            runner_mod.CommandResult(["codex", "review"], 2, stdout="", stderr="error: bad args")
        )
        is True
    )


def run_git(cwd: Path, *args: str) -> None:
    result = runner_mod.subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=runner_mod.subprocess.PIPE,
        stderr=runner_mod.subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_actionable_review_output_drops_verbose_stderr_transcript():
    output = "Full review comments:\n\n- [P1] Fix the bug\n\n[stderr]\n" + ("diff --git a/x b/x\n" * 100)

    assert runner_mod.actionable_review_output(output) == "Full review comments:\n\n- [P1] Fix the bug"


def test_trim_for_prompt_caps_large_review_text():
    from code_review_loop import prompts_composer

    text = "a" * 100 + "MIDDLE" + "z" * 100

    trimmed = prompts_composer.trim_for_prompt(text, 80)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        max_remediation_input_chars=200,
    )

    runner_mod.run_loop(config, runner)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )

    summary = runner_mod.run_loop(config, runner)

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

    text = runner_mod.format_terminal_summary(summary)

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

    text = runner_mod.format_terminal_summary(summary)

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

    text = runner_mod.format_terminal_summary(summary)

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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        debug_status_detection=True,
    )

    summary = runner_mod.run_loop(config, runner)
    text = runner_mod.format_terminal_summary(summary)
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
            return runner_mod.CommandResult(list(args), 0, stdout=next(review_outputs))
        return runner_mod.CommandResult(list(args), 0, stdout="fixed\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        debug_status_detection=True,
    )

    summary = runner_mod.run_loop(config, runner)
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


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


def test_default_runner_refreshes_active_terminal_title_during_child_process(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(runner_mod.sys, "stderr", stderr)
    monkeypatch.setattr(runner_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        terminal_title=True,
    )

    with runner_mod.terminal_title_context(config):
        runner_mod.set_terminal_title(config, "rev 1/1 RevRem")
        result = runner_mod.default_runner(
            [
                runner_mod.sys.executable,
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
    assert output.endswith(runner_mod.TERMINAL_TITLE_RESTORE)


def test_default_runner_does_not_refresh_terminal_title_during_rich_progress(tmp_path, monkeypatch):
    stderr = TtyBuffer()
    monkeypatch.setattr(runner_mod.sys, "stderr", stderr)
    monkeypatch.setattr(runner_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)
    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress_style="rich",
        terminal_title=True,
    )

    with runner_mod.terminal_title_context(config):
        runner_mod.set_terminal_title(config, "rev 1/1 RevRem")
        result = runner_mod.default_runner(
            [
                runner_mod.sys.executable,
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
    assert output.endswith(runner_mod.TERMINAL_TITLE_RESTORE)


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
                raise runner_mod.subprocess.TimeoutExpired(["codex", "exec"], timeout)
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

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_mod, "refresh_terminal_title", fake_refresh)
    monkeypatch.setattr(runner_mod, "TERMINAL_TITLE_REFRESH_SECONDS", 0.01)

    result = runner_mod.run_subprocess_with_terminal_title_refresh(
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
        raise runner_mod.subprocess.TimeoutExpired(
            ["codex", "exec"],
            12,
            output="partial stdout\n",
            stderr="partial stderr\n",
        )

    monkeypatch.setattr(runner_mod, "run_subprocess_with_terminal_title_refresh", fake_run_subprocess)

    result = runner_mod.default_runner(["codex", "exec"], tmp_path, "prompt", 12)

    assert result.returncode == -1
    assert result.stdout == "partial stdout\n"
    assert "Command timed out after 12 seconds" in result.stderr
    assert "Command: codex exec" in result.stderr
    assert f"cwd: {tmp_path}" in result.stderr
    assert "[partial stderr]\npartial stderr" in result.stderr


def test_default_runner_timeout_kills_process_group_with_pipe_holding_child(tmp_path):
    start = time.monotonic()

    result = runner_mod.default_runner(
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
            return runner_mod.CommandResult(list(args), 0, stdout="Full review comments:\n\n- [P1] Fix\n")
        return runner_mod.CommandResult(list(args), 1, stderr="Error: turn/start failed\n")

    config = runner_mod.LoopConfig(
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
        return runner_mod.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=runner_mod.budgets.BudgetConfig(max_wall_seconds=0),
    )

    with pytest.raises(runner_mod.RunLoopFailed) as excinfo:
        runner_mod.run_loop(config, runner, budget_state=runner_mod.budgets.BudgetState(started_at_monotonic=0))

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
        return runner_mod.CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=runner_mod.budgets.BudgetConfig(max_wall_seconds=100, soft_warn_fraction=0.5),
    )

    runner_mod.run_loop(config, runner, budget_state=runner_mod.budgets.BudgetState(started_at_monotonic=time.monotonic() - 60))

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
        return runner_mod.CommandResult(list(args), 0, stdout="REVIEW_STATUS: findings\n", tokens=10)

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=runner_mod.budgets.BudgetConfig(max_tokens=10),
    )

    with pytest.raises(runner_mod.RunLoopFailed) as excinfo:
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
        return runner_mod.CommandResult(
            list(args),
            0,
            stdout="REVIEW_STATUS: findings\n",
            usd=Decimal("1.25"),
        )

    config = runner_mod.LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        budget_config=runner_mod.budgets.BudgetConfig(max_usd=Decimal("1.25")),
    )

    with pytest.raises(runner_mod.RunLoopFailed):
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

    def fake_run_loop(_config):
        raise runner_mod.RunLoopFailed(
            summary,
            "wall budget exceeded",
            outcome=runner_mod.OutcomeFailed(reason="budget_ceiling_hit", error="wall budget exceeded"),
        )

    monkeypatch.setattr(runner_mod, "run_loop", fake_run_loop)

    exit_code = cli_main.main(["--max-wall-seconds", "0", "--no-run-history"])

    assert exit_code == 3
    assert "wall budget exceeded" in capsys.readouterr().err


def test_loop_writes_cancellation_summary_when_interrupted(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        raise KeyboardInterrupt

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


def test_summary_records_git_state_for_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "lexical_git_repo_root", lambda _cwd: tmp_path)

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

    monkeypatch.setattr(runner_mod, "run_git_preflight", fake_run_git_preflight)

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
    monkeypatch.setattr(runner_mod, "lexical_git_repo_root", lambda _cwd: tmp_path)

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

    monkeypatch.setattr(runner_mod, "run_git_preflight", fake_run_git_preflight)

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
    monkeypatch.setattr(runner_mod, "lexical_git_repo_root", lambda _cwd: None)

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

    monkeypatch.setattr(runner_mod, "run_loop", fake_run_loop)

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
