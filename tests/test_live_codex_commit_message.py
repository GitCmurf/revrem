from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from code_review_loop import harnesses
from code_review_loop.adapters import phase_support
from code_review_loop.adapters.subprocess_runner import default_runner
from code_review_loop.config import LoopConfig
from code_review_loop.core.review_interpretation import actionable_review_output

pytestmark = pytest.mark.skipif(
    os.environ.get("REVREM_LIVE_CODEX") != "1",
    reason="set REVREM_LIVE_CODEX=1 to run credential-gated Codex smoke tests",
)


def test_live_codex_commit_message_smoke():
    codex = shutil.which("codex")
    if codex is None:
        pytest.skip("codex executable is not on PATH")

    cwd = Path.cwd()
    config = LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin=codex,
        cwd=cwd,
        artifact_dir=cwd / ".revrem" / "live-smoke",
        commit_message_model=os.environ.get(
            "REVREM_LIVE_CODEX_COMMIT_MODEL",
            "gpt-5.3-codex-spark",
        ),
        commit_reasoning_effort="low",
        commit_reasoning_effort_requested="minimal",
        commit_reasoning_effort_adjustment="codex_minimal_unsupported_by_model",
        timeout_seconds=120,
        commit_timeout_seconds=120,
    )
    command, stdin = harnesses.prepare_prompt_invocation(
        "codex",
        phase_support.build_commit_message_command(config),
        "\n".join(
            [
                "Return one Conventional Commit subject ending with (RevRem).",
                "Files:",
                "src/code_review_loop/harnesses.py",
                "",
                "Stat:",
                " src/code_review_loop/harnesses.py | 2 +-",
                "",
                "Review/remediation context:",
                "Disable web search for the commit-message role.",
            ]
        ),
    )

    result = default_runner(command, cwd, stdin, timeout_seconds=120)
    output = phase_support._combined_output(result)
    assert result.returncode == 0, output

    subject = phase_support.sanitize_commit_message(
        actionable_review_output(output),
        fallback="chore(harnesses): disable web search (RevRem)",
    )
    assert re.match(r"^[a-z]+(?:\([a-z0-9-]+\))?: .+ \(RevRem\)$", subject)
    assert "http 400" not in output.lower()
    assert "unsupported value" not in output.lower()
