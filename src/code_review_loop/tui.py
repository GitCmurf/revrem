"""Optional Textual TUI entry point for RevRem."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from code_review_loop import tui_state

INSTALL_HINT = "Install it with: python -m pip install 'code-review-loop[tui]'"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.dry_run:
        print("RevRem TUI entry point is available.")
        return 0
    if importlib.util.find_spec("textual") is None:
        print(f"ERROR: revrem ui requires the optional Textual dependency. {INSTALL_HINT}", file=sys.stderr)
        return 1
    try:
        run_textual_app(selected_profile_name=args.profile)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="revrem ui",
        description="Launch the optional RevRem Textual interface.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the TUI entry point without importing or launching Textual.",
    )
    parser.add_argument(
        "--profile",
        help="Select the initial profile shown in the TUI.",
    )
    return parser.parse_args(argv)


def run_textual_app(*, selected_profile_name: str | None = None) -> None:
    model = tui_state.build_shell_model(cwd=Path.cwd(), selected_profile_name=selected_profile_name)
    textual_app = importlib.import_module("textual.app")
    widgets = importlib.import_module("textual.widgets")

    app_base: Any = textual_app.App
    header: Any = widgets.Header
    footer: Any = widgets.Footer
    static: Any = widgets.Static

    class RevRemApp(app_base):  # type: ignore[misc, valid-type]
        CSS = """
        Screen {
            layout: vertical;
        }

        #body {
            height: 1fr;
            padding: 1 2;
        }

        .panel-title {
            text-style: bold;
        }
        """
        BINDINGS = [
            ("d", "launch_dry_run", "Dry run"),
            ("e", "edit_profile", "Edit profile"),
            ("q", "quit", "Quit"),
        ]

        def compose(self):
            yield header(show_clock=True)
            yield static(
                tui_state.render_shell_text(model),
                id="body",
                markup=True,
            )
            yield footer()

        def action_launch_dry_run(self) -> None:
            if model.selected_launch_plan is None:
                _notify(self, "No profile is available to dry-run.")
                return
            result = run_launch_plan(model.selected_launch_plan, cwd=Path(model.snapshot.cwd))
            if result.returncode == 0:
                _notify(self, f"Dry run completed: {model.selected_launch_plan.profile_name}")
                return
            _notify(self, f"Dry run failed with exit {result.returncode}: {model.selected_launch_plan.profile_name}")

        def action_edit_profile(self) -> None:
            if model.selected_profile_name is None:
                _notify(self, "No profile is available to edit.")
                return
            plan = tui_state.edit_plan_for_name(model.selected_profile_name)
            suspend = getattr(self, "suspend", None)
            if callable(suspend):
                with suspend():
                    result = run_launch_plan(plan, cwd=Path(model.snapshot.cwd), capture_output=False)
            else:
                result = run_launch_plan(plan, cwd=Path(model.snapshot.cwd), capture_output=False)
            if result.returncode == 0:
                _notify(self, f"Edited profile: {model.selected_profile_name}")
                return
            _notify(self, f"Profile edit failed with exit {result.returncode}: {model.selected_profile_name}")

    RevRemApp().run()


def run_launch_plan(
    plan: tui_state.LaunchPlan,
    *,
    cwd: Path,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    argv = current_entrypoint_argv(plan.argv)
    return subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        capture_output=capture_output,
        check=False,
    )


def current_entrypoint_argv(argv: Sequence[str]) -> list[str]:
    resolved = list(argv)
    if not resolved or resolved[0] != "revrem":
        return resolved
    launcher = Path(sys.argv[0])
    if launcher.name in {"revrem", "code-review-loop"} and launcher.exists():
        resolved[0] = str(launcher)
        return resolved
    if launcher.suffix == ".py":
        # Preserve a runnable entrypoint when the TUI itself was started with `python -m`.
        return [sys.executable, "-m", "code_review_loop", *resolved[1:]]
    return resolved


def _notify(app: Any, message: str) -> None:
    notify = getattr(app, "notify", None)
    if callable(notify):
        notify(message)
    else:
        print(message)
