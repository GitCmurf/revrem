from __future__ import annotations

import asyncio
from pathlib import Path

from support.snapshot import assert_svg_snapshot, normalize_svg
from support.tui_pilot import pilot_app


def test_loop_snapshot_triage_disabled_final_off(tmp_path: Path) -> None:
    svg = _capture_loop_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
base = "main"
max_iterations = 2
final_review = false
[profiles.demo.triage]
enabled = false
""",
    )
    assert "REVIEW" in svg and "TRIAGE" in svg and "final review off" in svg
    assert_svg_snapshot("tui_loop/triage-disabled-final-off", svg)


def test_loop_snapshot_triage_routes(tmp_path: Path) -> None:
    svg = _capture_loop_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
base = "main"
max_iterations = 3
final_review = false
[profiles.demo.triage]
enabled = true
contract = "v2"
[profiles.demo.triage.routing]
enabled = true
default_route = "security"
[profiles.demo.triage.routes.security]
harness = "codex"
model = "gpt-5.5"
reasoning_effort = "high"
sandbox = "read-only"
fallback = "nit"
[profiles.demo.triage.routes.nit]
harness = "claude"
model = "haiku-4.5"
        sandbox = "read-only"
""",
        focus_delta=1,
        expand_focused=True,
    )
    assert "security" in svg and "haiku-4.5" in svg
    assert_svg_snapshot("tui_loop/triage-routes", svg)


def test_loop_snapshot_inner_retries(tmp_path: Path) -> None:
    svg = _capture_loop_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
base = "main"
max_iterations = 4
final_review = false
[profiles.demo.runtime]
inner_check_retries = 2
""",
    )
    assert "INNER RETRY" in svg and "OUTER LOOP" in svg
    assert_svg_snapshot("tui_loop/inner-retries", svg)


def test_loop_snapshot_final_review_on(tmp_path: Path) -> None:
    svg = _capture_loop_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
base = "main"
max_iterations = 4
final_review = true
""",
    )
    assert "final review on" in svg
    assert_svg_snapshot("tui_loop/final-review-on", svg)


def test_loop_snapshot_dirty_edit(tmp_path: Path) -> None:
    svg = _capture_loop_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
base = "main"
[profiles.demo.review]
model = "gpt-5.5"
""",
        edit_model="gpt-5.6",
    )
    assert "demo" in svg and "*" in svg and "gpt-5.6" in svg
    assert_svg_snapshot("tui_loop/dirty-edit", svg)


def _capture_loop_svg(
    tmp_path: Path,
    profile_toml: str,
    *,
    focus_delta: int = 0,
    expand_focused: bool = False,
    edit_model: str | None = None,
) -> str:
    async def run() -> str:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".revrem.toml").write_text(profile_toml, encoding="utf-8")
        async with pilot_app(cwd=repo, profile_name="demo", size=(120, 40)) as (app, pilot):
            await pilot.press("1")
            for _ in range(focus_delta):
                await pilot.press("down")
            if expand_focused:
                await pilot.press("enter")
            await pilot.pause()
            if edit_model is not None:
                diagram = app.query_one("#loop-diagram")
                diagram.set_text_field("model", edit_model)
                app._update_console_status()
                await pilot.pause()
            return normalize_svg(app.export_screenshot(title="revrem-loop", simplify=True))

    return asyncio.run(run())
