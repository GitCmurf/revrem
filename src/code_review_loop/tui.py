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

from code_review_loop import profiles, tui_state

INSTALL_HINT = "Install it with: python -m pip install 'revrem[tui]'"


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
    input_widget: Any | None = getattr(widgets, "Input", None)
    tabbed_content: Any | None = getattr(widgets, "TabbedContent", None)
    tab_pane: Any | None = getattr(widgets, "TabPane", None)

    class RevRemApp(app_base):  # type: ignore[misc, valid-type]
        CSS = """
        Screen {
            layout: vertical;
        }

        #body {
            height: 1fr;
            padding: 1 2;
        }

        #profile-name, #profile-path {
            margin: 0 2 1 2;
        }

        .panel-title {
            text-style: bold;
        }
        """
        BINDINGS = [
            ("d", "launch_dry_run", "Dry run"),
            ("s", "show_profile", "Show"),
            ("e", "edit_profile", "Edit profile"),
            ("n", "new_profile", "New"),
            ("c", "clone_profile", "Clone"),
            ("x", "export_profile", "Export"),
            ("i", "import_profiles", "Import"),
            ("delete", "delete_profile", "Delete"),
            ("q", "quit", "Quit"),
        ]

        def compose(self):
            yield header(show_clock=True)
            if tabbed_content is not None and tab_pane is not None:
                with tabbed_content():
                    for screen in model.screens:
                        with tab_pane(screen.title):
                            yield static(_screen_markup(screen), id=f"screen-{screen.name}", markup=True)
                    with tab_pane("Controls"):
                        if input_widget is not None:
                            yield input_widget(
                                value=model.selected_profile_name or "",
                                placeholder="profile name",
                                id="profile-name",
                            )
                            yield input_widget(
                                placeholder="import path",
                                id="profile-path",
                            )
                        yield static(
                            _controls_markup(model.selected_profile_name),
                            id="screen-controls",
                            markup=True,
                        )
            else:
                yield static(
                    tui_state.render_shell_text(model),
                    id="body",
                    markup=True,
                )
            yield footer()

        def action_launch_dry_run(self) -> None:
            profile_name = self._profile_name()
            selected = self._profile_by_name(profile_name)
            if selected is None:
                _notify(self, "No profile is available to dry-run.")
                return
            plan = tui_state.launch_plan(selected, dry_run=True)
            result = run_launch_plan(plan, cwd=Path(model.snapshot.cwd))
            if result.returncode == 0:
                _notify(self, f"Dry run completed: {profile_name}")
                return
            _notify(self, f"Dry run failed with exit {result.returncode}: {profile_name}")

        def action_show_profile(self) -> None:
            profile_name = self._profile_name()
            if profile_name is None:
                _notify(self, "No profile is available to show.")
                return
            self._run_interactive(tui_state.show_plan_for_name(profile_name), success=f"Shown profile: {profile_name}")

        def action_edit_profile(self) -> None:
            profile_name = self._profile_name()
            if profile_name is None:
                _notify(self, "No profile is available to edit.")
                return
            self._run_interactive(tui_state.edit_plan_for_name(profile_name), success=f"Edited profile: {profile_name}")

        def action_new_profile(self) -> None:
            profile_name = self._profile_name()
            if profile_name is None:
                _notify(self, "Enter a profile name before creating a profile.")
                return
            self._run_captured(tui_state.new_plan_for_name(profile_name), success=f"Created profile: {profile_name}")

        def action_clone_profile(self) -> None:
            source = model.selected_profile_name
            target = self._profile_name()
            if source is None:
                _notify(self, "No profile is available to clone.")
                return
            if target is None or target == source:
                target = f"{source}-copy"
            self._run_captured(
                tui_state.clone_plan_for_name(source, target),
                success=f"Cloned profile: {source} -> {target}",
            )

        def action_delete_profile(self) -> None:
            profile_name = self._profile_name()
            if profile_name is None:
                _notify(self, "No profile is available to delete.")
                return
            self._run_captured(
                tui_state.delete_plan_for_name(profile_name),
                success=f"Deleted profile: {profile_name}",
            )

        def action_export_profile(self) -> None:
            profile_name = self._profile_name()
            if profile_name is None:
                _notify(self, "No profile is available to export.")
                return
            self._run_interactive(
                tui_state.export_plan_for_name(profile_name),
                success=f"Exported profile: {profile_name}",
            )

        def action_import_profiles(self) -> None:
            path = self._path_value()
            if path is None:
                _notify(self, "Enter an import path before importing profiles.")
                return
            self._run_captured(tui_state.import_plan_for_path(path), success=f"Imported profiles: {path}")

        def _run_interactive(self, plan: tui_state.LaunchPlan, *, success: str) -> None:
            result = self._run_plan(plan, capture_output=False)
            if result.returncode == 0:
                _notify(self, success)
                return
            _notify(self, f"{plan.mode} failed with exit {result.returncode}: {plan.profile_name}")

        def _run_captured(self, plan: tui_state.LaunchPlan, *, success: str) -> None:
            result = self._run_plan(plan, capture_output=True)
            if result.returncode == 0:
                _notify(self, success)
                return
            _notify(self, f"{plan.mode} failed with exit {result.returncode}: {plan.profile_name}")

        def _run_plan(
            self,
            plan: tui_state.LaunchPlan,
            *,
            capture_output: bool,
        ) -> subprocess.CompletedProcess[str]:
            suspend = getattr(self, "suspend", None)
            if callable(suspend) and not capture_output:
                with suspend():
                    return run_launch_plan(plan, cwd=Path(model.snapshot.cwd), capture_output=False)
            return run_launch_plan(plan, cwd=Path(model.snapshot.cwd), capture_output=capture_output)

        def _profile_name(self) -> str | None:
            value = _input_value(self, "#profile-name")
            if value:
                return value
            return model.selected_profile_name

        def _path_value(self) -> str | None:
            return _input_value(self, "#profile-path")

        def _profile_by_name(self, profile_name: str | None) -> Any | None:
            if profile_name is None:
                return None
            return profiles_by_name.get(profile_name)

    profiles_by_name = {
        profile.name: profile
        for profile in profiles.resolve_profiles(
            cwd=Path(model.snapshot.cwd),
            require_implemented=False,
        )
    }
    RevRemApp().run()


def _screen_markup(screen: tui_state.TuiScreen) -> str:
    escaped_lines = "\n".join(tui_state.markup_escape(line) for line in screen.lines)
    return f"[b]{tui_state.markup_escape(screen.title)}[/b]\n{escaped_lines}"


def _controls_markup(selected_profile_name: str | None) -> str:
    selected = selected_profile_name or "<none>"
    return (
        f"[b]Selected[/b]\n{tui_state.markup_escape(selected)}\n\n"
        "[b]Profile lifecycle[/b]\n"
        "d dry-run | s show | e edit | n new | c clone | x export | i import | delete delete\n\n"
        "[b]Notes[/b]\n"
        "Use the profile field for target profile actions. Use the path field for TOML imports."
    )


def _input_value(app: Any, selector: str) -> str | None:
    query_one = getattr(app, "query_one", None)
    if not callable(query_one):
        return None
    try:
        widget = query_one(selector)
    except Exception:
        return None
    value = getattr(widget, "value", None)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None

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
