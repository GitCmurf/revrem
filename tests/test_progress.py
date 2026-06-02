from __future__ import annotations

import sys
import types

from code_review_loop import progress


class FakeText:
    def __init__(self):
        self.parts = []

    def append(self, value, style=None):
        self.parts.append((value, style))


class FakeConsole:
    printed = []

    def __init__(self, *args, **kwargs):
        pass

    def print(self, value):
        if isinstance(value, str) and "[/]" in value:
            raise RuntimeError("closing tag has nothing to close")
        self.printed.append(value)


class FakeGroup:
    def __init__(self, *items):
        self.items = items


class FakePanel:
    def __init__(self, value, **kwargs):
        self.value = value
        self.kwargs = kwargs


class FakeLive:
    updates = []

    def __init__(self, value, **kwargs):
        self.value = value
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, value):
        self.updates.append(value)


def install_fake_rich(monkeypatch):
    FakeConsole.printed = []
    FakeLive.updates = []
    rich_module = types.ModuleType("rich")
    console_module = types.ModuleType("rich.console")
    live_module = types.ModuleType("rich.live")
    panel_module = types.ModuleType("rich.panel")
    text_module = types.ModuleType("rich.text")
    console_module.Console = FakeConsole
    console_module.Group = FakeGroup
    live_module.Live = FakeLive
    panel_module.Panel = FakePanel
    text_module.Text = FakeText
    monkeypatch.setitem(sys.modules, "rich", rich_module)
    monkeypatch.setitem(sys.modules, "rich.console", console_module)
    monkeypatch.setitem(sys.modules, "rich.live", live_module)
    monkeypatch.setitem(sys.modules, "rich.panel", panel_module)
    monkeypatch.setitem(sys.modules, "rich.text", text_module)


def test_rich_event_uses_text_objects_so_markup_in_output_is_literal(monkeypatch):
    install_fake_rich(monkeypatch)

    assert progress.print_rich_event("review", "3", "issue", "bad [/]")

    rendered = FakeConsole.printed[0]
    assert isinstance(rendered, FakeText)
    assert ("review", "bold green") in rendered.parts
    assert ("issue", "green") in rendered.parts
    assert (": bad [/]", None) in rendered.parts


def test_rich_event_collapses_multiline_detail(monkeypatch):
    install_fake_rich(monkeypatch)

    assert progress.print_rich_event("triage", "1", "start", "first\n\nsecond")

    rendered = FakeConsole.printed[0]
    assert isinstance(rendered, FakeText)
    assert (": first second", None) in rendered.parts


def test_rich_event_styles_structured_start_detail(monkeypatch):
    install_fake_rich(monkeypatch)

    assert progress.print_rich_event(
        "review",
        "1",
        "start",
        (
            "opencode run · opencode/minimax-m3-free · low effort · "
            "timeout=0 · sandbox read-only · prompt=126.7k stdin · source=mixed"
        ),
    )

    rendered = FakeConsole.printed[0]
    assert isinstance(rendered, FakeText)
    assert ("review", "bold green") in rendered.parts
    assert ("start", "green") in rendered.parts
    assert ("opencode run", "bold") in rendered.parts
    assert ("opencode/minimax-m3-free", "magenta") in rendered.parts
    assert ("prompt=126.7k stdin", "blue") in rendered.parts


def test_rich_message_and_continuation_escape_markup_like_text(monkeypatch):
    install_fake_rich(monkeypatch)

    assert progress.print_rich_message("review", "3", "path [/]", head="[P2]   ")
    assert progress.print_rich_continuation("review", "3", "detail [/]", indent=7)

    message = FakeConsole.printed[0]
    continuation = FakeConsole.printed[1]
    assert isinstance(message, FakeText)
    assert isinstance(continuation, FakeText)
    assert ("review", "bold green") in message.parts
    assert ("path [/]", None) in message.parts
    assert ("detail [/]", None) in continuation.parts


def test_rich_live_progress_updates_panel_in_place(monkeypatch):
    install_fake_rich(monkeypatch)

    with progress.rich_live_progress(True) as active:
        assert active is True
        assert progress.print_rich_event("review", "1", "start", "codex review")
        assert progress.print_rich_event("review", "1", "clear")

    assert FakeConsole.printed == []
    assert len(FakeLive.updates) == 2
    latest = FakeLive.updates[-1]
    assert isinstance(latest, FakePanel)
    assert isinstance(latest.value, FakeGroup)
    assert len(latest.value.items) == 2


def test_rich_live_progress_keeps_panel_compact(monkeypatch):
    install_fake_rich(monkeypatch)

    with progress.rich_live_progress(True) as active:
        assert active is True
        for index in range(progress.RICH_LIVE_MAX_LINES + 3):
            assert progress.print_rich_event("review", str(index), "issue", "x" * 300)

    latest = FakeLive.updates[-1]
    assert latest.kwargs["title"] == "RevRem"
    assert len(latest.value.items) == progress.RICH_LIVE_MAX_LINES
    last_line = latest.value.items[-1]
    rendered_values = [value for value, _style in last_line.parts]
    assert "x" * 300 not in rendered_values
    assert any(value.endswith("…") for value in rendered_values)
