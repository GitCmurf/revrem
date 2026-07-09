from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from support.git_fixtures import init_repo
from support.tui_pilot import pilot_app

from code_review_loop import (
    events,
    tui,
    tui_loop_state,
    tui_loop_widgets,
    tui_run_controller,
)

LIVE_RUN_PILOT_TIMEOUT = 30


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
            returns = str(app.query_one("#loop-returns").render())
            assert "security" in header and "base" in header
            assert "01" in review_gutter
            assert "05" in commit_gutter
            assert "OUTER LOOP" in returns
            assert "REVIEW" in review
            assert "REMEDIATION" in remediation

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
            assert "Import profiles" in str(
                app.screen.query_one("#prompt-title").render()
            )

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
            original_effort = diagram.model.field_value(
                "review.reasoning_effort", "medium"
            )
            diagram.cycle_field("effort")
            await pilot.pause()
            assert diagram.is_dirty is True
            assert (
                diagram.model.field_value("review.reasoning_effort", "medium")
                != original_effort
            )
            app._update_console_status()
            assert "*" in str(app.query_one("#status-bar").render())
            diagram.set_text_field("model", "gpt-5.6")
            diagram.set_text_field("timeout", "123")
            assert diagram.model.field_value("review.model", "gpt-5.5") == "gpt-5.6"
            assert diagram.model.field_value("review.timeout_seconds", None) == 123.0

    asyncio.run(run())


def test_loop_cycle_harness_advances_from_effective_codex_value(tmp_path):
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
            assert diagram.model.is_dirty is False
            expected = tui_loop_widgets.HARNESS_CHOICES[
                (tui_loop_widgets.HARNESS_CHOICES.index("codex") + 1)
                % len(tui_loop_widgets.HARNESS_CHOICES)
            ]
            diagram.cycle_field("harness")
            await pilot.pause()
            assert diagram.model.field_value("review.harness", "codex") == expected

    asyncio.run(run())


def test_loop_cycle_effort_advances_from_effective_low_value(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.review]\nharness='codex'\nmodel='gpt-5.5'\n"
            "reasoning_effort='low'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            assert diagram.model.is_dirty is False
            expected = tui_loop_widgets.EFFORT_CHOICES[
                (tui_loop_widgets.EFFORT_CHOICES.index("low") + 1)
                % len(tui_loop_widgets.EFFORT_CHOICES)
            ]
            diagram.cycle_field("effort")
            await pilot.pause()
            assert (
                diagram.model.field_value("review.reasoning_effort", "low") == expected
            )

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


def test_loop_enter_expands_triage_before_route_focus_and_movement_keeps_expansion(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\nchecks=['pytest -q']\n"
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
            routes = app.query_one("#triage-routes-table")
            assert routes.display is False
            await pilot.press("enter")
            await pilot.pause()
            assert routes.display is True
            assert app.query_one("#loop-diagram").route_mode is False
            await pilot.press("tab")
            await pilot.pause()
            assert app.query_one("#loop-diagram").route_mode is True
            await pilot.press("escape")
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert "commands:" in str(app.query_one("#phase-card-checks").render())
            assert "harness:" not in str(app.query_one("#phase-card-commit").render()).lower()

    asyncio.run(run())


def test_tui_splash_can_be_skipped_or_dismissed(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security", skip_splash=False) as (
            app,
            pilot,
        ):
            assert app._splash_visible is True
            assert app.query_one("#splash-pane").display is True
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#splash-pane").display is False
        async with pilot_app(cwd=repo, profile_name="security", skip_splash=True) as (
            app,
            pilot,
        ):
            await pilot.pause()
            assert app.query_one("#splash-pane").display is False

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
            assert any(
                "built-in profile 'security' is read-only" in item
                for item in notifications
            )
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
            assert any(
                "built-in profile 'security' is read-only" in item
                for item in notifications
            )
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


def test_profiles_workspace_renders_picker_and_loads_into_loop(tmp_path):
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
            await pilot.press("3")
            await pilot.pause()
            picker = app.query_one("#profile-picker")
            assert "PROFILES" in _render(app, "#profile-picker")
            assert "alpha" in _render(app, "#profile-picker")
            picker.move(1)
            await pilot.press("enter")
            await pilot.pause()
            assert app._workspace == "loop"
            assert app._loop_diagram.model.name == "beta"
            assert "beta-model" in _render(app, "#phase-card-review")

    asyncio.run(run())


def test_profiles_workspace_warns_when_loading_builtin_preset(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        notifications: list[str] = []
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            app.notify = lambda message, **_kwargs: notifications.append(message)
            await pilot.press("3")
            await pilot.pause()
            picker = app.query_one("#profile-picker")
            for index, row in enumerate(picker.rows):
                if row.source_label == "builtin":
                    picker.selected_index = index
                    picker.rebuild()
                    break
            else:  # pragma: no cover - defensive
                raise AssertionError("expected builtin preset in profile picker")
            selected = picker.selected_name()
            await pilot.press("enter")
            await pilot.pause()
            assert app._workspace == "loop"
            assert app._loop_diagram.model.name == selected
            assert any(
                "read-only" in message and "press c to clone" in message
                for message in notifications
            )

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


def test_loop_goto_prompts_applies_selected_asset_to_scalar_prompt(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 1
            await pilot.press("g")
            await pilot.pause()
            assert app._workspace == "prompts"
            assert "PROMPTS" in _render(app, "#prompt-library")
            await pilot.press("enter")
            await pilot.pause()
            assert app._workspace == "loop"
            assert diagram.model.field_value("triage.prompt", None)
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_prompt_edit_sets_scalar_field_on_working_copy(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.commit]\nenabled=true\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 4
            app._apply_prompt_edit(
                "commit.message_prompt", "Use imperative subject lines"
            )
            await pilot.pause()
            assert diagram.model.field_value("commit.message_prompt", None) == (
                "Use imperative subject lines"
            )
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_prompt_contract_only_targets_triage_prompt(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\n"
            "[profiles.edit.commit]\nenabled=true\n",
            encoding="utf-8",
        )
        notifications: list[tuple[str, str | None]] = []
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            app.notify = lambda message, **kwargs: notifications.append(
                (message, kwargs.get("severity"))
            )
            await pilot.press("4")
            await pilot.pause()
            library = app.query_one("#prompt-library")
            for index, asset in enumerate(library.assets):
                if asset.kind == "contract":
                    library.selected_index = index
                    library.rebuild()
                    break
            else:  # pragma: no cover - defensive
                raise AssertionError("expected a contract prompt asset")
            app._prompt_target_key = "commit.message_prompt"
            app._apply_selected_prompt_asset()
            diagram = app.query_one("#loop-diagram")
            assert (
                diagram.model.field_value("commit.message_prompt", None)
                is None
            )
            assert any(
                "can only target triage.prompt" in message and severity == "error"
                for message, severity in notifications
            )

            app._prompt_target_key = "triage.prompt"
            for index, asset in enumerate(library.assets):
                if asset.name == "triage_v2":
                    library.selected_index = index
                    library.rebuild()
                    break
            else:  # pragma: no cover - defensive
                raise AssertionError("expected triage_v2 prompt asset")
            app._apply_selected_prompt_asset()
            assert diagram.model.field_value("triage.contract", None) == "v2"
            assert (
                diagram.model.field_value("triage.prompt", None) is None
            )
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_route_add_and_edit_update_working_copy(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.edit.triage.routes.security]\nharness='codex'\nsandbox='read-only'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 1
            app._apply_route_add("audit")
            app._apply_route_edit("security", "model", "gpt-9")
            await pilot.pause()
            routes = _render(app, "#triage-routes-table")
            assert "> audit:" in routes
            assert (
                diagram.model.field_value("triage.routes.audit.harness", None)
                == "codex"
            )
            assert (
                diagram.model.field_value("triage.routes.audit.sandbox", None)
                == "workspace-write"
            )
            assert (
                diagram.model.field_value("triage.routes.security.model", None)
                == "gpt-9"
            )
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_route_row_edit_rejects_invalid_timeout_atomically(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.edit.triage.routes.security]\nharness='codex'\nsandbox='read-only'\n",
            encoding="utf-8",
        )
        notifications: list[tuple[str, str | None]] = []
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            app.notify = lambda message, **kwargs: notifications.append(
                (message, kwargs.get("severity"))
            )
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            app._apply_route_row_edit(
                "security",
                {"model": "gpt-9", "timeout_seconds": "abc"},
            )
            assert (
                diagram.model.field_value("triage.routes.security.model", None)
                is None
            )
            assert diagram.is_dirty is False
            assert any(
                "timeout_seconds" in message and severity == "error"
                for message, severity in notifications
            )

    asyncio.run(run())


def test_route_row_edit_can_clear_optional_route_fields(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.edit.triage.routes.security]\n"
            "harness='codex'\n"
            "model='gpt-5.4-mini'\n"
            "reasoning_effort='high'\n"
            "timeout_seconds=900\n"
            "sandbox='read-only'\n"
            "fallback='audit'\n"
            "[profiles.edit.triage.routes.audit]\n"
            "harness='codex'\n"
            "sandbox='workspace-write'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            app._apply_route_row_edit(
                "security",
                {
                    "model": "",
                    "reasoning_effort": "",
                    "timeout_seconds": "",
                    "fallback": "",
                },
            )
            assert diagram.model.field_value("triage.routes.security.model", None) == ""
            assert (
                diagram.model.field_value(
                    "triage.routes.security.reasoning_effort", None
                )
                == ""
            )
            assert (
                diagram.model.field_value(
                    "triage.routes.security.timeout_seconds", None
                )
                == ""
            )
            assert diagram.model.field_value("triage.routes.security.fallback", None) == ""
            assert "security: codex · <default> · <default> · <default>" in _render(
                app, "#triage-routes-table"
            )
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_route_edit_rejects_fallback_cycle(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.edit.triage.routes.security]\n"
            "harness='codex'\nsandbox='read-only'\n"
            "[profiles.edit.triage.routes.audit]\n"
            "harness='codex'\nsandbox='workspace-write'\nfallback='security'\n",
            encoding="utf-8",
        )
        notifications: list[tuple[str, str | None]] = []
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            app.notify = lambda message, **kwargs: notifications.append(
                (message, kwargs.get("severity"))
            )
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            app._apply_route_edit("security", "fallback", "audit")
            assert (
                diagram.model.field_value("triage.routes.security.fallback", None)
                is None
            )
            assert diagram.is_dirty is False
            assert any(
                "fallback cycle" in message and severity == "error"
                for message, severity in notifications
            )

    asyncio.run(run())


def test_route_edit_modal_updates_working_copy_through_callback(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.edit.triage.routes.security]\nharness='codex'\nsandbox='read-only'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("enter")
            await pilot.pause()
            model_input = app.screen.query_one("#route-edit-model")
            model_input.value = "gpt-9"
            app.screen.set_focus(model_input)
            await pilot.press("enter")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            assert (
                diagram.model.field_value("triage.routes.security.model", None)
                == "gpt-9"
            )
            assert "gpt-9" in _render(app, "#triage-routes-table")
            assert diagram.is_dirty is True

    asyncio.run(run())


def test_route_edit_modal_saves_select_change_from_keyboard(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.edit.triage.routes.security]\nharness='codex'\nsandbox='read-only'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("enter")
            await pilot.pause()
            sandbox = app.screen.query_one("#route-edit-sandbox")
            app.screen.set_focus(sandbox)
            await pilot.press("enter")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("ctrl+s")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            assert (
                diagram.model.field_value("triage.routes.security.sandbox", None)
                == "workspace-write"
            )
            assert "workspace-write" in _render(app, "#triage-routes-table")

    asyncio.run(run())


def test_route_add_rejects_invalid_and_duplicate_names(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(
            "[profiles.edit]\n[profiles.edit.pipeline]\nbase='main'\n"
            "[profiles.edit.triage]\nenabled=true\ncontract='v2'\n"
            "[profiles.edit.triage.routing]\nenabled=true\ndefault_route='security'\n"
            "[profiles.edit.triage.routes.security]\nharness='codex'\nsandbox='read-only'\n",
            encoding="utf-8",
        )
        async with pilot_app(cwd=repo, profile_name="edit") as (app, pilot):
            await pilot.press("1")
            await pilot.pause()
            diagram = app.query_one("#loop-diagram")
            diagram.focused_index = 1
            app._apply_route_add("bad.name")
            app._apply_route_add("security")
            assert diagram.is_dirty is False

    asyncio.run(run())


def test_tui_pilot_confirmed_launch_reaches_visible_running_state(
    tmp_path, monkeypatch
):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="slow_cancel", artifact_dir="runs/live-launch"
        )
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            try:
                await pilot.press("r")
                await pilot.press("r")

                await _wait_for(
                    lambda: "Live status: running"
                    in _render(app, "#screen-run-monitor"),
                    pilot_pause=pilot.pause,
                )
                assert "Live run started: live" in _render(
                    app, "#screen-run-monitor"
                ) or (app.live_run_controller.launch is not None)
                assert app.live_run_controller.launch is not None
                assert (
                    app.live_run_controller.launch.artifact_dir
                    == repo / "runs/live-launch"
                )
            finally:
                _cancel_live_run(app)

    asyncio.run(run())


def test_run_workspace_mounts_live_loop_and_event_log(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="slow_cancel", artifact_dir="runs/live-mon"
        )
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            try:
                await pilot.press("r")
                await pilot.press("r")
                await _wait_for(
                    lambda: app._workspace == "run"
                    and "live" in _render(app, "#loop-run-header"),
                    pilot_pause=pilot.pause,
                    timeout=LIVE_RUN_PILOT_TIMEOUT,
                )
                assert app.query_one("#loop-run") is not None
                assert app.query_one("#event-log") is not None
                assert any(
                    glyph in _render(app, "#run-phase-review")
                    for glyph in ("▶", "✓", "·")
                )
            finally:
                _cancel_live_run(app)

    asyncio.run(run())


def test_run_workspace_before_launch_shows_empty_state(tmp_path):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="review_clear", artifact_dir="runs/not-started"
        )

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            await pilot.press("2")
            await pilot.pause()
            assert "No active run." in _render(app, "#loop-run-header")

    asyncio.run(run())


def test_run_workspace_toggles_logs_and_shows_artifacts(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="slow_cancel", artifact_dir="runs/live-log"
        )
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])
        notifications: list[str] = []

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            app.notify = lambda message, **_kwargs: notifications.append(message)
            try:
                await pilot.press("r")
                await pilot.press("r")
                await _wait_for(
                    lambda: app.live_run_controller.launch is not None,
                    pilot_pause=pilot.pause,
                    timeout=LIVE_RUN_PILOT_TIMEOUT,
                )
                await pilot.press("l")
                await pilot.pause()
                assert "logs" in _render(app, "#event-log")
                await pilot.press("o")
                await pilot.pause()
                assert any("runs/live-log" in message for message in notifications)
            finally:
                _cancel_live_run(app)

    asyncio.run(run())


def test_artifacts_key_is_run_workspace_scoped(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="slow_cancel", artifact_dir="runs/scoped"
        )
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])
        notifications: list[str] = []

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            app.notify = lambda message, **_kwargs: notifications.append(message)
            try:
                await pilot.press("r")
                await pilot.press("r")
                await _wait_for(
                    lambda: app.live_run_controller.launch is not None,
                    pilot_pause=pilot.pause,
                    timeout=LIVE_RUN_PILOT_TIMEOUT,
                )
                await pilot.press("1")
                await pilot.press("o")
                await pilot.pause()
                assert not any("Artifacts:" in message for message in notifications)
                await pilot.press("2")
                await pilot.press("o")
                await pilot.pause()
                assert any("runs/scoped" in message for message in notifications)
            finally:
                _cancel_live_run(app)

    asyncio.run(run())


def test_help_overlay_lists_run_logs_and_artifacts(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.press("?")
            await pilot.pause()
            help_text = _render(app, "#footer-bar")
            assert "\\[l\\] logs/events" in help_text
            assert "\\[o\\] artifacts" in help_text

    asyncio.run(run())


def test_saved_loop_edit_launches_run_with_matching_live_diagram(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="slow_cancel", artifact_dir="runs/edited-live"
        )
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            try:
                await pilot.press("1")
                await pilot.pause()
                diagram = app.query_one("#loop-diagram")
                diagram.set_loop_meta_field("max_iterations", "3")
                app.action_save_loop()
                await pilot.pause()
                await pilot.press("r")
                await pilot.press("r")
                await _wait_for(
                    lambda: app._workspace == "run"
                    and (
                        "iteration 1/3" in _render(app, "#loop-run-header")
                        or "max 3" in _render(app, "#loop-run-header")
                    ),
                    pilot_pause=pilot.pause,
                    timeout=LIVE_RUN_PILOT_TIMEOUT,
                )
                assert "live" in _render(app, "#loop-run-header")
            finally:
                _cancel_live_run(app)

    asyncio.run(run())


def test_run_workspace_keeps_launched_profile_when_selection_changes(
    tmp_path, monkeypatch
):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        (repo / ".revrem.toml").write_text(
            """
[profiles.alpha]
[profiles.alpha.pipeline]
base = "main"
max_iterations = 3
final_review = false
[profiles.alpha.output]
artifact_dir = "runs/alpha-live"
[profiles.alpha.review]
harness = "fake"
model = "slow_cancel"

[profiles.beta]
[profiles.beta.pipeline]
base = "main"
max_iterations = 9
final_review = false
[profiles.beta.output]
artifact_dir = "runs/beta-live"
[profiles.beta.review]
harness = "fake"
model = "review_clear"
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])

        async with pilot_app(cwd=repo, profile_name="alpha") as (app, pilot):
            try:
                await pilot.press("r")
                await pilot.press("r")
                await _wait_for(
                    lambda: "RUN · alpha" in _render(app, "#loop-run-header"),
                    pilot_pause=pilot.pause,
                    timeout=LIVE_RUN_PILOT_TIMEOUT,
                )
                await pilot.press("3")
                await pilot.press("down")
                await pilot.press("enter")
                await pilot.press("2")
                await pilot.pause()
                header = _render(app, "#loop-run-header")
                assert "RUN · alpha" in header
                assert "beta" not in header
                assert "iteration 1/3" in header or "max 3" in header
            finally:
                _cancel_live_run(app)

    asyncio.run(run())


def test_tui_pilot_live_monitor_updates_and_cancels_visible_run(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="review_findings", artifact_dir="runs/live-cancel"
        )
        monkeypatch.setattr(tui.sys, "argv", [str(repo / "launcher.py")])

        async with pilot_app(cwd=repo, profile_name="live") as (app, pilot):
            try:
                await pilot.press("r")
                await pilot.press("r")

                await _wait_for(
                    lambda: (
                        "phase_start" in _render(app, "#event-log")
                        and "findings-summary (1)" in _render(app, "#event-log")
                    ),
                    pilot_pause=pilot.pause,
                    timeout=LIVE_RUN_PILOT_TIMEOUT,
                )
                await pilot.press("k")
                await _wait_for(
                    lambda: "cancelled" in _render(app, "#loop-run-header"),
                    pilot_pause=pilot.pause,
                    timeout=LIVE_RUN_PILOT_TIMEOUT,
                )

                launch = app.live_run_controller.launch
                assert launch is not None
                summary = json.loads(
                    (launch.artifact_dir / "summary.json").read_text(encoding="utf-8")
                )
                assert summary["stopped_reason"] == "cancelled"
                records, _ = events.read_events(
                    launch.artifact_dir / events.EVENTS_FILENAME
                )
                assert any(record.kind == "cancellation" for record in records)
            finally:
                _cancel_live_run(app)

    asyncio.run(run())


class _FakeLiveController:
    status = "running"

    def __init__(self, snapshot: tui_run_controller.LiveEventSnapshot) -> None:
        self._snapshot = snapshot

    def read_live_events(self) -> tui_run_controller.LiveEventSnapshot:
        return self._snapshot

    def stdout_lines(self) -> tuple[str, ...]:
        return ()

    def stderr_lines(self) -> tuple[str, ...]:
        return ()


def test_loop_run_view_waits_when_events_not_ready(tmp_path):
    async def run() -> None:
        cls = tui_loop_widgets.loop_run_view_class()
        if cls is None:
            pytest.skip("Textual is not installed")
        profile = _loop_run_profile(tmp_path)
        async with _single_widget_app(cls()).run_test() as pilot:
            widget = pilot.app.query_one("#loop-run")
            widget.set_state(
                _FakeLiveController(tui_run_controller.LiveEventSnapshot(ready=False)),
                profile,
            )
            widget.rebuild()
            await pilot.pause()
            assert "events: waiting for events.jsonl" in _render(
                pilot.app, "#loop-run-header"
            )

    asyncio.run(run())


def test_loop_run_view_reports_event_read_errors(tmp_path):
    async def run() -> None:
        cls = tui_loop_widgets.loop_run_view_class()
        if cls is None:
            pytest.skip("Textual is not installed")
        profile = _loop_run_profile(tmp_path)
        async with _single_widget_app(cls()).run_test() as pilot:
            widget = pilot.app.query_one("#loop-run")
            widget.set_state(
                _FakeLiveController(
                    tui_run_controller.LiveEventSnapshot(error="bad json", ready=True)
                ),
                profile,
            )
            widget.rebuild()
            await pilot.pause()
            rendered = _render(pilot.app, "#loop-run-header")
            assert "events: unavailable" in rendered
            assert "bad json" in rendered

    asyncio.run(run())


def test_event_log_waits_when_events_not_ready():
    async def run() -> None:
        cls = tui_loop_widgets.event_log_class()
        if cls is None:
            pytest.skip("Textual is not installed")
        async with _single_widget_app(cls()).run_test() as pilot:
            widget = pilot.app.query_one("#event-log")
            widget.set_controller(
                _FakeLiveController(tui_run_controller.LiveEventSnapshot(ready=False))
            )
            widget.rebuild()
            await pilot.pause()
            assert "waiting for events.jsonl" in _render(pilot.app, "#event-log")

    asyncio.run(run())


def test_tui_pilot_prompt_entry_runs_profile_actions(tmp_path, monkeypatch):
    async def run() -> None:
        repo = init_repo(tmp_path / "repo")
        _write_live_profile(
            repo, review_model="review_clear", artifact_dir="runs/live-prompt"
        )
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
        _write_live_profile(
            repo, review_model="review_clear", artifact_dir="runs/live-prompt-cancel"
        )
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


def _single_widget_app(widget):
    components = tui._load_textual_components()
    if components is None:
        pytest.skip("Textual is not installed")

    class SingleWidgetApp(components.app.App):  # type: ignore[misc, valid-type]
        def compose(self):
            yield widget

    return SingleWidgetApp()


def _loop_run_profile(tmp_path: Path):
    from code_review_loop import profiles

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".revrem.toml").write_text(
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n",
        encoding="utf-8",
    )
    return profiles.resolve_profile("p", cwd=repo, require_implemented=False)


def _cancel_live_run(app) -> None:
    process = app.live_run_controller.process
    if process is not None and process.poll() is None:
        app.live_run_controller.cancel(grace_seconds=1)


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
