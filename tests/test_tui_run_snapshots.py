from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from support.snapshot import assert_svg_snapshot, normalize_svg

from code_review_loop import events, profiles, tui, tui_loop_widgets, tui_run_controller


def test_run_snapshot_waiting(tmp_path: Path) -> None:
    svg = _capture_run_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
max_iterations = 3
""",
        tui_run_controller.LiveEventSnapshot(ready=False),
    )
    assert "events: waiting for events.jsonl" in svg
    assert_svg_snapshot("tui_run/waiting", svg)


def test_run_snapshot_review_running(tmp_path: Path) -> None:
    svg = _capture_run_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
max_iterations = 3
""",
        _snapshot(
            _event(1, "phase_start", phase="review", iteration=1),
        ),
    )
    assert "▶ review" in svg and "iteration 1/3" in svg
    assert_svg_snapshot("tui_run/review-running", svg)


def test_run_snapshot_remediation_running_with_routes(tmp_path: Path) -> None:
    svg = _capture_run_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
max_iterations = 4
[profiles.demo.triage]
enabled = true
contract = "v2"
[profiles.demo.triage.routing]
enabled = true
default_route = "codex-midi"
[profiles.demo.triage.routes.codex-midi]
harness = "codex"
model = "gpt-5.4-mini"
""",
        _snapshot(
            _event(1, "phase_start", phase="review", iteration=1),
            _event(2, "phase_result", phase="review", iteration=1, payload={"status": "clear"}),
            _event(3, "phase_start", phase="triage", iteration=1),
            _event(4, "phase_result", phase="triage", iteration=1, payload={"status": "routed"}),
            _event(5, "phase_start", phase="remediate", iteration=1),
        ),
    )
    assert "▶ remediation" in svg and "codex-midi" not in svg
    assert_svg_snapshot("tui_run/remediation-running", svg)


def test_run_snapshot_inner_retry(tmp_path: Path) -> None:
    svg = _capture_run_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
max_iterations = 2
[profiles.demo.runtime]
inner_check_retries = 2
""",
        _snapshot(
            _event(1, "phase_start", phase="remediate", iteration=1),
            _event(2, "check_result", iteration="1.1", payload={"passed": False}),
            _event(3, "phase_start", phase="remediate", iteration="1.2"),
        ),
    )
    assert "inner retry 1/2" in svg
    assert_svg_snapshot("tui_run/inner-retry", svg)


def test_run_snapshot_disabled_triage(tmp_path: Path) -> None:
    svg = _capture_run_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
max_iterations = 1
[profiles.demo.triage]
enabled = false
""",
        _snapshot(
            _event(1, "phase_start", phase="review", iteration=1),
            _event(2, "phase_result", phase="review", iteration=1, payload={"status": "clear"}),
        ),
    )
    assert "⤫ triage" in svg and "disabled" in svg
    assert_svg_snapshot("tui_run/disabled-triage", svg)


def test_run_snapshot_done_clear(tmp_path: Path) -> None:
    svg = _capture_run_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
max_iterations = 1
final_review = false
checks = ["pytest -q"]
""",
        _snapshot(
            _event(1, "phase_start", phase="review", iteration=1),
            _event(2, "phase_result", phase="review", iteration=1, payload={"status": "clear"}),
            _event(3, "phase_start", phase="remediate", iteration=1),
            _event(4, "phase_result", phase="remediate", iteration=1, payload={"status": "skipped"}),
            _event(5, "check_result", iteration=1, payload={"passed": True}),
            _event(6, "phase_start", phase="commit", iteration=1),
            _event(7, "phase_result", phase="commit", iteration=1, payload={"status": "skipped"}),
        ),
        status="clear",
    )
    assert "✓ checks" in svg and "passed" in svg
    assert_svg_snapshot("tui_run/done-clear", svg)


def test_run_snapshot_done_with_findings(tmp_path: Path) -> None:
    svg = _capture_run_svg(
        tmp_path,
        """
[profiles.demo]
[profiles.demo.pipeline]
max_iterations = 1
checks = ["pytest -q"]
""",
        _snapshot(
            _event(1, "phase_start", phase="review", iteration=1),
            _event(2, "phase_result", phase="review", iteration=1, payload={"status": "findings"}),
            _event(3, "check_result", iteration=1, payload={"passed": False}),
        ),
        status="findings",
    )
    assert "findings" in svg and "failed" in svg
    assert_svg_snapshot("tui_run/done-with-findings", svg)


def _capture_run_svg(
    tmp_path: Path,
    profile_toml: str,
    snapshot: tui_run_controller.LiveEventSnapshot,
    *,
    status: str = "running",
) -> str:
    async def run() -> str:
        profile = _profile(tmp_path, profile_toml)
        view_cls = tui_loop_widgets.loop_run_view_class()
        log_cls = tui_loop_widgets.event_log_class()
        components = tui._load_textual_components()
        if view_cls is None or log_cls is None or components is None:
            pytest.skip("Textual is not installed")

        controller = _FakeLiveController(snapshot, status=status)
        loop_view = view_cls()
        event_log = log_cls()

        class SnapshotApp(components.app.App):  # type: ignore[misc, valid-type]
            CSS = """
            #loop-run, #event-log {
                height: auto;
                width: 100%;
            }
            .run-row {
                height: auto;
            }
            .phase-gutter {
                height: auto;
                width: 44;
            }
            .run-phase {
                height: auto;
                width: 1fr;
            }
            """

            def compose(self):
                loop_view.set_state(controller, profile)
                event_log.set_controller(controller)
                yield loop_view
                yield event_log

        async with SnapshotApp().run_test(size=(120, 32)) as pilot:
            await pilot.pause()
            loop_view.rebuild()
            event_log.rebuild()
            await pilot.pause()
            return normalize_svg(
                pilot.app.export_screenshot(title="revrem-run", simplify=True)
            )

    return asyncio.run(run())


def _profile(tmp_path: Path, profile_toml: str) -> profiles.Profile:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".revrem.toml").write_text(profile_toml, encoding="utf-8")
    return profiles.resolve_profile("demo", cwd=repo, require_implemented=False)


def _snapshot(*records: events.Event) -> tui_run_controller.LiveEventSnapshot:
    return tui_run_controller.LiveEventSnapshot(events=records, ready=True)


def _event(
    seq: int,
    kind: str,
    *,
    phase: str | None = None,
    iteration: int | str | None = None,
    payload: dict[str, object] | None = None,
) -> events.Event:
    return events.Event(
        run_id="snapshot",
        seq=seq,
        kind=kind,
        phase=phase,
        iteration=iteration,
        payload=payload or {},
        ts="2026-06-30T00:00:00Z",
    )


class _FakeLiveController:
    def __init__(
        self, snapshot: tui_run_controller.LiveEventSnapshot, *, status: str
    ) -> None:
        self._snapshot = snapshot
        self.status = status

    def read_live_events(self) -> tui_run_controller.LiveEventSnapshot:
        return self._snapshot

    def stdout_lines(self) -> tuple[str, ...]:
        return ("review stdout",)

    def stderr_lines(self) -> tuple[str, ...]:
        return ()
