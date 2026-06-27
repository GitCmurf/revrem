from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path

import pytest
from support.git_fixtures import init_repo

from code_review_loop import events, profiles, tui_run_controller, tui_state


class FixedIdentity:
    def new_run_id(self) -> str:
        return "fixedrun"


class FakeProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = StringIO("stdout line\n")
        self.stderr = StringIO("stderr line\n")
        self.pid = 12345
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)


def test_prepare_live_run_launch_uses_profile_artifact_dir_precedence(tmp_path):
    profile = profiles.Profile(
        name="demo",
        output=profiles.OutputConfig(artifact_dir="custom/run"),
    )
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )

    launch = tui_run_controller.prepare_live_run_launch(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        identity=FixedIdentity(),
    )

    assert launch.artifact_dir_arg == "custom/run"
    assert launch.artifact_dir == tmp_path / "custom/run"
    assert launch.argv == (
        "revrem",
        "--profile",
        "demo",
        "--artifact-dir",
        "custom/run",
        "--no-tty",
        "--pending-review",
        "ignore",
        "--summary-format",
        "json",
    )


def test_prepare_live_run_launch_generates_default_shape(tmp_path):
    profile = profiles.Profile(name="demo")
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )

    launch = tui_run_controller.prepare_live_run_launch(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        identity=FixedIdentity(),
    )

    assert launch.artifact_dir_arg.startswith(".revrem/runs/")
    assert launch.artifact_dir_arg.endswith("-fixedrun")
    assert launch.artifact_dir == tmp_path / launch.artifact_dir_arg


def test_live_run_controller_starts_child_with_machine_friendly_argv(tmp_path):
    profile = profiles.Profile(name="demo")
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )
    calls = []

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeProcess()

    controller = tui_run_controller.LiveRunController()
    launch = controller.start(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        entrypoint_resolver=lambda argv: ["python", "-m", "code_review_loop", *argv[1:]],
        popen_factory=fake_popen,
        identity=FixedIdentity(),
    )

    assert controller.status == "running"
    assert calls[0][0] == [
        "python",
        "-m",
        "code_review_loop",
        "--profile",
        "demo",
        "--artifact-dir",
        launch.artifact_dir_arg,
        "--no-tty",
        "--pending-review",
        "ignore",
        "--summary-format",
        "json",
    ]
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][1]["stdout"] is tui_run_controller.subprocess.PIPE
    assert calls[0][1]["stderr"] is tui_run_controller.subprocess.PIPE
    assert calls[0][1]["text"] is True
    assert calls[0][1]["start_new_session"] is True


def test_start_marks_setup_failed_when_launch_raises(tmp_path):
    profile = profiles.Profile(name="demo")
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )

    def boom_popen(*_args, **_kwargs):
        raise OSError("no such executable")

    controller = tui_run_controller.LiveRunController()
    with pytest.raises(OSError):
        controller.start(
            profile=profile,
            plan=plan,
            cwd=tmp_path,
            entrypoint_resolver=list,
            popen_factory=boom_popen,
            identity=FixedIdentity(),
        )

    assert controller.status == "setup-failed"
    assert controller.process is None
    assert controller.message is not None
    assert "no such executable" in controller.message
    # A failed launch must not look like an active run to the TUI.
    assert controller.refresh() == "setup-failed"


def test_classify_exit_requires_artifacts_for_clean_cancellation():
    assert tui_run_controller.classify_exit(0) == "completed-clear"
    assert tui_run_controller.classify_exit(2) == "completed-findings"
    assert tui_run_controller.classify_exit(3) == "budget"
    assert tui_run_controller.classify_exit(4) == "setup-failed"
    assert tui_run_controller.classify_exit(5) == "failed"
    assert (
        tui_run_controller.classify_exit(
            5,
            summary={"final_status": "error", "stopped_reason": "cancelled"},
        )
        == "cancelled"
    )
    assert tui_run_controller.classify_exit(6) == "failed"
    assert tui_run_controller.classify_exit(130) == "interrupted-before-run-initialized"
    assert (
        tui_run_controller.classify_exit(-signal.SIGINT)
        == "interrupted-before-run-initialized"
    )


def test_cancel_sends_sigint_to_process_group(monkeypatch):
    process = FakeProcess(returncode=5)
    process.returncode = None  # type: ignore[assignment]
    signals = []

    def fake_getpgid(pid):
        assert pid == process.pid
        return 999

    def fake_killpg(pgid, signum):
        signals.append((pgid, signum))
        process.returncode = 5  # type: ignore[assignment]

    monkeypatch.setattr(tui_run_controller.os, "getpgid", fake_getpgid)
    monkeypatch.setattr(tui_run_controller.os, "killpg", fake_killpg)
    controller = tui_run_controller.LiveRunController(process=process, status="running")

    status = controller.cancel(grace_seconds=0)

    assert status == "failed"
    assert signals == [(999, tui_run_controller.signal.SIGINT)]


def test_cancel_reports_forced_cleanup_after_escalation(monkeypatch):
    class StubbornProcess(FakeProcess):
        def __init__(self):
            super().__init__(returncode=None)  # type: ignore[arg-type]
            self.wait_calls = 0

        def poll(self) -> int | None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self.wait_calls < 3:
                raise subprocess.TimeoutExpired(["fake"], timeout)
            self.returncode = -9
            return -9

    process = StubbornProcess()
    signals = []
    monkeypatch.setattr(tui_run_controller.os, "getpgid", lambda pid: 999)
    monkeypatch.setattr(
        tui_run_controller.os,
        "killpg",
        lambda pgid, signum: signals.append((pgid, signum)),
    )
    controller = tui_run_controller.LiveRunController(process=process, status="running")

    status = controller.cancel(grace_seconds=0)

    assert status == "failed-forced-cleanup"
    assert signals == [
        (999, tui_run_controller.signal.SIGINT),
        (999, tui_run_controller.signal.SIGTERM),
        (999, tui_run_controller.signal.SIGKILL),
    ]


def test_controller_cancels_real_revrem_child_and_reads_cancellation_summary(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
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
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    (repo / ".revrem.toml").write_text(
        """
[profiles.cancel-demo]
review.harness = "fake"
review.model = "slow_cancel"
remediation.harness = "fake"
remediation.model = "clear"
triage.enabled = false
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("REVREM_ALLOW_FAKE_HARNESS", "1")
    profile = profiles.resolve_profile("cancel-demo", cwd=repo)
    plan = tui_state.launch_plan(profile, dry_run=False)
    controller = tui_run_controller.LiveRunController()

    launch = controller.start(
        profile=profile,
        plan=plan,
        cwd=repo,
        entrypoint_resolver=lambda argv: [sys.executable, "-m", "code_review_loop", *argv[1:]],
    )
    deadline = time.monotonic() + 10
    while not (launch.artifact_dir / events.EVENTS_FILENAME).is_file():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for events.jsonl")
        time.sleep(0.01)

    status = controller.cancel(grace_seconds=5)

    summary = json.loads((launch.artifact_dir / "summary.json").read_text(encoding="utf-8"))
    assert status == "cancelled"
    assert summary["stopped_reason"] == "cancelled"
    assert any(event.kind == "cancellation" for event in controller.read_live_events().events)


def test_cancel_reaps_nested_provider_child_with_own_session(tmp_path, monkeypatch):
    repo = init_repo(tmp_path / "repo")
    provider = tmp_path / "provider.py"
    nested_pid_file = tmp_path / "nested.pid"
    provider.write_text(
        """#!/usr/bin/env python3
import os
import subprocess
import sys
import time

child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    start_new_session=True,
)
with open(os.environ["REVREM_NESTED_PID_FILE"], "w", encoding="utf-8") as handle:
    handle.write(str(child.pid))
    handle.flush()
time.sleep(60)
""",
        encoding="utf-8",
    )
    provider.chmod(0o755)
    (repo / ".revrem.toml").write_text(
        f"""
[profiles.cancel-nested]

[profiles.cancel-nested.pipeline]
max_iterations = 1
final_review = false

[profiles.cancel-nested.review]
harness = "claude"
model = "nested"

[profiles.cancel-nested.remediation]
harness = "fake"
model = "clear"

[profiles.cancel-nested.triage]
enabled = false

[profiles.cancel-nested.runtime]
provider_retry_attempts = 1

[profiles.cancel-nested.runtime.harness_executables]
claude = "{provider}"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("REVREM_ALLOW_FAKE_HARNESS", "1")
    monkeypatch.setenv("REVREM_NESTED_PID_FILE", str(nested_pid_file))
    profile = profiles.resolve_profile("cancel-nested", cwd=repo)
    plan = tui_state.launch_plan(profile, dry_run=False)
    controller = tui_run_controller.LiveRunController()

    controller.start(
        profile=profile,
        plan=plan,
        cwd=repo,
        entrypoint_resolver=lambda argv: [sys.executable, "-m", "code_review_loop", *argv[1:]],
    )
    nested_pid = _wait_for_pid_file(nested_pid_file)

    # Allow the normal SIGINT cancellation path enough headroom to write
    # summary.json and exit before escalation, even when the suite saturates
    # CPU; the sibling real-child cancel test uses the same grace.
    status = controller.cancel(grace_seconds=5)

    assert status == "cancelled"
    _wait_until_not_running(nested_pid)


def test_live_events_ignore_stale_explicit_artifact_dir_until_replaced(tmp_path):
    run_dir = tmp_path / "custom" / "run"
    run_dir.mkdir(parents=True)
    old_sink = events.JsonlSink(run_dir, "old-run")
    old_sink.emit("phase_start", phase="review")
    old_sink.close()
    profile = profiles.Profile(
        name="demo",
        output=profiles.OutputConfig(artifact_dir="custom/run"),
    )
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )

    controller = tui_run_controller.LiveRunController()
    controller.start(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        entrypoint_resolver=list,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
    )

    assert controller.read_live_events().ready is False

    new_sink = events.JsonlSink(run_dir, "new-run")
    new_sink.emit("phase_start", phase="review", payload={"message": "new"})
    new_sink.close()

    snapshot = controller.read_live_events()
    assert snapshot.ready is True
    assert [event.run_id for event in snapshot.events] == ["new-run"]


def test_live_events_ignore_malformed_stale_file_until_identity_changes(tmp_path):
    run_dir = tmp_path / "custom" / "run"
    run_dir.mkdir(parents=True)
    events_path = run_dir / events.EVENTS_FILENAME
    events_path.write_text("{not json}\n", encoding="utf-8")
    profile = profiles.Profile(
        name="demo",
        output=profiles.OutputConfig(artifact_dir="custom/run"),
    )
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )

    controller = tui_run_controller.LiveRunController()
    controller.start(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        entrypoint_resolver=list,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
    )

    assert controller.read_live_events().ready is False

    new_sink = events.JsonlSink(run_dir, "new-run")
    new_sink.emit("phase_start", phase="review")
    new_sink.close()

    snapshot = controller.read_live_events()
    assert snapshot.ready is True
    assert [event.run_id for event in snapshot.events] == ["new-run"]


def test_live_events_expose_non_terminal_rows_before_close(tmp_path):
    run_dir = tmp_path / "custom" / "run"
    run_dir.mkdir(parents=True)
    profile = profiles.Profile(
        name="demo",
        output=profiles.OutputConfig(artifact_dir="custom/run"),
    )
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )

    controller = tui_run_controller.LiveRunController()
    controller.start(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        entrypoint_resolver=list,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(returncode=None),
    )

    sink = events.JsonlSink(run_dir, "new-run")
    sink.emit("phase_start", phase="review", payload={"message": "start"})

    snapshot = controller.read_live_events()
    assert snapshot.ready is True
    views = tui_state.event_views_from_events(snapshot.events)
    assert [(event.seq, event.kind, event.detail) for event in views] == [
        (1, "phase_start", "start"),
    ]

    sink.emit("phase_result", phase="review", payload={"status": "clear"})
    sink.close()

    snapshot = controller.read_live_events()
    views = tui_state.event_views_from_events(snapshot.events)
    assert [(event.seq, event.kind, event.detail) for event in views] == [
        (1, "phase_start", "start"),
        (2, "phase_result", "clear"),
    ]


def test_finish_ignores_stale_summary_from_explicit_artifact_dir(tmp_path):
    run_dir = tmp_path / "custom" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"final_status": "error", "stopped_reason": "cancelled"}),
        encoding="utf-8",
    )
    profile = profiles.Profile(
        name="demo",
        output=profiles.OutputConfig(artifact_dir="custom/run"),
    )
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )

    controller = tui_run_controller.LiveRunController()
    controller.start(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        entrypoint_resolver=list,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(returncode=5),
    )

    status = controller.finish(5)

    assert status == "failed"


def test_finish_accepts_replaced_summary_from_explicit_artifact_dir(tmp_path):
    run_dir = tmp_path / "custom" / "run"
    run_dir.mkdir(parents=True)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(
        json.dumps({"final_status": "error", "stopped_reason": "cancelled"}),
        encoding="utf-8",
    )
    profile = profiles.Profile(
        name="demo",
        output=profiles.OutputConfig(artifact_dir="custom/run"),
    )
    plan = tui_state.LaunchPlan(
        profile_name="demo",
        mode="run",
        argv=("revrem", "--profile", "demo"),
        shell_command="revrem --profile demo",
    )
    controller = tui_run_controller.LiveRunController()
    controller.start(
        profile=profile,
        plan=plan,
        cwd=tmp_path,
        entrypoint_resolver=list,
        popen_factory=lambda *_args, **_kwargs: FakeProcess(returncode=5),
    )
    summary_path.unlink()
    summary_path.write_text(
        json.dumps({"final_status": "error", "stopped_reason": "cancelled"}),
        encoding="utf-8",
    )

    status = controller.finish(5)

    assert status == "cancelled"


def test_terminal_statuses_cover_all_non_idle_running_states():
    statuses = set(tui_run_controller.TERMINAL_STATUSES)

    assert statuses == {
        "completed-clear",
        "completed-findings",
        "budget",
        "setup-failed",
        "cancelled",
        "interrupted-before-run-initialized",
        "failed",
        "failed-forced-cleanup",
    }


def _wait_for_pid_file(path: Path) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.is_file():
            return int(path.read_text(encoding="utf-8"))
        time.sleep(0.01)
    raise AssertionError("timed out waiting for nested pid file")


def _wait_until_not_running(pid: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"nested child still running: {pid}")


def _pid_is_running(pid: int) -> bool:
    # os.kill(pid, 0) is the portable liveness probe; it governs on hosts
    # without /proc. /proc only refines the result so an already-reaped
    # zombie (which os.kill still reports as alive) is treated as gone.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    proc_stat = Path("/proc") / str(pid) / "stat"
    try:
        stat_text = proc_stat.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # /proc is unavailable or the entry vanished after os.kill succeeded.
        return True
    close_paren = stat_text.rfind(")")
    if close_paren != -1:
        fields = stat_text[close_paren + 1 :].strip().split()
        if fields and fields[0] == "Z":
            return False
    return True
