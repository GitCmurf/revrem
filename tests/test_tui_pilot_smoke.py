from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from support.git_fixtures import init_repo
from support.tui_pilot import pilot_app

from code_review_loop import events, tui, tui_loop_state


def test_tui_pilot_boots_home_view(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.pause()
            home = app.query_one("#screen-home")
            rendered = str(home.render())
            assert "Loop" in rendered
            assert "1 Loop" in rendered
            assert "3 Profiles" in rendered
            assert "security" in rendered
            status = app.query_one("#status-bar")
            assert "profile=security" in str(status.render())
            footer = app.query_one("#footer-bar")
            assert "?\\]help" in str(footer.render())
            await pilot.press("h")
            await pilot.pause()
            assert "confirm/start live run" in str(footer.render())
            _assert_no_widget(app, "#profile-name")
            _assert_no_widget(app, "#profile-path")

    asyncio.run(run())


def test_loop_workspace_renders_real_diagram_widgets(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            assert app.query(".phase-card")
            header = str(app.query_one("#loop-header").render())
            review_gutter = str(app.query_one("#phase-gutter-review").render())
            commit_gutter = str(app.query_one("#phase-gutter-commit").render())
            review = str(app.query_one("#phase-card-review").render())
            remediation = str(app.query_one("#phase-card-remediation").render())
            assert "security" in header and "base" in header
            assert "┌▶" in review_gutter
            assert "└◀" in commit_gutter
            assert "review" in review
            assert "remediation" in remediation

    asyncio.run(run())


def test_loop_iterations_key_opens_iteration_prompt_with_current_value(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\nmax_iterations=7\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.press("i")
            await pilot.pause()
            assert "Edit max_iterations" in str(
                app.screen.query_one("#prompt-title").render()
            )
            assert app.screen.query_one("#prompt-input").value == "7"

    asyncio.run(run())


def test_profiles_workspace_i_still_imports_profiles(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("3")
            await pilot.press("i")
            await pilot.pause()
            assert "Import profiles" in str(app.screen.query_one("#prompt-title").render())

    asyncio.run(run())


def test_loop_inline_edit_marks_dirty_and_overlays(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.review]\nharness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_text_field("model", "gpt-5.6")
            await pilot.pause()
            assert diagram.is_dirty is True
            app._update_console_status()
            assert "*" in str(app.query_one("#status-bar").render())
            diagram.set_text_field("timeout", "123")
            assert diagram.model.field_value("review.model", "gpt-5.5") == "gpt-5.6"
            assert diagram.model.field_value("review.timeout_seconds", None) == 123.0

    asyncio.run(run())


def test_loop_reverted_edit_clears_dirty_marker(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.review]\nharness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_text_field("model", "gpt-5.6")
            app._update_console_status()
            assert "*" in str(app.query_one("#status-bar").render())
            diagram.set_text_field("model", "gpt-5.5")
            app._update_console_status()
            assert diagram.is_dirty is False
            assert "*" not in str(app.query_one("#status-bar").render())

    asyncio.run(run())


def test_loop_triage_focus_mounts_routes_table(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='codex-midi'\n"
            "[profiles.edit.triage.routes.codex-midi]\n"
            "harness='codex'\nmodel='gpt-5.4-mini'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.press("down")
            await pilot.pause()
            assert app.query(".triage-routes-table")

    asyncio.run(run())


def test_loop_diagram_current_phase_clamps_index(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 999
            assert diagram.current_phase() == "commit"
            assert diagram.focused_index == len(tui_loop_state.LOOP_PHASES) - 1

    asyncio.run(run())


def test_loop_save_persists_and_clears_dirty(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.review]\nharness='codex'\nmodel='gpt-5.5'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.model.set_field("review.model", "gpt-5.6")
            diagram.rebuild()
            assert diagram.is_dirty is True
            app.action_save_loop()
            await pilot.pause()
            assert app.query_one("#loop-diagram").is_dirty is False
            persisted = (repo / ".revrem.toml").read_text(encoding="utf-8")
            assert "gpt-5.6" in persisted

    asyncio.run(run())


def test_builtin_profile_save_notifies_clone_to_edit(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        notifications: list[str] = []
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            app.notify = lambda message, **_kwargs: notifications.append(message)
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_text_field("model", "gpt-9")
            app.action_save_loop()
            await pilot.pause()
            assert any("built-in profile 'security' is read-only" in item for item in notifications)
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_builtin_profile_save_and_run_notifies_clone_to_edit(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        notifications: list[str] = []
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            app.notify = lambda message, **_kwargs: notifications.append(message)
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_text_field("model", "gpt-9")
            app.action_launch_run()
            await pilot.pause()
            assert any("built-in profile 'security' is read-only" in item for item in notifications)
            assert app.live_run_controller.launch is None
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_profile_selection_reloads_loop_diagram(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.alpha]\n[profiles.alpha.pipeline]\nbase='main'\n"
            "[profiles.alpha.review]\nmodel='alpha-model'\n"
            "[profiles.beta]\n[profiles.beta.pipeline]\nbase='main'\n"
            "[profiles.beta.review]\nmodel='beta-model'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="alpha") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            assert "alpha" in str(app.query_one("#loop-header").render())
            await pilot.press("3")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("1")
            await pilot.pause()
            assert "beta" in str(app.query_one("#loop-header").render())
            assert "beta-model" in str(app.query_one("#phase-card-review").render())

    asyncio.run(run())


def test_dirty_loop_blocks_profile_switch(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.alpha]\n[profiles.alpha.pipeline]\nbase='main'\n"
            "[profiles.alpha.review]\nmodel='alpha-model'\n"
            "[profiles.beta]\n[profiles.beta.pipeline]\nbase='main'\n"
            "[profiles.beta.review]\nmodel='beta-model'\n",
            encoding="utf-8",
        )
        notifications: list[str] = []
        async with pilot_app(cwd=repo, profile_name="alpha") as (app, pilot):
            app.notify = lambda message, **_kwargs: notifications.append(message)
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.set_text_field("model", "unsaved-alpha")
            await pilot.press("3")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("1")
            await pilot.pause()
            assert any("Save or revert loop changes" in item for item in notifications)
            assert "alpha" in str(app.query_one("#loop-header").render())
            assert diagram.model.field_value("review.model", "") == "unsaved-alpha"

    asyncio.run(run())


def test_tui_pilot_confirmed_launch_reaches_visible_running_state(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="slow_cancel", artifact_dir="runs/live-launch")
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            await pilot.press("r")
            await pilot.press("r")

            await _wait_for(
                lambda: "Live status: running" in _render(app, "#screen-run-monitor"),
                pilot_pause=pilot.pause,
            )
            assert "Live run started: live" in _render(app, "#screen-run-monitor") or (
                app.live_run_controller.launch is not None
            )
            assert app.live_run_controller.launch is not None
            assert app.live_run_controller.launch.artifact_dir == repo / "runs/live-launch"
            app.live_run_controller.cancel(grace_seconds=1)

    asyncio.run(run())


def test_tui_pilot_live_monitor_updates_and_cancels_visible_run(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="review_findings", artifact_dir="runs/live-cancel")
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            await pilot.press("r")
            await pilot.press("r")

            await _wait_for(
                lambda: (
                    "phase_start" in _render(app, "#screen-run-monitor")
                    and "phase_result: findings-summary (1)" in _render(app, "#screen-run-monitor")
                ),
                pilot_pause=pilot.pause,
                timeout=12,
            )
            await pilot.press("k")
            await _wait_for(
                lambda: "Live status: cancelled" in _render(app, "#screen-run-monitor"),
                pilot_pause=pilot.pause,
                timeout=12,
            )

            launch = app.live_run_controller.launch
            assert launch is not None
            summary = json.loads((launch.artifact_dir / "summary.json").read_text(encoding="utf-8"))
            assert summary["stopped_reason"] == "cancelled"
            records, _ = events.read_events(launch.artifact_dir / events.EVENTS_FILENAME)
            assert any(record.kind == "cancellation" for record in records)

    asyncio.run(run())


def test_tui_pilot_prompt_entry_runs_profile_actions(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="review_clear", artifact_dir="runs/live-prompt")
        calls = []

        def fake_run_launch_plan(plan, *, cwd, capture_output=True):
            calls.append((plan.argv, cwd, capture_output))
            return type("Result", (), {"returncode": 0})()

        monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)

        async with pilot_app(cwd=repo, profile_name="live") as (_app, pilot):
            await pilot.press("n")
            await pilot.press("f", "r", "e", "s", "h")
            await pilot.press("enter")
            await _wait_for(lambda: bool(calls), pilot_pause=pilot.pause)

        assert calls == [
            (("revrem", "config", "new", "fresh", "--no-interactive"), repo, True)
        ]

    asyncio.run(run())


def test_tui_pilot_prompt_escape_cancels_without_running(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(repo, review_model="review_clear", artifact_dir="runs/live-prompt-cancel")
        calls = []

        def fake_run_launch_plan(plan, *, cwd, capture_output=True):
            calls.append((plan.argv, cwd, capture_output))
            return type("Result", (), {"returncode": 0})()

        monkeypatch.setattr(tui, "run_launch_plan", fake_run_launch_plan)

        async with pilot_app(cwd=repo, profile_name="live") as (_app, pilot):
            await pilot.press("i")
            await pilot.press("escape")
            await pilot.pause()

        assert calls == []

    asyncio.run(run())


def _write_live_profile(repo: Path, *, review_model: str, artifact_dir: str) -> None:
    (repo / ".revrem.toml").write_text(
        f"""
[profiles.live]
description = "Pilot live run"

[profiles.live.pipeline]
max_iterations = 1
final_review = false

[profiles.live.output]
artifact_dir = "{artifact_dir}"

[profiles.live.review]
harness = "fake"
model = "{review_model}"

[profiles.live.remediation]
harness = "fake"
model = "slow_cancel"

[profiles.live.triage]
enabled = false
""",
        encoding="utf-8",
    )


async def _wait_for(
    predicate: Callable[[], bool],
    *,
    pilot_pause: Callable[[], Awaitable[object]],
    timeout: float = 8,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot_pause()
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for TUI state")


def _render(app: tui.RevRemApp, selector: str) -> str:
    return str(app.query_one(selector).render())


def _assert_no_widget(app: tui.RevRemApp, selector: str) -> None:
    try:
        app.query_one(selector)
    except Exception:
        return
    raise AssertionError(f"unexpected widget exists: {selector}")
