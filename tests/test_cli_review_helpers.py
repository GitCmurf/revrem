from __future__ import annotations

from importlib import import_module

import code_review_loop.runner as runner_mod
from code_review_loop import events
from code_review_loop.core.ports import RunContext
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs

cli_main = import_module("code_review_loop.cli.main")


def make_run_context(runner) -> RunContext:
    return RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )


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
