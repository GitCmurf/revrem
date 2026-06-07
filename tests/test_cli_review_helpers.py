from __future__ import annotations

import json
import re
import subprocess
from importlib import import_module
from pathlib import Path

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop import application, events, waiting_progress
from code_review_loop.adapters import remediation as remediation_impl
from code_review_loop.adapters import review as review_impl
from code_review_loop.adapters import triage as triage_impl
from code_review_loop.adapters.commit import (
    commit_message_for_staged_changes,
    deterministic_commit_message,
)
from code_review_loop.adapters.phase_support import (
    DEFAULT_COMMIT_MESSAGE_PROMPT,
    build_commit_message_command,
    normalize_revrem_conventional_subject,
    progress_event,
    run_with_waiting_progress,
    sanitize_commit_message,
)
from code_review_loop.adapters.review import review_failed_to_run
from code_review_loop.config import LoopConfig
from code_review_loop.core.outcome import OutcomeClear
from code_review_loop.core.ports import CommandResult, RunContext
from code_review_loop.core.review_interpretation import (
    actionable_review_output,
    detect_review_status,
    extract_finding_blocks,
    extract_finding_summaries,
    extract_review_summary,
    review_status_diagnostics,
)
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs

cli_main = import_module("code_review_loop.cli.main")


def assert_professional_fallback_subject(
    message: str,
    *,
    expected_type: str,
    expected_scope: str | None,
    expected_terms: tuple[str, ...],
) -> None:
    if expected_scope is None:
        assert message.startswith(f"{expected_type}: ")
    else:
        assert message.startswith(f"{expected_type}({expected_scope}): ")
    assert message.endswith(" (RevRem)")
    lowered = message.lower()
    assert "apply verified remediation" not in lowered
    assert "remediate review iteration" not in lowered
    assert "triage cli override" not in lowered
    assert "preserve review excerpts" not in lowered
    assert "validate profiles correctly" not in lowered
    for term in expected_terms:
        assert term in lowered
    assert re.search(r"^(\w+)(?:\([^)]*\))?: \1\b", lowered) is None
    assert re.search(r"^(\w+)\(\1s?\):", lowered) is None


def commit_subject_summary(message: str) -> str:
    return message.removesuffix(" (RevRem)").split(": ", 1)[1]


def make_run_context(runner) -> RunContext:
    return RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=runner,
        **phase_harness_kwargs(),
    )


def test_detect_review_status_prefers_explicit_status_line():
    assert detect_review_status("Looks good\nREVIEW_STATUS: clear\n") == "clear"
    assert detect_review_status("One blocker\nREVIEW_STATUS: findings\n") == "findings"


def test_detect_review_status_treats_ambiguous_output_as_unknown():
    assert detect_review_status("This review has a detailed discussion.") == "unknown"


def test_detect_review_status_accepts_exact_clear_review_lines():
    assert detect_review_status("No findings.\n") == "clear"
    assert detect_review_status("summary\nNo actionable findings\n") == "clear"
    assert (
        detect_review_status(
            "I did not find any discrete, actionable bugs in the diff."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not find any discrete, actionable correctness issues in the changes."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any introduced, actionable correctness issues in "
            "the changed code. A local full pytest run had one subprocess import "
            "failure in an existing test/tool path, but it does not appear tied "
            "to the diff under review."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not find any discrete introduced bug that would break existing behavior."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not find a discrete introduced bug that should block the patch."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any discrete introduced bugs that would block the patch. "
            "The changed code compiles and the repository's dev-check suite passes."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any discrete introduced bugs that should block the patch. "
            "The repository's dev-check suite passes locally."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "The diff was reviewed against the merge base and the changed implementation "
            "has corresponding tests and documentation. I did not identify a discrete "
            "introduced correctness, security, or maintainability issue that should block "
            "the patch."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "The changed code and accompanying tests pass the repository's dev-check suite, "
            "and I did not identify any discrete introduced correctness, security, or "
            "maintainability issue that should block the patch."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "The diff was reviewed and the repository verification suite passes. "
            "I did not identify any discrete introduced correctness, security, or "
            "maintainability issues that should block the patch."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "The changes pass locally without revealing any discrete correctness issue."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any actionable correctness, security, or maintainability issues introduced by the diff."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any introduced correctness, security, or maintainability issues that warrant an inline finding."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I reviewed the diff against the specified merge base and did not identify "
            "any discrete introduced correctness, security, or maintainability issues "
            "that warrant inline findings. The test suite also passes locally."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not identify any blocking defects in this patch. The tests pass."
        )
        == "clear"
    )
    assert (
        detect_review_status("I did not find any new regressions in the changed paths.")
        == "clear"
    )
    assert (
        detect_review_status(
            "I did not find any actionable bugs introduced by the reviewed diff. "
            "The full test suite has one failure in an unchanged test path that appears "
            "to be a local environment/PYTHONPATH issue rather than a regression in "
            "the proposed changes."
        )
        == "clear"
    )
    assert detect_review_status("This would warrant an inline finding.") == "unknown"
    assert (
        detect_review_status(
            "The changes add the alias and tests without any clear regressions or actionable bugs."
        )
        == "clear"
    )
    assert (
        detect_review_status(
            "{\n"
            '  "findings": [],\n'
            '  "explanation": "I did not identify any discrete introduced bugs that should '
            'block the patch."\n'
            "}\n"
        )
        == "clear"
    )
    assert (
        detect_review_status(
            '{"findings": [], "overall_correctness": "patch is correct"}\n'
        )
        == "clear"
    )


def test_detect_review_status_does_not_generalize_negated_clear_with_findings():
    assert (
        detect_review_status(
            "I did not identify any broad design problem.\n\n"
            "Full review comments:\n\n"
            "- [P2] Fix the actual bug — src/example.py:10\n"
        )
        == "findings"
    )
    assert (
        detect_review_status(
            "The patch has a concrete issue. I did not identify any alternative approach.\n"
            "Please fix the failure described above."
        )
        == "unknown"
    )
    assert (
        detect_review_status(
            "I did not identify any broad design problem.\n\n"
            "- [P3] Tighten docs — docs/example.md:1\n"
        )
        == "findings"
    )


def test_prompted_review_harness_requires_explicit_status_for_clear_prose():
    output = (
        "I did not find any actionable bugs introduced by the reviewed diff. "
        "No remediation is needed."
    )

    assert detect_review_status(output, harness="gemini") == "unknown"
    diagnostics = review_status_diagnostics(output, harness="gemini")
    assert diagnostics["explicit_status_required"] is True
    assert diagnostics["status_source"] == "none"


def test_prompted_review_harness_accepts_explicit_status_and_records_tool_denial():
    output = (
        "The supplied diff has no actionable findings.\n"
        "REVIEW_STATUS: clear\n\n"
        "[stderr]\n"
        "Error executing tool run_shell_command: Tool execution denied by policy.\n"
    )

    assert detect_review_status(output, harness="gemini") == "clear"
    diagnostics = review_status_diagnostics(output, harness="gemini")
    assert diagnostics["status_source"] == "explicit_status"
    assert diagnostics["tool_denial_present"] is True
    assert diagnostics["tool_denial_source"] == "stderr_control"
    assert (
        diagnostics["tool_denial_evidence"]
        == "Error executing tool run_shell_command: Tool execution denied by policy."
    )


def test_review_status_diagnostics_ignores_tool_denial_text_outside_stderr():
    output = (
        "The reviewed tests include this literal fixture text:\n"
        "Error executing tool run_shell_command: Tool execution denied by policy.\n"
        "REVIEW_STATUS: clear\n\n"
        "[stderr]\n"
        "Provider emitted non-fatal progress logs.\n"
    )

    diagnostics = review_status_diagnostics(output, harness="opencode")

    assert diagnostics["status"] == "clear"
    assert diagnostics["stderr_present"] is True
    assert diagnostics["tool_denial_present"] is False
    assert diagnostics["tool_denial_source"] is None
    assert diagnostics["tool_denial_evidence"] is None


def test_review_status_diagnostics_ignores_tool_denial_in_stderr_diff_transcript():
    output = (
        "The supplied diff has no actionable findings.\n"
        "REVIEW_STATUS: clear\n\n"
        "[stderr]\n"
        "\x1b[0m$ git diff main...HEAD tests/test_cli_review_helpers.py\n"
        '+        "Error executing tool run_shell_command: Tool execution denied by policy.\\n"\n'
        'tests/test_cli_review_helpers.py:4040:+        "Tool execution denied by policy.\\n"\n'
    )

    diagnostics = review_status_diagnostics(output, harness="opencode")

    assert diagnostics["status"] == "clear"
    assert diagnostics["stderr_present"] is True
    assert diagnostics["tool_denial_present"] is False
    assert diagnostics["tool_denial_evidence"] is None


def test_status_debug_detail_names_codex_bullets_for_prompted_harnesses():
    diagnostics = review_status_diagnostics(
        "## Findings\n\n1. Fix the issue.\nREVIEW_STATUS: findings\n",
        harness="opencode",
    )

    detail = review_impl._status_debug_detail(diagnostics)

    assert "status=findings" in detail
    assert "explicit=findings" in detail
    assert "codex_bullets=0" in detail
    assert "findings=0" not in detail


def test_run_loop_treats_structured_empty_findings_review_as_clear(tmp_path):
    calls = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        if args[1] == "review":
            return CommandResult(
                list(args),
                0,
                stdout='{"findings": [], "overall_correctness": "patch is correct"}\n',
            )
        raise AssertionError(f"unexpected command: {args}")

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
    assert [call[0][1] for call in calls] == ["review"]
    assert not (tmp_path / "artifacts" / "remediation-1.txt").exists()


def test_run_loop_writes_replayable_events_jsonl(tmp_path, capsys):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(
                list(args),
                0,
                stdout='{"findings": [], "overall_correctness": "patch is correct"}\n',
            )
        raise AssertionError(f"unexpected command: {args}")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()
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
    assert [
        event.payload.get("kind") for event in records if event.kind == "artifact_write"
    ] == [
        "summary",
        "reviews",
    ]
    assert capsys.readouterr().out == (
        "0001|review|1|phase_start: codex review · sandbox read-only · source=direct-config\n"
        "0002|review|1|phase_result: clear\n"
        f"0003|artifacts|artifact_write: {tmp_path / 'artifacts' / 'summary.json'}\n"
        f"0004|artifacts|artifact_write: {tmp_path / 'artifacts' / 'review-1.txt'}\n"
        "0005|summary|summary: review_clear\n"
    )


def test_progress_warning_status_emits_warning_event(tmp_path):
    sink = events.InMemorySink("run-1")
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=False,
    )
    ctx = RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=None,
        **phase_harness_kwargs(),
        event_sink=sink,
    )

    progress_event(
        config, "triage", "1", "warning", "suppressions unavailable", ctx=ctx
    )

    assert sink.events[0].kind == "warning"
    assert sink.events[0].payload["message"] == "suppressions unavailable"


def test_detect_review_status_does_not_treat_scoped_clear_prose_as_clear_when_issue_follows():
    assert (
        detect_review_status(
            "I did not find any issue in the docs, but there is a bug in the CLI."
        )
        == "unknown"
    )
    assert (
        detect_review_status(
            "I did not find any issue in the docs; however, there is a bug in the CLI."
        )
        == "unknown"
    )
    assert (
        detect_review_status(
            "I did not find any discrete issue in the docs.\n\n"
            "However, there is a bug in the parser."
        )
        == "unknown"
    )
    assert (
        detect_review_status(
            "I did not find any actionable bugs.\n\n"
            "No validation prevents this regression."
        )
        == "unknown"
    )
    assert (
        detect_review_status(
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

    assert detect_review_status(output) == "clear"


def test_detect_review_status_recognizes_codex_review_findings():
    output = """The patch has a bug.

Full review comments:

- [P2] Count filtered summaries after filtering — src/example.py:10-12
  This reports misleading data.
"""
    assert detect_review_status(output) == "findings"


def test_review_status_diagnostics_explain_clear_with_stderr_noise():
    output = (
        "The changes add the alias and tests without any clear regressions or actionable bugs.\n\n"
        "[stderr]\n"
        "review comments:\n- [P2] stale transcript example\n"
    )

    diagnostics = review_status_diagnostics(output)

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
    assert extract_finding_summaries(output, limit=2) == [
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
    assert extract_finding_blocks(output, limit=2, detail_lines=2) == [
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
        extract_review_summary(output)
        == "The loop can omit the only review transcript path in a failure summary."
    )


def test_review_model_is_top_level_codex_option(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        model="gpt-test",
    )

    command = review_impl.build_review_command(config)

    assert command[:5] == ["codex", "--model", "gpt-test", "review", "--base"]
    assert command == ["codex", "--model", "gpt-test", "review", "--base", "main"]


def test_non_codex_review_receives_explicit_review_prompt(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
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
        "plan",
        "--model",
        "sonnet",
    ]
    assert calls[0][1] is not None
    assert "Review the current repository changes" in calls[0][1]
    assert "Treat the working tree as read-only" in calls[0][1]
    assert "git diff <base>...HEAD" in calls[0][1]
    assert "Base branch: main" in calls[0][1]
    assert f"Working directory: {tmp_path}" in calls[0][1]
    assert "REVIEW_STATUS: findings" in calls[0][1]
    assert "REVIEW_STATUS: clear" in calls[0][1]


def test_opencode_review_prompt_is_attached_as_file(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )

    runner_mod.run_loop(config, runner)

    assert calls[0][0][:4] == [
        "opencode",
        "run",
        "--model",
        "provider/model",
    ]
    assert "--dangerously-skip-permissions" not in calls[0][0]
    assert calls[0][1] is None
    assert "--file" in calls[0][0]
    file_index = calls[0][0].index("--file")
    assert calls[0][0][file_index - 1] == "Follow the attached RevRem prompt exactly."
    prompt_path = Path(calls[0][0][file_index + 1])
    assert prompt_path.name == "review-1-prompt.txt"
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "Review the current repository changes" in prompt


def test_opencode_review_failure_names_opencode_harness(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(list(args), 1, stderr="Error: provider failed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )

    with pytest.raises(RuntimeError, match="opencode review failed for review-1"):
        runner_mod.run_loop(config, runner)


def test_opencode_review_retries_once_on_transient_provider_failure(tmp_path):
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if len(calls) == 1:
            return CommandResult(
                list(args),
                1,
                stderr=(
                    "Error: {"
                    '"name":"UnknownError",'
                    '"data":{"message":"Unexpected server error","ref":"err_3151eb39"}'
                    "}\n"
                ),
            )
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "clear"
    assert len(calls) == 2
    attempt_artifact = tmp_path / "artifacts" / "review-1-attempt-1.txt"
    assert "err_3151eb39" in attempt_artifact.read_text(encoding="utf-8")


def test_opencode_review_does_not_retry_provider_cli_contract_error(tmp_path):
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        return CommandResult(
            list(args),
            1,
            stderr="Error: File not found: Follow the attached RevRem prompt exactly.\n",
        )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )

    with pytest.raises(RuntimeError, match="provider CLI contract error"):
        runner_mod.run_loop(config, runner)
    assert len(calls) == 1


def test_gemini_review_runs_in_plan_mode_with_prompt_via_prompt_arg(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="gemini",
        review_model="gemini-3.1-pro-preview",
    )

    runner_mod.run_loop(config, runner)

    assert calls[0][0][:5] == [
        "gemini",
        "--approval-mode",
        "plan",
        "--model",
        "gemini-3.1-pro-preview",
    ]
    prompt = calls[0][0][calls[0][0].index("--prompt") + 1]
    assert calls[0][1] is None
    assert "Treat the working tree as read-only" in prompt
    assert "Base branch: main" in prompt


def test_gemini_review_prompt_includes_revrem_diff_context(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True
    )
    (repo / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-am", "change value"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=repo,
        artifact_dir=repo / "artifacts",
        review_harness="gemini",
        review_model="gemini-3.1-pro-preview",
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    prompt = calls[0][0][calls[0][0].index("--prompt") + 1]
    assert calls[0][1] is None
    context = (repo / "artifacts" / "review-1-context.txt").read_text(encoding="utf-8")
    artifact_paths = summary["artifact_paths"]
    assert "Use the supplied diff context as the authoritative patch input" in prompt
    assert "git diff --stat main...HEAD" in prompt
    assert "git diff main...HEAD" in prompt
    assert "+VALUE = 2" in prompt
    assert context in prompt
    assert (repo / "artifacts" / "review-1-prompt.txt").is_file()
    assert artifact_paths["reviews"] == [str(repo / "artifacts" / "review-1.txt")]
    assert str(repo / "artifacts" / "review-1-prompt.txt") in artifact_paths["prompts"]
    assert (
        str(repo / "artifacts" / "review-1-context.txt") in artifact_paths["contexts"]
    )


def test_gemini_review_prompt_respects_configured_char_limit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "sample.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True
    )
    (repo / "sample.txt").write_text("change\n" + ("x" * 5000) + "\n", encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-am", "large change"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=repo,
        artifact_dir=repo / "artifacts",
        review_harness="gemini",
        review_model="gemini-3.1-pro-preview",
        external_review_input_chars=1500,
    )

    runner_mod.run_loop(config, runner)

    prompt = calls[0][0][calls[0][0].index("--prompt") + 1]
    assert calls[0][1] is None
    assert len(prompt) <= 1500
    assert "omitted" in prompt
    context = (repo / "artifacts" / "review-1-context.txt").read_text(encoding="utf-8")
    assert "x" * 1000 in context
    assert context not in prompt
    phase_start = next(
        json.loads(line)
        for line in (repo / "artifacts" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if json.loads(line)["kind"] == "phase_start"
    )
    assert phase_start["payload"]["review_context_chars"] > 1500
    assert phase_start["payload"]["external_review_input_chars"] == 1500
    assert phase_start["payload"]["prompt_truncated"] is True
    assert phase_start["payload"]["prompt_delivery"] == "argv-prompt"
    assert phase_start["payload"]["prompt_chars"] == len(prompt)
    assert (
        phase_start["payload"]["command"][
            phase_start["payload"]["command"].index("--prompt") + 1
        ]
        == f"<prompt chars={len(prompt)}>"
    )
    assert prompt not in json.dumps(phase_start["payload"]["command"])


def test_external_review_prompt_ignores_remediation_input_cap(tmp_path):
    calls: list[tuple[list[str], str | None]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append((list(args), input_text))
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
        max_remediation_input_chars=200,
        external_review_input_chars=1200,
    )

    runner_mod.run_loop(config, runner)

    assert calls[0][1] is None
    prompt_path = Path(calls[0][0][calls[0][0].index("--file") + 1])
    prompt = prompt_path.read_text(encoding="utf-8")
    assert len(prompt) > 200
    assert len(prompt) <= 1200


def test_external_review_waiting_progress_warns_after_quiet_threshold(tmp_path):
    sink = events.InMemorySink("run1")
    config = LoopConfig(
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="gemini",
        external_review_warning_seconds=10,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        reporter = waiting_progress.current_reporter()
        assert reporter is not None
        reporter(5)
        reporter(10)
        return CommandResult(list(args), 0, stdout="done\n")

    result = run_with_waiting_progress(
        config,
        runner,
        ["gemini"],
        tmp_path,
        "prompt",
        None,
        phase="review",
        label="1",
        ctx=RunContext(
            runner=runner,
            clock=FakeClock(),
            identity=FakeRunIdentity(),
            event_sink=sink,
            **phase_harness_kwargs(),
        ),
        prompt_artifact=tmp_path / "artifacts" / "review-1-prompt.txt",
    )

    assert result.returncode == 0
    waiting_events = [
        event for event in sink.events if event.payload.get("summary") == "waiting"
    ]
    assert waiting_events[0].payload.get("quiet_warning") is None
    assert waiting_events[1].payload["quiet_warning"] is True
    assert "no provider output is available until the process exits" in str(
        waiting_events[1].payload["message"]
    )


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
    captured: list[LoopConfig] = []

    def fake_run_loop(config, **_kwargs):
        captured.append(config)
        return application.ReviewLoopResult(
            summary={"final_status": "clear", "stopped_reason": "review_clear"},
            outcome=OutcomeClear(reason="review_clear"),
        )

    monkeypatch.setattr(application, "run_review_loop", fake_run_loop)

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
    assert review_impl.build_review_command(captured[0])[0] == "/tmp/claude-dev"


def test_model_overrides_and_reasoning_effort_are_passed_to_codex(tmp_path):
    config = LoopConfig(
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

    review_command = review_impl.build_review_command(config)
    remediation_command = remediation_impl.build_remediation_command(config)

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
    assert (
        remediation_command[remediation_command.index("--model") + 1] == "gpt-5.4-mini"
    )


def test_remediation_command_uses_deterministic_output_options(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        exec_json=True,
    )

    command = remediation_impl.build_remediation_command(
        config, tmp_path / "last-message.txt"
    )

    assert "--color" in command
    assert command[command.index("--color") + 1] == "never"
    assert "--json" in command
    assert "--output-last-message" in command
    assert command[-1] == "-"


def test_triage_command_uses_read_only_exec_with_phase_model(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_model="gpt-5.4-mini",
        triage_reasoning_effort="low",
    )

    command = triage_impl.build_triage_command(config)

    assert command[:4] == ["codex", "exec", "-c", 'model_reasoning_effort="low"']
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-5.4-mini"
    assert "--full-auto" not in command
    assert command[-1] == "-"


def test_commit_message_command_uses_read_only_exec_with_configured_model(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-5.3-codex-spark",
        commit_reasoning_effort="minimal",
    )

    command = build_commit_message_command(config)

    assert command == [
        "codex",
        "exec",
        "-c",
        'model_reasoning_effort="minimal"',
        "-c",
        'web_search="disabled"',
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--model",
        "gpt-5.3-codex-spark",
        "-",
    ]


def test_remediation_command_does_not_disable_web_search(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        remediation_reasoning_effort="minimal",
    )

    command = remediation_impl.build_remediation_command(config)

    assert 'web_search="disabled"' not in command


def test_sanitize_commit_message_extracts_subject_without_meta_prose():
    assert (
        sanitize_commit_message(
            'Commit message: "Harden RevRem commit flow"\n\nExplanation...',
            fallback="fallback",
        )
        == "chore: Harden RevRem commit flow (RevRem)"
    )
    assert (
        sanitize_commit_message(
            "fix(cli): stop on no-op remediation", fallback="fallback"
        )
        == "fix(cli): stop on no-op remediation (RevRem)"
    )
    assert (
        sanitize_commit_message("", fallback="fallback") == "chore: fallback (RevRem)"
    )
    assert (
        sanitize_commit_message(
            "Looking at the staged changes and review findings, I need to write a concise "
            "Conventional Commit subject.\n"
            "\n"
            "The main changes include:\n"
            "- improved OpenCode integration\n"
            "\n"
            "Commit subject: fix(review): harden provider diagnostics\n",
            fallback="fallback",
        )
        == "fix(review): harden provider diagnostics (RevRem)"
    )
    assert (
        sanitize_commit_message(
            "Looking at the staged changes and review findings, I need to write a concise "
            "Conventional Commit subject.\n"
            "The main changes include:\n"
            "- improved OpenCode integration\n",
            fallback="fallback",
        )
        == "chore: fallback (RevRem)"
    )
    assert (
        sanitize_commit_message(
            "Use custom format",
            fallback="fallback",
            enforce_revrem_conventional=False,
        )
        == "Use custom format"
    )


def test_default_commit_message_prompt_rejects_meta_prose():
    assert "Output exactly one line" in DEFAULT_COMMIT_MESSAGE_PROMPT
    assert "Do not explain your reasoning" in DEFAULT_COMMIT_MESSAGE_PROMPT
    assert "fix(cli): stop after no-op remediation (RevRem)" in DEFAULT_COMMIT_MESSAGE_PROMPT
    assert "Looking at the staged changes" in DEFAULT_COMMIT_MESSAGE_PROMPT


def test_commit_message_for_staged_changes_respects_profile_prompt_override(tmp_path):
    config = LoopConfig(
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
            return CommandResult(list(args), 0, stdout=" file.py | 2 +-\n")
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(list(args), 0, stdout="file.py\n")
        if args[:2] == ["codex", "exec"]:
            return CommandResult(list(args), 0, stdout="Use custom format\n")
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 1, make_run_context(runner)
    )

    assert message == "Use custom format"
    assert "Write a custom subject." in next(
        prompt for args, prompt in calls if args[:2] == ["codex", "exec"]
    )


def test_commit_message_for_staged_changes_uses_specific_fallback_on_model_failure(
    tmp_path,
):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-test-commit",
        timeout_seconds=30,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/foo.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(list(args), 0, stdout="src/code_review_loop/foo.py\n")
        if args[:2] == ["codex", "exec"]:
            return CommandResult(list(args), 1, stderr="model unavailable\n")
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 2, make_run_context(runner)
    )

    assert_professional_fallback_subject(
        message,
        expected_type="chore",
        expected_scope="foo",
        expected_terms=("foo",),
    )
    assert (tmp_path / "artifacts" / "commit-2-message-fallback.json").is_file()


def test_commit_message_for_staged_changes_parses_conventional_subject_from_model_output(
    tmp_path,
):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-test-commit",
        timeout_seconds=30,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/review.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(
                list(args), 0, stdout="src/code_review_loop/review.py\n"
            )
        if args[:2] == ["codex", "exec"]:
            return CommandResult(
                list(args),
                0,
                stdout=(
                    "Looking at the staged changes, I need to write a concise subject.\n"
                    "fix(review): harden provider diagnostics (RevRem)\n"
                ),
            )
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 8, make_run_context(runner)
    )

    assert message == "fix(review): harden provider diagnostics (RevRem)"


def test_commit_message_for_staged_changes_falls_back_on_invalid_model_prose(
    tmp_path,
):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-test-commit",
        timeout_seconds=30,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/review.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(
                list(args), 0, stdout="src/code_review_loop/review.py\n"
            )
        if args[:2] == ["codex", "exec"]:
            return CommandResult(
                list(args),
                0,
                stdout=(
                    "Looking at the staged changes, I need to write a concise subject.\n"
                    "The main changes include:\n"
                    "- provider diagnostics\n"
                ),
            )
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 9, make_run_context(runner)
    )
    fallback_path = tmp_path / "artifacts" / "commit-9-message-fallback.json"
    fallback = json.loads(fallback_path.read_text(encoding="utf-8"))

    assert_professional_fallback_subject(
        message,
        expected_type="chore",
        expected_scope="review",
        expected_terms=("review",),
    )
    assert fallback["reason"] == "model_drafting_invalid"
    assert "Looking at" not in message
    assert "The main changes include" not in message


def test_commit_message_for_staged_changes_removes_created_side_effect_file(
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-test-commit",
        timeout_seconds=30,
    )
    status_outputs = iter(["", "?? commit-subject.txt\n"])

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/review.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(
                list(args), 0, stdout="src/code_review_loop/review.py\n"
            )
        if args == ["git", "rev-parse", "HEAD"]:
            return CommandResult(list(args), 0, stdout="same-head\n")
        if args == ["git", "diff", "--cached", "--raw"]:
            return CommandResult(
                list(args), 0, stdout=":100644 100644 old new M\tsrc/code_review_loop/review.py\n"
            )
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout=next(status_outputs))
        if args[:2] == ["codex", "exec"]:
            (tmp_path / "commit-subject.txt").write_text(
                "fix(review): harden provider diagnostics (RevRem)",
                encoding="utf-8",
            )
            return CommandResult(
                list(args),
                0,
                stdout="I wrote commit-subject.txt with the subject.\n",
            )
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 9, make_run_context(runner)
    )
    side_effect_path = tmp_path / "artifacts" / "commit-9-message-side-effects.json"
    side_effects = json.loads(side_effect_path.read_text(encoding="utf-8"))

    assert not (tmp_path / "commit-subject.txt").exists()
    assert_professional_fallback_subject(
        message,
        expected_type="chore",
        expected_scope="review",
        expected_terms=("review",),
    )
    assert side_effects["created_paths_removed"] == ["commit-subject.txt"]
    assert side_effects["unsafe_status_lines"] == []
    assert json.loads(
        (tmp_path / "artifacts" / "commit-9-message-fallback.json").read_text(
            encoding="utf-8"
        )
    )["reason"] == "model_drafting_side_effects"


def test_commit_message_for_staged_changes_aborts_on_tracked_side_effect(
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-test-commit",
        timeout_seconds=30,
    )
    status_outputs = iter(["", " M src/code_review_loop/review.py\n"])

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/review.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(
                list(args), 0, stdout="src/code_review_loop/review.py\n"
            )
        if args == ["git", "rev-parse", "HEAD"]:
            return CommandResult(list(args), 0, stdout="same-head\n")
        if args == ["git", "diff", "--cached", "--raw"]:
            return CommandResult(
                list(args), 0, stdout=":100644 100644 old new M\tsrc/code_review_loop/review.py\n"
            )
        if args[:4] == ["git", "status", "--porcelain=v1", "--untracked-files=all"]:
            return CommandResult(list(args), 0, stdout=next(status_outputs))
        if args[:2] == ["codex", "exec"]:
            return CommandResult(
                list(args),
                0,
                stdout="fix(review): harden provider diagnostics (RevRem)\n",
            )
        raise AssertionError(f"unexpected command: {args!r}")

    with pytest.raises(RuntimeError, match="commit-message drafting modified"):
        commit_message_for_staged_changes(config, runner, 9, make_run_context(runner))

    side_effects = json.loads(
        (tmp_path / "artifacts" / "commit-9-message-side-effects.json").read_text(
            encoding="utf-8"
        )
    )
    assert side_effects["created_paths_removed"] == []
    assert side_effects["unsafe_status_lines"] == [" M src/code_review_loop/review.py"]


def test_commit_message_fallback_uses_review_context_for_feature_type(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "review-3.txt").write_text(
        "Add a CLI flag to enable triage from the command line.\n",
        encoding="utf-8",
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=artifact_dir,
        commit_message_model="gpt-test-commit",
        timeout_seconds=30,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/cli/args.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(
                list(args), 0, stdout="src/code_review_loop/cli/args.py\n"
            )
        if args[:2] == ["codex", "exec"]:
            return CommandResult(list(args), 1, stderr="model unavailable\n")
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 3, make_run_context(runner)
    )

    assert_professional_fallback_subject(
        message,
        expected_type="feat",
        expected_scope="cli",
        expected_terms=("cli", "flag", "triage"),
    )


def test_commit_message_fallback_uses_remediation_context_for_refactor_type(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "remediation-4-last-message.txt").write_text(
        "Refactor the runner setup into a cohesive helper module.\n",
        encoding="utf-8",
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=artifact_dir,
        commit_message_model=None,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/runner_setup.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(
                list(args), 0, stdout="src/code_review_loop/runner_setup.py\n"
            )
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 4, make_run_context(runner)
    )

    assert_professional_fallback_subject(
        message,
        expected_type="refactor",
        expected_scope="runner-setup",
        expected_terms=("runner", "setup"),
    )


def test_commit_message_fallback_ranks_bugfix_context_above_feature_words(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "review-5.txt").write_text(
        "Fix a regression when profiles add support for draft routes.\n",
        encoding="utf-8",
    )
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=artifact_dir,
        commit_message_model=None,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(
                list(args), 0, stdout=" src/code_review_loop/profiles.py | 2 +-\n"
            )
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(
                list(args), 0, stdout="src/code_review_loop/profiles.py\n"
            )
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 5, make_run_context(runner)
    )

    assert_professional_fallback_subject(
        message,
        expected_type="fix",
        expected_scope="profiles",
        expected_terms=("regression", "profiles"),
    )


def test_commit_message_effort_adjustment_emits_operator_event(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model="gpt-test-commit",
        commit_reasoning_effort="low",
        commit_reasoning_effort_requested="minimal",
        commit_reasoning_effort_adjustment="codex_minimal_unsupported_by_model",
    )
    sink = events.InMemorySink("run1")

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(list(args), 0, stdout=" src/pkg/widget.py | 2 +-\n")
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(list(args), 0, stdout="src/pkg/widget.py\n")
        if args[:2] == ["codex", "exec"]:
            return CommandResult(list(args), 1, stderr="model unavailable\n")
        raise AssertionError(f"unexpected command: {args!r}")

    commit_message_for_staged_changes(
        config,
        runner,
        7,
        RunContext(
            runner=runner,
            clock=FakeClock(),
            identity=FakeRunIdentity(),
            event_sink=sink,
            **phase_harness_kwargs(),
        ),
    )

    adjustment_events = [
        event
        for event in sink.events
        if event.phase == "commit-message"
        and event.payload.get("summary") == "config-adjusted"
    ]
    assert adjustment_events
    assert "minimal->low" in adjustment_events[0].payload["message"]


def test_commit_message_fallback_defaults_neutral_context_to_chore(tmp_path):
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        commit_message_model=None,
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:4] == ["git", "diff", "--cached", "--stat"]:
            return CommandResult(list(args), 0, stdout=" package/widget.py | 2 +-\n")
        if args[:4] == ["git", "diff", "--cached", "--name-only"]:
            return CommandResult(list(args), 0, stdout="package/widget.py\n")
        raise AssertionError(f"unexpected command: {args!r}")

    message = commit_message_for_staged_changes(
        config, runner, 6, make_run_context(runner)
    )

    assert_professional_fallback_subject(
        message,
        expected_type="chore",
        expected_scope="package",
        expected_terms=("widget",),
    )


def test_deterministic_commit_message_avoids_overeager_fix_for_generic_corrections():
    message = deterministic_commit_message(
        staged_paths=["package/widget.py"],
        context="Correct local wording in the widget helper.",
    )

    assert_professional_fallback_subject(
        message,
        expected_type="chore",
        expected_scope="package",
        expected_terms=("correct", "widget"),
    )


def test_deterministic_commit_message_strips_redundant_type_verbs():
    cases = [
        (
            deterministic_commit_message(
                staged_paths=["src/code_review_loop/runner_shell.py"],
                context="Preserve latest excerpt for unresolved final reviews.",
            ),
            "fix",
            ("latest", "excerpt"),
        ),
        (
            deterministic_commit_message(
                staged_paths=["src/foo/subprocess_runner.py"],
                context="Extract duplicated subprocess runner helpers.",
            ),
            "refactor",
            ("duplicated", "subprocess"),
        ),
        (
            deterministic_commit_message(
                staged_paths=["tests/test_profiles.py"],
                context="Add coverage for escalation precedence.",
            ),
            "test",
            ("escalation", "precedence"),
        ),
        (
            deterministic_commit_message(
                staged_paths=["docs/70-devex/devex-001-using-code-review-loop.md"],
                context="New triage controls for operators.",
            ),
            "docs",
            ("triage", "controls"),
        ),
        (
            deterministic_commit_message(
                staged_paths=["a/cache.py"],
                context="Performance cache repeated rev-parse calls.",
            ),
            "perf",
            ("cache", "repeated"),
        ),
    ]

    for message, expected_type, expected_terms in cases:
        assert message.startswith(f"{expected_type}")
        assert message.endswith(" (RevRem)")
        lowered = message.lower()
        assert re.search(r"^(\w+)(?:\([^)]*\))?: \1\b", lowered) is None
        assert re.search(r"^(\w+)\(\1s?\):", lowered) is None
        for term in expected_terms:
            assert term in lowered


def test_deterministic_commit_message_strips_trigger_words_anywhere_and_dedupes_terms():
    cases = [
        (
            deterministic_commit_message(
                staged_paths=["src/code_review_loop/cli/args.py"],
                context="Add a CLI flag to enable triage in triage runs.",
            ),
            "feat(cli): cli flag triage runs",
            {"add", "enable"},
        ),
        (
            deterministic_commit_message(
                staged_paths=["src/code_review_loop/runner_shell.py"],
                context="Fix preserve latest review excerpt for unresolved final reviews.",
            ),
            "fix(runner-shell): latest excerpt unresolved final",
            {"fix", "preserve"},
        ),
        (
            deterministic_commit_message(
                staged_paths=["src/foo/subprocess_runner.py"],
                context="Refactor extract duplicated subprocess runner helpers.",
            ),
            "refactor(foo): duplicated subprocess runner helpers",
            {"refactor", "extract"},
        ),
        (
            deterministic_commit_message(
                staged_paths=["tests/test_profiles.py"],
                context="Cover add coverage for escalation precedence.",
            ),
            "test: escalation precedence",
            {"cover", "add", "coverage"},
        ),
    ]

    for message, expected_prefix, forbidden_terms in cases:
        assert message.startswith(expected_prefix)
        summary_terms = commit_subject_summary(message).split()
        assert len(summary_terms) == len(set(summary_terms))
        assert not (set(summary_terms) & forbidden_terms)


def test_deterministic_commit_message_suppresses_filename_scopes():
    assert deterministic_commit_message(
        staged_paths=["README.md"],
        context="Document installation steps.",
    ).startswith("docs: ")
    assert deterministic_commit_message(
        staged_paths=["x.txt"],
        context="Refresh local fixture.",
    ).startswith("chore: ")


def test_deterministic_commit_message_uses_src_subpackage_scope():
    cases = [
        ("src/code_review_loop/cli/args.py", "feat(cli):"),
        ("src/code_review_loop/adapters/commit.py", "fix(adapters):"),
        ("src/code_review_loop/core/engine.py", "refactor(core):"),
        ("src/code_review_loop/policy.py", "fix(policy):"),
    ]

    for path, prefix in cases:
        message = deterministic_commit_message(
            staged_paths=[path],
            context="Fix preserve route handling.",
        )
        if prefix.startswith("feat"):
            message = deterministic_commit_message(
                staged_paths=[path],
                context="Add route handling.",
            )
        elif prefix.startswith("refactor"):
            message = deterministic_commit_message(
                staged_paths=[path],
                context="Extract route handling.",
            )
        assert message.startswith(prefix)


def test_deterministic_commit_message_caps_fallback_subject_length():
    message = deterministic_commit_message(
        staged_paths=["src/code_review_loop/adapters/commit.py"],
        context=(
            "Fix extremely verbose deterministic fallback commit message "
            "construction for routed remediation evidence artifacts."
        ),
    )

    assert len(message) <= 72
    assert message.endswith(" (RevRem)")
    assert re.match(r"^fix\(adapters\): [a-z0-9 -]+ \(RevRem\)$", message)
    assert not message.removesuffix(" (RevRem)").endswith(("-", ",", ":", ";", "."))


def test_normalize_revrem_conventional_subject_preserves_suffix_when_truncated():
    subject = "fix(cli): " + "x" * 200

    normalized = normalize_revrem_conventional_subject(subject)

    assert normalized.endswith(" (RevRem)")
    assert len(normalized) == 120
    assert normalized.startswith("fix(cli): ")


def test_detect_review_status_requires_explicit_status_line():
    """Fuzzy patterns must not flip ambiguous output to clear."""
    assert (
        detect_review_status("no findings about style, but several about logic")
        == "unknown"
    )
    assert (
        detect_review_status("review is clear of syntax errors but not semantic")
        == "unknown"
    )
    assert detect_review_status("") == "unknown"


def test_review_failure_detection_allows_nonzero_findings_without_stderr():
    assert (
        review_failed_to_run(
            CommandResult(["codex", "review"], -9, stdout="", stderr=""), "codex"
        )
        is True
    )
    assert (
        review_failed_to_run(
            CommandResult(["codex", "review"], 1, stdout="Finding\n", stderr=""),
            "codex",
        )
        is False
    )
    assert (
        review_failed_to_run(
            CommandResult(
                ["codex", "review"], 1, stdout="", stderr="Error: thread/start failed"
            ),
            "codex",
        )
        is True
    )
    assert (
        review_failed_to_run(
            CommandResult(["codex", "review"], 2, stdout="", stderr="error: bad args"),
            "codex",
        )
        is True
    )


def run_git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_actionable_review_output_drops_verbose_stderr_transcript():
    output = "Full review comments:\n\n- [P1] Fix the bug\n\n[stderr]\n" + (
        "diff --git a/x b/x\n" * 100
    )

    assert (
        actionable_review_output(output)
        == "Full review comments:\n\n- [P1] Fix the bug"
    )


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
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        return CommandResult(list(args), 0, stdout="fixed\n")

    config = LoopConfig(
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
