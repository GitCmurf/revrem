from __future__ import annotations

from io import StringIO

from code_review_loop import profiles, tui_run_controller, tui_state


class FixedIdentity:
    def new_run_id(self) -> str:
        return "fixedrun"


class FakeProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = StringIO("stdout line\n")
        self.stderr = StringIO("stderr line\n")

    def poll(self) -> int | None:
        return self.returncode

    def wait(self) -> int:
        return self.returncode


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
