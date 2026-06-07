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
            {
                "returncode": 1,
                "stderr": "Error: authentication required; api key invalid",
            },
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
        # Non-retryable: configured provider model is unavailable even when
        # the CLI also wraps the response in a generic server-error envelope.
        (
            {
                "returncode": 1,
                "stderr": (
                    "Error: Model not found: opencode/minimax-m3-free. "
                    "Did you mean: deepseek-v4-flash-free?\n"
                    'Error: {"name":"UnknownError",'
                    '"data":{"message":"Unexpected server error",'
                    '"ref":"err_3151eb39"}}'
                ),
            },
            "provider_model_unavailable",
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
        # Non-retryable: RevRem enforced the configured subprocess timeout.
        (
            {
                "returncode": -1,
                "stderr": (
                    "Command timed out after 1800.0 seconds\n"
                    "Command: gemini --approval-mode plan --model gemini-3.1-pro-preview\n"
                ),
            },
            "provider_timeout",
            False,
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


def test_classify_provider_failure_detects_timeout_after_partial_stdout() -> None:
    result = _result(
        -1,
        stdout="partial provider output mentioning work before timeout\n",
        stderr=(
            "Command timed out after 1800.0 seconds\n"
            "Command: gemini --approval-mode plan --model gemini-3.1-pro-preview\n"
        ),
    )

    failure = provider_failures.classify_provider_failure(result, harness="gemini")

    assert failure is not None
    assert failure.reason == "provider_timeout"
    assert failure.transient is False


def test_classify_provider_failure_does_not_treat_textual_timeout_finding_as_local_timeout() -> None:
    result = _result(
        1,
        stdout="Finding: provider timeout handling is incorrect\n",
        stderr="",
    )

    failure = provider_failures.classify_provider_failure(result, harness="codex")

    assert failure is not None
    assert failure.reason == "provider_transient_error"
    assert failure.transient is True


def test_classify_provider_failure_returns_none_for_unrecognised_output() -> None:
    result = _result(1, stderr="some unrelated non-fatal log line")
    assert (
        provider_failures.classify_provider_failure(result, harness="harness") is None
    )


def test_classify_provider_failure_ignores_help_text_api_key_mention() -> None:
    """Help text such as ``pass --api-key YOUR_KEY`` must not be misread as
    a provider authentication failure (no space between ``api`` and ``key``).
    """
    result = _result(1, stderr="Usage: opencode review --api-key YOUR_KEY [opts]")
    assert (
        provider_failures.classify_provider_failure(result, harness="harness") is None
    )


def test_classify_provider_failure_ignores_unknownerrors_substring() -> None:
    """``unknownerrors`` (no word boundary) must not match the
    ``UnknownError`` JSON envelope signal."""
    result = _result(1, stderr="recent unknownerrors: 3")
    assert (
        provider_failures.classify_provider_failure(result, harness="harness") is None
    )


def test_classify_provider_failure_ignores_temporarily_unavailable_in_cache_message() -> (
    None
):
    """Cache messages that mention ``temporarily unavailable`` must not
    trigger the transient failure path on their own."""
    result = _result(1, stderr="cache entry temporarily unavailable, retry later")
    assert (
        provider_failures.classify_provider_failure(result, harness="harness") is None
    )


def test_review_failed_to_run_flags_provider_auth_required(tmp_path: Path) -> None:
    """``review_failed_to_run`` must use the harness parameter for
    classification so that provider_auth_required results are flagged as
    failures (the previous default of ``""`` would also catch them by string
    match but lost the harness name in any downstream log)."""
    result = _result(1, stderr="Error: authentication required; api key invalid")

    assert review_impl.review_failed_to_run(result, "opencode") is True


def test_review_failed_to_run_preserves_returncode_one_findings_with_provider_keywords() -> None:
    result = _result(
        1,
        stdout=(
            "- [P1] Preserve finding text that mentions rate limit handling\n"
            "  This is a legitimate review finding, not a provider failure.\n"
            "REVIEW_STATUS: findings\n"
        ),
        stderr="",
    )

    assert review_impl.review_failed_to_run(result, "opencode") is False


@pytest.mark.parametrize(
    "harness",
    ["", "opencode", "gemini", "kilo", "codex", "claude"],
)
def test_classify_provider_failure_is_harness_agnostic(
    harness: str, tmp_path: Path
) -> None:
    """The ``harness`` argument is a forward-compat hook: it must not
    affect the classification outcome until a harness-specific rule is
    introduced deliberately.
    """
    result = _result(1, stderr="Error: 429 rate limit exceeded")
    failure = provider_failures.classify_provider_failure(result, harness=harness)
    assert failure is not None
    assert failure.reason == "provider_rate_limited"
    assert failure.transient is True


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


def test_run_review_with_retry_does_not_retry_timeout(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        return CommandResult(
            list(args),
            -1,
            stderr=(
                "Command timed out after 1800.0 seconds\n"
                "Command: gemini --approval-mode plan --model gemini-3.1-pro-preview\n"
            ),
        )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        review_harness="gemini",
        review_model="gemini-3.1-pro-preview",
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
        ["gemini"],
        None,
        "1",
        None,
        ctx=ctx,
    )

    assert result.returncode == -1
    assert len(calls) == 1


def test_run_review_with_retry_retries_rate_limited(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(list(args))
        if len(calls) == 1:
            return CommandResult(list(args), 1, stderr="Error: 429 rate limit exceeded")
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
        adapter.execute(RemediationRequest(iteration=1, remediation_input="fix"), ctx)


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
        adapter.execute(RemediationRequest(iteration=1, remediation_input="fix"), ctx)


def test_run_review_with_retry_sleeps_between_transient_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_review_with_retry`` must back off between transient retries so a
    sustained rate limit does not produce a tight retry loop."""
    calls: list[float] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        calls.append(_monotonic())
        if len(calls) == 1:
            return CommandResult(list(args), 1, stderr="Error: 429 rate limit exceeded")
        return CommandResult(list(args), 0, stdout="REVIEW_STATUS: clear\n")

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        calls.append(_monotonic())
        sleeps.append(seconds)

    fake_now = {"t": 0.0}

    def _monotonic() -> float:
        return fake_now["t"]

    def tick(seconds: float) -> None:
        fake_now["t"] += seconds

    monkeypatch.setattr(review_impl.time, "sleep", fake_sleep)
    monkeypatch.setattr(review_impl.time, "monotonic", _monotonic)

    real_sleep_calls: list[float] = []

    def recording_sleep(seconds: float) -> None:
        real_sleep_calls.append(seconds)
        tick(seconds)

    monkeypatch.setattr(review_impl.time, "sleep", recording_sleep)

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
    assert len(real_sleep_calls) == 1
    assert real_sleep_calls[0] >= review_impl.REVIEW_RETRY_BACKOFF_SECONDS


def test_remediation_adapter_retries_transient_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remediation should retry a transient rate-limit failure once and
    succeed on the second attempt, mirroring the review-phase contract."""
    (tmp_path / "artifacts").mkdir()
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:2] == ["git", "diff"]:
            return CommandResult(list(args), 0, stdout="")
        calls.append(list(args))
        if len(calls) == 1:
            return CommandResult(list(args), 1, stderr="Error: 429 rate limit exceeded")
        return CommandResult(list(args), 0, stdout="ok\n")

    real_sleep_calls: list[float] = []

    def recording_sleep(seconds: float) -> None:
        real_sleep_calls.append(seconds)

    monkeypatch.setattr(
        "code_review_loop.adapters.remediation.time.sleep", recording_sleep
    )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        remediation_harness="opencode",
        remediation_model="opencode/model",
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )
    adapter = RemediationAdapter(config)

    adapter.execute(RemediationRequest(iteration=1, remediation_input="fix"), ctx)

    assert len(calls) == 2
    assert real_sleep_calls == [
        config.provider_retry_backoff_seconds,
    ]


def test_remediation_adapter_uses_configured_retry_attempts_and_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:2] == ["git", "diff"]:
            return CommandResult(list(args), 0, stdout="")
        calls.append(list(args))
        if len(calls) < 3:
            return CommandResult(list(args), 1, stderr="Error: 429 rate limit exceeded")
        return CommandResult(list(args), 0, stdout="ok\n")

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "code_review_loop.adapters.remediation.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        remediation_harness="opencode",
        remediation_model="opencode/model",
        provider_retry_attempts=3,
        provider_retry_backoff_seconds=4.5,
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )
    adapter = RemediationAdapter(config)

    adapter.execute(RemediationRequest(iteration=1, remediation_input="fix"), ctx)

    assert len(calls) == 3
    assert sleep_calls == [4.5, 4.5]


def test_remediation_adapter_does_not_retry_model_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "artifacts").mkdir()
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:2] == ["git", "diff"]:
            return CommandResult(list(args), 0, stdout="")
        calls.append(list(args))
        return CommandResult(
            list(args),
            1,
            stderr=(
                "Error: Model not found: opencode/minimax-m3-free. "
                "Did you mean: deepseek-v4-flash-free?\n"
                'Error: {"name":"UnknownError","data":{"message":"Unexpected server error"}}'
            ),
        )

    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "code_review_loop.adapters.remediation.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        remediation_harness="opencode",
        remediation_model="opencode/minimax-m3-free",
        provider_retry_attempts=3,
        provider_retry_backoff_seconds=4.5,
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )
    adapter = RemediationAdapter(config)

    with pytest.raises(RuntimeError, match="provider model unavailable"):
        adapter.execute(RemediationRequest(iteration=1, remediation_input="fix"), ctx)

    assert len(calls) == 1
    assert sleep_calls == []


def test_remediation_retry_persists_failed_attempt_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transient retry must persist a failed-attempt artifact for parity
    with ``run_review_with_retry`` (which writes
    ``review-{label}-attempt-{attempt}.txt``). Operators triaging a
    transient retry should see the failed first attempt on disk, not only
    the post-retry transcript.
    """
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:2] == ["git", "diff"]:
            return CommandResult(list(args), 0, stdout="")
        calls.append(list(args))
        if len(calls) == 1:
            return CommandResult(list(args), 1, stderr="Error: 429 rate limit exceeded")
        return CommandResult(list(args), 0, stdout="ok\n")

    monkeypatch.setattr(
        "code_review_loop.adapters.remediation.time.sleep", lambda _s: None
    )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=artifact_dir,
        remediation_harness="opencode",
        remediation_model="opencode/model",
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )
    adapter = RemediationAdapter(config)

    adapter.execute(RemediationRequest(iteration=2, remediation_input="fix"), ctx)

    failed_attempt_artifact = artifact_dir / "remediation-2-attempt-1.txt"
    assert failed_attempt_artifact.exists(), (
        "remediation retry must persist the failed first-attempt artifact "
        "for observability parity with run_review_with_retry"
    )
    contents = failed_attempt_artifact.read_text()
    assert "429 rate limit exceeded" in contents
    assert (artifact_dir / "remediation-2.txt").exists()


def test_remediation_adapter_does_not_retry_auth_required_repeatedly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-transient failures must still raise on the first attempt so a
    misconfigured API key fails fast."""
    (tmp_path / "artifacts").mkdir()
    calls: list[list[str]] = []

    def runner(args, cwd, input_text=None, timeout_seconds=None):
        if args[:2] == ["git", "diff"]:
            return CommandResult(list(args), 0, stdout="")
        calls.append(list(args))
        return CommandResult(
            list(args),
            1,
            stderr="Error: authentication required; api key invalid",
        )

    sleep_calls: list[float] = []

    def recording_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        "code_review_loop.adapters.remediation.time.sleep", recording_sleep
    )

    config = LoopConfig(
        base="main",
        max_iterations=1,
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        remediation_harness="opencode",
        remediation_model="opencode/model",
    )
    ctx = RunContext(
        runner=runner,
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        **phase_harness_kwargs(),
    )
    adapter = RemediationAdapter(config)

    with pytest.raises(RuntimeError, match="provider auth/setup required"):
        adapter.execute(RemediationRequest(iteration=1, remediation_input="fix"), ctx)

    assert len(calls) == 1
    assert sleep_calls == []
