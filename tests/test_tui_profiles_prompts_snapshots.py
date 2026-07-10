from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from support.snapshot import assert_svg_snapshot, normalize_svg
from support.tui_pilot import configure_test_app, pilot_app, tui_test_environment

from code_review_loop import tui, tui_loop_widgets


def test_profile_picker_snapshot(tmp_path: Path) -> None:
    svg = _capture_workspace_svg(
        tmp_path,
        "3",
        """
[profiles.alpha]
[profiles.alpha.pipeline]
base = "main"
max_iterations = 3
[profiles.beta]
[profiles.beta.pipeline]
base = "main"
max_iterations = 9
""",
        profile_name="alpha",
    )
    assert "PROFILES" in svg and "alpha" in svg
    assert_svg_snapshot("tui_profiles_prompts/profile-picker", svg)


def test_prompt_library_snapshot(tmp_path: Path) -> None:
    svg = _capture_workspace_svg(
        tmp_path,
        "4",
        """
[profiles.demo]
[profiles.demo.pipeline]
base = "main"
""",
    )
    assert "PROMPTS" in svg and "security-checklist" in svg
    assert_svg_snapshot("tui_profiles_prompts/prompt-library", svg)


def test_route_selection_snapshot(tmp_path: Path) -> None:
    async def run() -> str:
        repo = _repo(
            tmp_path,
            """
[profiles.demo]
[profiles.demo.pipeline]
base = "main"
[profiles.demo.triage]
enabled = true
contract = "v2"
[profiles.demo.triage.routing]
enabled = true
default_route = "security"
[profiles.demo.triage.routes.security]
harness = "codex"
model = "gpt-5.5"
sandbox = "read-only"
[profiles.demo.triage.routes.nit]
harness = "claude"
model = "haiku-4.5"
sandbox = "read-only"
""",
        )
        async with pilot_app(cwd=repo, profile_name="demo", size=(120, 40)) as (
            app,
            pilot,
        ):
            await pilot.press("1")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            return normalize_svg(
                app.export_screenshot(title="revrem-routes", simplify=True)
            )

    svg = asyncio.run(run())
    assert "security" in svg and "fallback" in svg
    assert_svg_snapshot("tui_profiles_prompts/route-selection", svg)


def test_route_edit_modal_snapshot() -> None:
    svg = _capture_route_modal_svg()
    assert "Route: security" in svg and "sandbox" in svg
    assert_svg_snapshot("tui_profiles_prompts/route-edit-modal", svg)


def _capture_workspace_svg(
    tmp_path: Path, key: str, profile_toml: str, *, profile_name: str = "demo"
) -> str:
    async def run() -> str:
        repo = _repo(tmp_path, profile_toml)
        async with pilot_app(cwd=repo, profile_name=profile_name, size=(120, 40)) as (
            app,
            pilot,
        ):
            await pilot.press(key)
            await pilot.pause()
            return normalize_svg(
                app.export_screenshot(title="revrem-workspace", simplify=True)
            )

    return asyncio.run(run())


def _capture_route_modal_svg() -> str:
    async def run() -> str:
        modal_cls = tui_loop_widgets.route_edit_modal_class()
        components = tui._load_textual_components()
        if modal_cls is None or components is None:
            pytest.skip("Textual is not installed")

        class ModalApp(components.app.App):  # type: ignore[misc, valid-type]
            CSS = """
            RouteEditModal {
                align: center middle;
            }
            #route-edit-dialog {
                width: 64;
                height: auto;
                border: round $accent;
                background: $surface;
                padding: 1 2;
            }
            """

            def on_mount(self) -> None:
                self.push_screen(
                    modal_cls(
                        route="security",
                        values={
                            "harness": "codex",
                            "model": "gpt-5.5",
                            "reasoning_effort": "high",
                            "timeout_seconds": "600",
                            "sandbox": "read-only",
                            "fallback": "",
                        },
                        route_names=("security", "fallback-route"),
                    )
                )

        with tui_test_environment():
            app = ModalApp()
            configure_test_app(app)
            async with app.run_test(size=(96, 32)) as pilot:
                await pilot.pause()
                return normalize_svg(
                    pilot.app.export_screenshot(title="revrem-route-modal", simplify=True)
                )

    return asyncio.run(run())


def _repo(tmp_path: Path, profile_toml: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".revrem.toml").write_text(profile_toml, encoding="utf-8")
    return repo
