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


def install_fake_rich(monkeypatch):
    FakeConsole.printed = []
    rich_module = types.ModuleType("rich")
    console_module = types.ModuleType("rich.console")
    text_module = types.ModuleType("rich.text")
    console_module.Console = FakeConsole
    text_module.Text = FakeText
    monkeypatch.setitem(sys.modules, "rich", rich_module)
    monkeypatch.setitem(sys.modules, "rich.console", console_module)
    monkeypatch.setitem(sys.modules, "rich.text", text_module)


def test_rich_event_uses_text_objects_so_markup_in_output_is_literal(monkeypatch):
    install_fake_rich(monkeypatch)

    assert progress.print_rich_event("review", "3", "issue", "bad [/]")

    rendered = FakeConsole.printed[0]
    assert isinstance(rendered, FakeText)
    assert ("review", "bold green") in rendered.parts
    assert ("issue", "green") in rendered.parts
    assert (": bad [/]", None) in rendered.parts


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
