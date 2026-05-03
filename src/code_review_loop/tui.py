"""Optional Textual TUI entry point for RevRem."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from code_review_loop import tui_state

INSTALL_HINT = "Install it with: python -m pip install 'code-review-loop[tui]'"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    if args.dry_run:
        print("RevRem TUI entry point is available.")
        return 0
    if importlib.util.find_spec("textual") is None:
        print(f"ERROR: revrem ui requires the optional Textual dependency. {INSTALL_HINT}", file=sys.stderr)
        return 1
    run_textual_app()
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
    return parser.parse_args(argv)


def run_textual_app() -> None:
    snapshot = tui_state.build_home_snapshot(cwd=Path.cwd())
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
        BINDINGS = [("q", "quit", "Quit")]

        def compose(self):
            yield header(show_clock=True)
            yield static(
                "\n".join(
                    [
                        "[b]RevRem[/b]",
                        "",
                        f"Workspace: {snapshot.cwd}",
                        f"Profiles: {len(snapshot.profiles)} available",
                        f"Recent runs: {len(snapshot.recent_runs)} loaded",
                        f"Artifact links: {sum(len(run.artifacts) for run in snapshot.run_monitors)} indexed",
                        "Implemented harnesses: "
                        + ", ".join(h.name for h in snapshot.harnesses if h.implemented),
                        "Quick start: "
                        + (
                            snapshot.run_previews[0].shell_command
                            if snapshot.run_previews
                            else "revrem config new final-pr"
                        ),
                        "",
                        "Home: recent runs and quick-start profiles",
                        "Profiles: create, inspect, import, and export TOML profiles",
                        "Pipeline: review, triage, remediation, checks, and commit phases",
                        "Run Monitor: phase state, progress output, artifacts, and summaries",
                    ]
                ),
                id="body",
            )
            yield footer()

    RevRemApp().run()
