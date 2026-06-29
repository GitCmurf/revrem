from __future__ import annotations

import asyncio
import difflib
import os
import re
from pathlib import Path

from support.tui_pilot import pilot_app

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots" / "tui_loop"


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
    assert "review" in svg and "triage" in svg and "final review off" in svg
    _assert_svg_snapshot("triage-disabled-final-off", svg)


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
    )
    assert "security" in svg and "haiku-4.5" in svg
    _assert_svg_snapshot("triage-routes", svg)


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
    assert "inner retry" in svg
    _assert_svg_snapshot("inner-retries", svg)


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
    _assert_svg_snapshot("final-review-on", svg)


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
    assert "demo*" in svg and "gpt-5.6" in svg
    _assert_svg_snapshot("dirty-edit", svg)


def _capture_loop_svg(
    tmp_path: Path,
    profile_toml: str,
    *,
    focus_delta: int = 0,
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
            await pilot.pause()
            if edit_model is not None:
                diagram = app.query_one("#loop-diagram")
                diagram.set_text_field("model", edit_model)
                app._update_console_status()
                await pilot.pause()
            return _normalize_svg(app.export_screenshot(title="revrem-loop", simplify=True))

    return asyncio.run(run())


def _normalize_svg(svg: str) -> str:
    normalized = svg.replace("&#160;", " ")
    normalized = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM)?\b", "<time>", normalized)
    normalized = re.sub(r"pytest-\d+", "pytest-N", normalized)
    normalized = re.sub(r"terminal-\d+", "terminal-ID", normalized)
    return normalized


def _assert_svg_snapshot(name: str, svg: str) -> None:
    assert svg.startswith("<svg")
    assert len(svg) > 1000
    path = SNAPSHOT_DIR / f"{name}.svg"
    should_update = os.environ.get("REVREM_UPDATE_SNAPSHOTS") == "1"
    if should_update or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
        return
    expected = path.read_text(encoding="utf-8")
    if svg != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                svg.splitlines(keepends=True),
                fromfile=f"{path} (committed)",
                tofile=f"{path} (actual)",
            )
        )
        raise AssertionError(f"SVG snapshot changed for {name}:\n{diff}")
