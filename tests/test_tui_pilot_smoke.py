from __future__ import annotations

import asyncio

from support.tui_pilot import pilot_app


def test_tui_pilot_boots_home_view(tmp_path):
    async def run() -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        async with pilot_app(cwd=repo, profile_name="security") as (app, pilot):
            await pilot.pause()
            home = app.query_one("#screen-home")
            rendered = str(home.render())
            assert "Workspace:" in rendered
            assert str(repo) in rendered
            status = app.query_one("#status-bar")
            assert "profile security" in str(status.render())
            help_panel = app.query_one("#screen-help")
            assert "Press [h] for full keybindings." in str(help_panel.render())
            app.action_toggle_help()
            await pilot.pause()
            assert "confirm/start live run" in str(help_panel.render())

    asyncio.run(run())
