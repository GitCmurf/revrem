"""Classification matrix for ``provider_failures.classify_provider_failure``.

Pins the full provider-failure classification surface (reason, transient flag)
and the retry/raise contract used by ``run_review_with_retry`` and
``RemediationAdapter``. Adding new ``ProviderFailure.reason`` values without
extending this table is a test-coverage regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_review_loop import provider_failures
from code_review_loop.adapters import review as review_impl
from code_review_loop.adapters.remediation import RemediationAdapter
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult, RemediationRequest, RunContext
from tests.support.fakes import FakeClock, FakeRunIdentity
from tests.support.phase_harnesses import phase_harness_kwargs


def _result(returncode: int, *, stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(["harness"], returncode, stdout=stdout, stderr=stderr)


@pytest.mark.parametrize(
    ("kwargs", "expected_reason", "expected_transient"),
    [
        # Non-retryable: provider refused to authenticate the caller.
        (
            {"returncode": 1, "stderr": "Error: authentication required; api key invalid"},
            "provider_auth_required",
            False,
        ),
        # Non-retryable: provider reports quota exhaustion (Gemini-style).
        (
            {
                "returncode": 1,
                "stderr": "TerminalQuotaError: code: 429 QUOTA_EXHAUSTED",
            },
            "provider_quota_exhausted",
            False,
        ),
        # Non-retryable: CLI contract error (File not found, bad option, ...).
        (
            {"returncode": 1, "stderr": "Error: File not found: missing.txt"},
            "provider_cli_contract_error",
            False,
        ),
        # Retryable: provider returns a transient server error envelope.
        (
            {
                "returncode": 1,
                "stderr": (
                    'Error: {"name":"UnknownError",'
                    '"data":{"message":"Unexpected server error",'
                    '"ref":"err_3151eb39"}}'
                ),
            },
            "provider_server_error",
            True,
        ),
        # Retryable: provider returns a transient transport error.
        (
            {
                "returncode": 1,
                "stderr": "Error: connection reset by peer (econnreset)",
            },
            "provider_transient_error",
            True,
        ),
        # Retryable: provider applies per-token rate limiting.
        (
            {"returncode": 1, "stderr": "Error: 429 rate limit exceeded"},
            "provider_rate_limited",
            True,
        ),
        # Retryable: subprocess was signalled (e.g. SIGTERM) before exit.
        (
            {"returncode": -15, "stderr": "Killed"},
            "provider_interrupted",
            True,
        ),
    ],
)
def test_classify_provider_failure_reason_and_transient(
    kwargs: dict[str, object],
    expected_reason: str,
    expected_transient: bool,
) -> None:
    result = _result(**kwargs)

    failure = provider_failures.classify_provider_failure(result, harness="harness")

    assert failure is not None
    assert failure.reason == expected_reason
    assert failure.transient is expected_transient


def test_classify_provider_failure_returns_none_for_success() -> None:
    assert (
        provider_failures.classify_provider_failure(
            _result(0, stdout="ok\n"), harness="harness"
        )
        is None
    )


def test_classify_provider_failure_returns_none_for_unrecognised_output() -> None:
    result = _result(1, stderr="some unrelated non-fatal log line")
    assert (
        provider_failures.classify_provider_failure(result, harness="harness") is None
    )


def test_review_failed_to_run_flags_provider_auth_required(tmp_path: Path) -> None:
    """``review_failed_to_run`` must use the harness parameter for
    classification so that provider_auth_required results are flagged as
    failures (the previous default of ``""`` would also catch them by string
    match but lost the harness name in any downstream log)."""
    result = _result(
        1, stderr="Error: authentication required; api key invalid"
    )

    assert review_impl.review_failed_to_run(result, "opencode") is True


def test_run_review_with_retry_does_not_retry_auth_required(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        return CommandResult(
            list(args),
            1,
            stderr="Error: authentication required; api key invalid",
        )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )

    result = review_impl.run_review_with_retry(
        config,
        runner,
        ["opencode"],
        None,
        "1",
        None,
        ctx=ctx,
    )

    assert result.returncode == 1
    assert len(calls) == 1
    assert "authentication required" in (calls[0] and result.stderr or "")


def test_run_review_with_retry_does_not_retry_quota_exhausted(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        return CommandResult(
            list(args),
            1,
            stderr="TerminalQuotaError: code: 429 QUOTA_EXHAUSTED",
        )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )

    result = review_impl.run_review_with_retry(
        config,
        runner,
        ["opencode"],
        None,
        "1",
        None,
        ctx=ctx,
    )

    assert result.returncode == 1
    assert len(calls) == 1


def test_run_review_with_retry_retries_rate_limited(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if len(calls) == 1:
            return CommandResult(
                list(args), 1, stderr="Error: 429 rate limit exceeded"
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
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )

    result = review_impl.run_review_with_retry(
        config,
        runner,
        ["opencode"],
        None,
        "1",
        None,
        ctx=ctx,
    )

    assert result.returncode == 0
    assert len(calls) == 2


def test_run_review_with_retry_retries_interrupted_subprocess(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if len(calls) == 1:
            return CommandResult(list(args), -15, stderr="Killed")
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="opencode",
        review_model="provider/model",
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )

    result = review_impl.run_review_with_retry(
        config,
        runner,
        ["opencode"],
        None,
        "1",
        None,
        ctx=ctx,
    )

    assert result.returncode == 0
    assert len(calls) == 2


def test_remediation_adapter_does_not_retry_auth_required(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        remediation_harness="opencode",
        remediation_model="opencode/model",
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(
            list(args),
            1,
            stderr="Error: authentication required; api key invalid",
        )

    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )
    adapter = RemediationAdapter(config)

    with pytest.raises(RuntimeError, match="provider auth/setup required"):
        adapter.execute(
            RemediationRequest(iteration=1, remediation_input="fix"), ctx
        )


def test_remediation_adapter_does_not_retry_quota_exhausted(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        remediation_harness="opencode",
        remediation_model="opencode/model",
    )

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        return CommandResult(
            list(args),
            1,
            stderr="TerminalQuotaError: code: 429 QUOTA_EXHAUSTED",
        )

    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )
    adapter = RemediationAdapter(config)

    with pytest.raises(RuntimeError, match="provider quota exhausted"):
        adapter.execute(
            RemediationRequest(iteration=1, remediation_input="fix"), ctx
        )
