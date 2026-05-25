"""Git preflight gateway (REVREM-TASK-003 Wave C3a step 2).

Hosts ``run_git_preflight``, used by both the review preflight and the resume
precondition checks. Moved out of ``cli/__init__.py`` per the plan; the parent
module re-exports it so existing ``monkeypatch.setattr(MODULE,
"run_git_preflight", …)`` test sites keep working.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from code_review_loop import loop as _cli  # noqa: E402  -- loop-shell helpers
from code_review_loop.core.ports import CommandResult


def run_git_preflight(cwd: Path, args: Sequence[str]) -> CommandResult:
    command = ["git", *args]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command,
            -1,
            stdout=_cli._timeout_stream_text(exc.output),
            stderr=_cli._timeout_stream_text(exc.stderr),
        )
    return CommandResult(
        command,
        completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
