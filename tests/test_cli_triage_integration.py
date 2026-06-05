from __future__ import annotations

import json
from pathlib import Path

import pytest

import tests.support.application_runner as runner_mod
from code_review_loop import suppressions
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.runtime import RunLoopFailed


def make_git_worktree(tmp_path: Path, cwd_rel: str | None = "work") -> tuple[Path, Path]:
    (tmp_path / ".git").mkdir(exist_ok=True)
    cwd = tmp_path if cwd_rel is None else tmp_path / cwd_rel
    cwd.mkdir(parents=True, exist_ok=True)
    return tmp_path, cwd


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
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(list(args), 0, stdout="Confirmed: fix profile merge first.\n")
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
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

    summary = runner_mod.run_loop(config, runner).to_dict()

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
            return CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

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
            return CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        raise AssertionError(f"remediation/check should not run after suppression: {args!r}")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

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
            return CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    triage_json = json.loads((tmp_path / "artifacts" / "triage-1.json").read_text(encoding="utf-8"))
    assert triage_json["confirmed_findings"] == []
    assert triage_json["needs_more_info"][0]["fingerprint"] == "f2:def456"
    assert triage_json["suppressed_findings"][0]["fingerprint"] == "f1:abc123"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert summary["final_status"] == "unknown"
    assert "Structured triage handoff" in (calls[2][1] or "")
    assert len(calls) == 4


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
            return CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(list(args), 0, stdout=json.dumps(triage_payload))
        raise AssertionError(f"remediation/check should not run after rejected-only triage: {args!r}")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

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
            return CommandResult(list(args), 0, stdout=next(review_outputs))
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(list(args), 0, stdout=json.dumps(next(triage_outputs)))
        if args[0] == "pytest":
            check_attempts += 1
            if check_attempts == 1:
                return CommandResult(list(args), 1, stdout="FAILED\n")
            return CommandResult(list(args), 0, stdout="passed\n")
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=2,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
        check_commands=("pytest -q",),
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert summary["pending_check_failures"] is False
    assert len(calls) == 10
    assert "Check failures from the previous iteration:" in (calls[7][1] or "")
    assert "Structured triage handoff" not in (calls[7][1] or "")

def test_loop_invalid_structured_triage_continues_with_original_review(tmp_path):
    calls = []
    triage_attempts = 0

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        nonlocal triage_attempts
        calls.append((list(args), input_text, timeout_seconds))
        if args[1] == "review":
            return CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            triage_attempts += 1
            return CommandResult(list(args), 0, stdout='{"confirmed_findings": []')
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
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
            return CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(
                list(args),
                -1,
                stderr="Command timed out after 1 second\n",
            )
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        triage_timeout_seconds=1,
        final_review=False,
    )

    with pytest.raises(RunLoopFailed):
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
            return CommandResult(
                list(args),
                0,
                stdout="Full review comments:\n\n- [P2] Fix profile merge\n",
            )
        if "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only":
            return CommandResult(
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
            return CommandResult(list(args), 0, stdout="remediated\n")
        if args[:3] == ["git", "add", "-A"]:
            return CommandResult(list(args), 0)
        if args[:3] == ["git", "diff", "--cached"] and "--quiet" in args:
            return CommandResult(list(args), 1)
        if args[:3] == ["git", "diff", "--cached"] and "--stat" in args:
            return CommandResult(list(args), 0, stdout=" src/code.py | 1 +\n")
        if args[:3] == ["git", "diff", "--cached"] and "--name-only" in args:
            return CommandResult(list(args), 0, stdout="src/code.py\n")
        if args[:3] == ["git", "commit", "-m"]:
            return CommandResult(list(args), 0, stdout="[branch abc] fix(cli): harden RevRem commit flow\n")
        return CommandResult(list(args), 0, stdout="passed\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=cwd,
        artifact_dir=tmp_path / "artifacts",
        triage_enabled=True,
        final_review=False,
        check_commands=(),
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    assert summary["final_status"] == "unknown"
    assert summary["stopped_reason"] == "max_iterations_reached"
    assert run_count == 1
    assert remediation_inputs and "Structured triage handoff" in remediation_inputs[0]
    assert "Fix profile merge" in remediation_inputs[0]
    assert len([call for call in calls if "--sandbox" in call[0]]) == 2


def test_loop_writes_failure_summary_when_triage_fails(tmp_path):
    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[1] == "review":
            return CommandResult(list(args), 0, stdout="Full review comments:\n\n- [P2] Fix profile merge\n")
        return CommandResult(list(args), 1, stderr="Error: triage failed\n")

    config = LoopConfig(
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
            return CommandResult(list(args), 0, stdout="No findings.\n")
        return CommandResult(list(args), 0, stdout="remediated\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        debug_status_detection=True,
    )

    summary = runner_mod.run_loop(config, runner).to_dict()

    diagnostic_path = tmp_path / "artifacts" / "review-1-status.json"
    assert diagnostic_path.exists()
    assert summary["artifact_paths"]["diagnostics"] == [str(diagnostic_path)]
    assert summary["artifact_paths"]["reviews"] == [str(tmp_path / "artifacts" / "review-1.txt")]
