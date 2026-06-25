from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from code_review_loop import profiles, tui, tui_state


@asynccontextmanager
async def pilot_app(
    *,
    cwd: Path,
    home: Path | None = None,
    profile_name: str | None = None,
    fake_harness: bool = True,
) -> AsyncIterator[tuple[tui.RevRemApp, object]]:
    previous_fake = os.environ.get("REVREM_ALLOW_FAKE_HARNESS")
    if fake_harness:
        os.environ["REVREM_ALLOW_FAKE_HARNESS"] = "1"
    else:
        os.environ.pop("REVREM_ALLOW_FAKE_HARNESS", None)
    try:
        model = tui_state.build_shell_model(
            cwd=cwd,
            home=home,
            selected_profile_name=profile_name,
        )
        profiles_by_name = {
            profile.name: profile
            for profile in profiles.resolve_profiles(
                cwd=cwd,
                home=home,
                require_implemented=False,
                include_builtins=True,
            )
        }
        app = tui.RevRemApp(model=model, profiles_by_name=profiles_by_name)
        async with app.run_test() as pilot:
            yield app, pilot
    finally:
        if previous_fake is None:
            os.environ.pop("REVREM_ALLOW_FAKE_HARNESS", None)
        else:
            os.environ["REVREM_ALLOW_FAKE_HARNESS"] = previous_fake
