"""Opt-in account-access checks: REVREM_LIVE_CURRENT_MODELS=1 pytest -q this_file."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from code_review_loop.harnesses import PhaseCommandRequest, build_phase_command

pytestmark = pytest.mark.skipif(
    os.environ.get("REVREM_LIVE_CURRENT_MODELS") != "1",
    reason="set REVREM_LIVE_CURRENT_MODELS=1 for bounded, credential-gated model probes",
)


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"])
def test_current_model_executes_through_codex_adapter(tmp_path, model):
    codex = shutil.which("codex")
    assert codex is not None, "Install and authenticate Codex before running live probes"
    command = build_phase_command(PhaseCommandRequest(
        harness="codex", role="commit-message", executable=codex, cwd=tmp_path,
        model=model, reasoning_effort="low", sandbox="read-only",
    ))
    # Keep account auth, but avoid local plugins, instructions and persistent sessions.
    command[2:2] = ["--ignore-user-config", "--ephemeral", "--skip-git-repo-check"]
    result = subprocess.run(
        command, cwd=tmp_path, input="Reply exactly REVREM_MODEL_OK. Do not call tools.",
        text=True, capture_output=True, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "REVREM_MODEL_OK"
