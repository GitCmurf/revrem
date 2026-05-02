from __future__ import annotations

import importlib.util

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
