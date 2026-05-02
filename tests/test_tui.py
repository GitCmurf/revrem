from __future__ import annotations

import importlib.util
import sys
import types

from code_review_loop import cli, tui


def test_tui_dry_run_does_not_require_textual(capsys):
    assert cli.main(["ui", "--dry-run"]) == 0

    captured = capsys.readouterr()
    assert "RevRem TUI entry point is available." in captured.out
    assert captured.err == ""


def test_tui_reports_missing_optional_dependency(monkeypatch, capsys):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args, **kwargs):
        if name == "textual":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(tui.importlib.util, "find_spec", fake_find_spec)

    assert cli.main(["ui"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "requires the optional Textual dependency" in captured.err
    assert "code-review-loop[tui]" in captured.err


def test_tui_launches_textual_app_with_home_snapshot(monkeypatch, tmp_path):
    rendered_widgets = []
    launched = []

    class FakeApp:
        def run(self):
            launched.append(type(self).__name__)
            rendered_widgets.extend(list(self.compose()))

    class FakeWidget:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    app_module = types.ModuleType("textual.app")
    widgets_module = types.ModuleType("textual.widgets")
    app_module.App = FakeApp
    widgets_module.Header = FakeWidget
    widgets_module.Footer = FakeWidget
    widgets_module.Static = FakeWidget
    monkeypatch.setitem(sys.modules, "textual.app", app_module)
    monkeypatch.setitem(sys.modules, "textual.widgets", widgets_module)
    monkeypatch.setattr(tui.importlib.util, "find_spec", lambda name: object() if name == "textual" else None)
    monkeypatch.setattr(tui.Path, "cwd", lambda: tmp_path)

    assert cli.main(["ui"]) == 0

    assert launched == ["RevRemApp"]
    body = rendered_widgets[1]
    assert body.kwargs["id"] == "body"
    assert f"Workspace: {tmp_path}" in body.args[0]
    assert "Pipeline: review, triage, remediation, checks, and commit phases" in body.args[0]
