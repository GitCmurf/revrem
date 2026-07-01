from __future__ import annotations

from pathlib import Path

from code_review_loop import events as event_model
from code_review_loop import profiles, tui_run_state


def _profile(
    tmp_path: Path,
    *,
    triage: bool = False,
    commit: bool = True,
    inner: int = 0,
    checks: tuple[str, ...] | None = ("pytest -q",),
) -> profiles.Profile:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    body = [
        "[profiles.p]",
        "[profiles.p.pipeline]",
        "base='main'",
        "max_iterations=11",
        "[profiles.p.triage]",
        f"enabled={'true' if triage else 'false'}",
        "[profiles.p.commit]",
        f"enabled={'true' if commit else 'false'}",
        "[profiles.p.runtime]",
        f"inner_check_retries={inner}",
    ]
    checks_value = (
        "[]"
        if checks is None
        else f"[{', '.join(repr(command) for command in checks)}]"
    )
    body.insert(4, f"checks={checks_value}")
    (repo / ".revrem.toml").write_text("\n".join(body) + "\n", encoding="utf-8")
    return profiles.resolve_profile("p", cwd=repo, require_implemented=False)


def _ev(
    seq: int,
    kind: str,
    phase: str | None = None,
    iteration: int | str | None = None,
    **payload: object,
) -> event_model.Event:
    return event_model.Event(
        run_id="r",
        seq=seq,
        kind=kind,
        phase=phase,
        iteration=iteration,
        payload=payload,
    )


def test_pending_when_no_events(tmp_path: Path) -> None:
    view = tui_run_state.run_loop_view((), _profile(tmp_path))
    states = {phase.name: phase.state for phase in view.phases}

    assert states["review"] == "pending"
    assert view.iteration is None
    assert view.max_iterations == 11


def test_running_and_done_states_map_remediate(tmp_path: Path) -> None:
    events = (
        _ev(1, "phase_start", "review", 1),
        _ev(2, "phase_result", "review", 1, summary="2 findings"),
        _ev(3, "phase_start", "remediate", 1),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path))
    states = {phase.name: phase.state for phase in view.phases}

    assert states["review"] == "done"
    assert states["remediation"] == "running"
    assert states["commit"] == "pending"
    assert view.iteration == 1


def test_disabled_phases_render_disabled(tmp_path: Path) -> None:
    view = tui_run_state.run_loop_view((), _profile(tmp_path, triage=False, commit=False))
    states = {phase.name: phase.state for phase in view.phases}

    assert states["triage"] == "disabled"
    assert states["commit"] == "disabled"


def test_checks_state_from_check_result_events(tmp_path: Path) -> None:
    events = (
        _ev(1, "phase_start", "remediate", 2),
        _ev(2, "phase_result", "remediate", 2),
        _ev(3, "check_result", "test", 2, name="pytest -q", status="passed"),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path))
    states = {phase.name: phase.state for phase in view.phases}
    details = {phase.name: phase.detail for phase in view.phases}

    assert states["checks"] == "done"
    assert details["checks"] == "passed"


def test_failed_check_result_uses_status_field(tmp_path: Path) -> None:
    events = (
        _ev(1, "phase_start", "remediate", 2),
        _ev(2, "phase_result", "remediate", 2),
        _ev(3, "check_result", "test", 2, command="pytest -q", status="failed"),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path))
    states = {phase.name: phase.state for phase in view.phases}
    details = {phase.name: phase.detail for phase in view.phases}

    assert states["checks"] == "done"
    assert details["checks"] == "failed"


def test_failed_cleanliness_check_is_visible_without_explicit_pipeline_checks(
    tmp_path: Path,
) -> None:
    events = (
        _ev(1, "phase_start", "remediate", 1),
        _ev(2, "phase_result", "remediate", 1),
        _ev(3, "check_result", "check", 1, command="git diff --check", status="failed"),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path, checks=()))
    states = {phase.name: phase.state for phase in view.phases}
    details = {phase.name: phase.detail for phase in view.phases}

    assert states["checks"] == "done"
    assert details["checks"] == "failed"


def test_inner_retry_counts_repeated_remediate_in_iteration(tmp_path: Path) -> None:
    events = (
        _ev(1, "phase_start", "remediate", 3),
        _ev(2, "phase_result", "remediate", 3),
        _ev(3, "check_result", "test", 3, status="failed"),
        _ev(4, "phase_start", "remediate", 3),
        _ev(5, "phase_result", "remediate", 3),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path, inner=2))

    assert view.inner_check_retries == 2
    assert view.inner_retry == 1


def test_inner_retry_counts_sub_iteration_labels_as_same_outer_iteration(
    tmp_path: Path,
) -> None:
    events = (
        _ev(1, "phase_start", "remediate", 1),
        _ev(2, "check_result", "test", "1.1", status="failed"),
        _ev(3, "phase_start", "remediate", "1.2"),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path, inner=2))

    assert view.iteration == 1
    assert view.inner_retry == 1


def test_new_outer_iteration_resets_prior_phase_states(tmp_path: Path) -> None:
    events = (
        _ev(1, "phase_start", "review", 1),
        _ev(2, "phase_result", "review", 1, status="findings"),
        _ev(3, "phase_start", "triage", 1),
        _ev(4, "phase_result", "triage", 1),
        _ev(5, "phase_start", "remediate", 1),
        _ev(6, "phase_result", "remediate", 1),
        _ev(7, "check_result", "test", 1, status="passed"),
        _ev(8, "phase_start", "review", 2),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path, triage=True, inner=1))
    states = {phase.name: phase.state for phase in view.phases}

    assert states["review"] == "running"
    assert states["triage"] == "pending"
    assert states["remediation"] == "pending"
    assert states["checks"] == "pending"


def test_orphan_check_result_marks_checks_without_remediate_start(tmp_path: Path) -> None:
    events = (_ev(1, "check_result", "check", "1.1", status="failed"),)
    view = tui_run_state.run_loop_view(events, _profile(tmp_path))
    states = {phase.name: phase.state for phase in view.phases}
    details = {phase.name: phase.detail for phase in view.phases}

    assert states["checks"] == "done"
    assert details["checks"] == "failed"
    assert view.iteration == 1


def test_string_outer_iteration_change_resets_prior_states(tmp_path: Path) -> None:
    events = (
        _ev(1, "phase_start", "review", "1"),
        _ev(2, "phase_result", "review", "1"),
        _ev(3, "check_result", "check", "1.1", status="passed"),
        _ev(4, "phase_start", "review", "2"),
    )
    view = tui_run_state.run_loop_view(events, _profile(tmp_path))
    states = {phase.name: phase.state for phase in view.phases}

    assert view.iteration == 2
    assert states["review"] == "running"
    assert states["checks"] == "pending"


def test_event_tail_lines_bounded_and_formatted() -> None:
    events = [_ev(i, "phase_output", "review", 1, text=f"line {i}") for i in range(1, 20)]

    lines = tui_run_state.event_tail_lines(events, limit=5)

    assert len(lines) == 5
    assert "review" in lines[-1]


def test_event_tail_lines_empty() -> None:
    assert tui_run_state.event_tail_lines(()) == ()
