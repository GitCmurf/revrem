"""Tests for ProgressReporter protocol and TerminalProgressReporter adapter (B4)."""

from __future__ import annotations

from support.fakes import FakeClock, FakeRunIdentity  # noqa: E402
from support.phase_harnesses import phase_harness_kwargs  # noqa: E402

from code_review_loop.adapters.phase_support import progress_event
from code_review_loop.adapters.terminal import TerminalProgressReporter  # noqa: E402
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import ProgressReporter, RunContext  # noqa: E402


class RecordingReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def phase(self, phase: str, label: str, status: str, detail: str = "") -> None:
        self.calls.append((phase, label, status, detail))


def _make_ctx(reporter: ProgressReporter | None = None) -> RunContext:
    return RunContext(
        clock=FakeClock(),
        identity=FakeRunIdentity(),
        runner=None,
        **phase_harness_kwargs(),
        event_sink=None,
        budget_state=None,
        progress_reporter=reporter,
    )


def _make_config(tmp_path, *, progress: bool = True, progress_style: str = "compact"):
    return LoopConfig(
        base="main",
        max_iterations=1,
        codex_bin="codex",
        cwd=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        progress=progress,
        progress_style=progress_style,
    )


# ---------------------------------------------------------------------------
# 1. RecordingReporter captures phase calls
# ---------------------------------------------------------------------------


def test_recording_reporter_captures_phase_calls():
    reporter = RecordingReporter()
    reporter.phase("review", "1", "start", "some detail")
    reporter.phase("triage", "2", "clear")
    assert reporter.calls == [
        ("review", "1", "start", "some detail"),
        ("triage", "2", "clear", ""),
    ]


# ---------------------------------------------------------------------------
# 2. progress_event delegates to reporter when injected
# ---------------------------------------------------------------------------


def test_progress_event_delegates_to_reporter_when_injected(tmp_path, capsys):
    reporter = RecordingReporter()
    ctx = _make_ctx(reporter)
    config = _make_config(tmp_path, progress=True, progress_style="compact")

    progress_event(config, "review", "1", "start", "detail text", ctx=ctx)

    assert reporter.calls == [("review", "1", "start", "detail text")]
    # No output to stderr — the reporter was invoked instead of legacy path
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# 3. progress_event falls back to legacy when ctx.progress_reporter is None
# ---------------------------------------------------------------------------


def test_progress_event_skips_reporter_when_none(tmp_path, capsys):
    ctx = _make_ctx(None)
    config = _make_config(tmp_path, progress=True, progress_style="compact")

    progress_event(config, "review", "1", "start", "detail", ctx=ctx)

    # Legacy compact path writes to stderr
    err = capsys.readouterr().err
    assert "start: detail" in err


# ---------------------------------------------------------------------------
# 4. TerminalProgressReporter compact style writes to stderr
# ---------------------------------------------------------------------------


def test_terminal_reporter_compact_style(tmp_path, capsys):
    reporter = TerminalProgressReporter("compact")
    reporter.phase("review", "1", "clear")
    err = capsys.readouterr().err
    assert "clear" in err


def test_terminal_reporter_compact_style_with_detail(tmp_path, capsys):
    reporter = TerminalProgressReporter("compact")
    reporter.phase("review", "1", "start", "codex review --base main")
    err = capsys.readouterr().err
    assert "start: codex review --base main" in err


# ---------------------------------------------------------------------------
# 5. TerminalProgressReporter rich style warns once per instance when unavailable
# ---------------------------------------------------------------------------


def test_terminal_reporter_rich_fallback_warns_once(monkeypatch, capsys):
    import code_review_loop.progress as prog

    monkeypatch.setattr(prog, "print_rich_event", lambda *a, **k: False)

    reporter = TerminalProgressReporter("rich")
    reporter.phase("review", "1", "start", "detail")
    reporter.phase("review", "1", "clear")

    err = capsys.readouterr().err
    assert err.count("rich progress unavailable") == 1


# ---------------------------------------------------------------------------
# 6. Two separate instances each warn once independently
# ---------------------------------------------------------------------------


def test_terminal_reporter_rich_fallback_instance_isolation(monkeypatch, capsys):
    import code_review_loop.progress as prog

    monkeypatch.setattr(prog, "print_rich_event", lambda *a, **k: False)

    r1 = TerminalProgressReporter("rich")
    r2 = TerminalProgressReporter("rich")
    r1.phase("review", "1", "start")
    r2.phase("review", "2", "start")

    err = capsys.readouterr().err
    assert err.count("rich progress unavailable") == 2
