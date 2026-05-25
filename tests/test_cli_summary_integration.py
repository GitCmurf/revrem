from __future__ import annotations

import code_review_loop.runner as runner_mod


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
