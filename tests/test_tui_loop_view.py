from __future__ import annotations

from pathlib import Path

from code_review_loop import profiles, tui_loop_state
from code_review_loop.tui_loop_model import LoopEditModel


def _repo(path: Path, body: str) -> Path:
    repo = path
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    (repo / ".revrem.toml").write_text(body, encoding="utf-8")
    return repo


def _model(repo: Path, name: str) -> LoopEditModel:
    return LoopEditModel.load(name, cwd=repo)


def test_rail_meta_omits_inner_rail_when_retries_zero(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nmax_iterations=5\n"
        "[profiles.p.runtime]\ninner_check_retries=0\n",
    )
    meta = tui_loop_state.loop_rail_meta(_model(repo, "p").profile)
    assert meta.inner_rail is False
    assert meta.inner_return_label is None
    assert "iteration < 5" in meta.outer_return_label


def test_rail_meta_draws_inner_rail_when_retries_positive(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nmax_iterations=5\n"
        "[profiles.p.runtime]\ninner_check_retries=2\n",
    )
    meta = tui_loop_state.loop_rail_meta(_model(repo, "p").profile)
    assert meta.inner_rail is True
    assert meta.inner_return_label is not None
    assert "up to 2 inner retries" in meta.inner_return_label


def test_rail_meta_final_review_only_when_on(tmp_path: Path) -> None:
    on = _repo(
        tmp_path / "on",
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nfinal_review=true\n",
    )
    off = _repo(
        tmp_path / "off",
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nfinal_review=false\n",
    )
    assert tui_loop_state.loop_rail_meta(_model(on, "p").profile).final_review is True
    assert tui_loop_state.loop_rail_meta(_model(off, "p").profile).final_review is False
    assert tui_loop_state.loop_rail_meta(_model(off, "p").profile).final_review_label is None


def test_phase_gutter_shows_inner_rail_and_final_review_together(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nfinal_review=true\n"
        "[profiles.p.runtime]\ninner_check_retries=2\n",
    )
    meta = tui_loop_state.loop_rail_meta(_model(repo, "p").profile)
    remediation = tui_loop_state.phase_gutter("remediation", meta)
    checks = tui_loop_state.phase_gutter("checks", meta)
    assert meta.inner_rail is True
    assert meta.final_review is True
    assert "03" in remediation
    assert "04" in checks
    returns = "\n".join(tui_loop_state.loop_return_lines(_model(repo, "p").profile))
    assert "INNER RETRY" in returns
    assert "up to 2 inner retries" in returns
    assert meta.final_review_label is not None


def test_phase_card_summary_shows_harness_model_and_disabled_marker(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n"
        "[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    review = tui_loop_state.phase_card_lines(model, "review", focused=False, expanded=False)
    text = "\n".join(review)
    assert "REVIEW" in text and "codex" in text and "gpt-5.5" in text
    assert text.lstrip().startswith(f"▸ {tui_loop_state.PHASE_ENABLED_GLYPH}")
    triage = tui_loop_state.phase_card_lines(model, "triage", focused=False, expanded=False)
    assert "\n".join(triage).lstrip().startswith(
        f"▸ {tui_loop_state.PHASE_DISABLED_GLYPH}"
    )


def test_phase_card_focused_collapsed_remains_single_summary_line(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n"
        "[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    lines = tui_loop_state.phase_card_lines(
        _model(repo, "p"), "review", focused=True, expanded=False
    )
    assert len(lines) == 1
    assert lines[0].startswith(">")
    assert "harness" not in lines[0].lower()


def test_phase_card_expanded_shows_edit_fields_with_overlay(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n"
        "[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    model.set_field("review.model", "gpt-5.6")
    expanded = tui_loop_state.phase_card_lines(model, "review", focused=True, expanded=True)
    text = "\n".join(expanded)
    assert text.startswith(">▾")
    assert "harness" in text and "model" in text and "effort" in text and "timeout" in text
    assert "gpt-5.6" in text and "gpt-5.5" not in text


def test_phase_card_timeout_overlay_shows_default_when_unset(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n"
        "[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    assert "<default>" in "\n".join(
        tui_loop_state.phase_card_lines(
            _model(repo, "p"), "review", focused=False, expanded=False
        )
    )


def test_phase_card_timeout_overlay_formats_int_and_float_values(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n"
        "[profiles.p.review]\nharness='codex'\nmodel='gpt-5.5'\n",
    )
    model = _model(repo, "p")
    model.set_field("review.timeout_seconds", "0.5")
    assert "0.5s" in "\n".join(
        tui_loop_state.phase_card_lines(model, "review", focused=False, expanded=False)
    )
    model.set_field("review.timeout_seconds", "1")
    assert "1s" in "\n".join(
        tui_loop_state.phase_card_lines(model, "review", focused=False, expanded=False)
    )


def test_checks_phase_is_display_only(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nchecks=['pytest -q']\n",
    )
    expanded = "\n".join(
        tui_loop_state.phase_card_lines(_model(repo, "p"), "checks", focused=True, expanded=True)
    )
    assert "1 commands" in expanded
    assert "harness" not in expanded and "model" not in expanded
    assert tui_loop_state.PHASE_DOTTED["checks"] == {}


def test_loop_header_and_rails_reflect_unsaved_meta_edits(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\nmax_iterations=7\n"
        "[profiles.p.runtime]\ninner_check_retries=0\n",
    )
    model = _model(repo, "p")
    model.set_field("pipeline.max_iterations", "11")
    model.set_field("pipeline.final_review", "false")
    model.set_field("runtime.inner_check_retries", "2")
    header = tui_loop_state.loop_header_text(model)
    meta = tui_loop_state.loop_rail_meta(model)
    assert "11" in header and "2" in header
    assert meta.max_iterations == 11
    assert meta.inner_rail is True
    assert meta.final_review is False


def test_loop_meta_dotted_uses_raw_profile_keys() -> None:
    assert tui_loop_state.LOOP_META_DOTTED["max_iterations"] == "pipeline.max_iterations"
    assert tui_loop_state.LOOP_META_DOTTED["final_review"] == "pipeline.final_review"
    assert tui_loop_state.LOOP_META_DOTTED["inner_check_retries"] == (
        "runtime.inner_check_retries"
    )


def _routes_repo(tmp_path: Path) -> Path:
    body = "\n".join(
        (
            "[profiles.r]",
            "[profiles.r.pipeline]",
            "base='main'",
            "[profiles.r.triage]",
            "enabled=true",
            "contract='v2'",
            "[profiles.r.triage.routing]",
            "enabled=true",
            "default_route='security'",
            "strict_on_unavailable_route=false",
            "allow_model_escalation=true",
            "[profiles.r.triage.routes.security]",
            "harness='codex'",
            "model='gpt-5.5'",
            "reasoning_effort='high'",
            "sandbox='read-only'",
            "fallback='nit'",
            "[profiles.r.triage.routes.nit]",
            "harness='claude'",
            "model='haiku-4.5'",
            "reasoning_effort='low'",
            "sandbox='read-only'",
        )
    )
    return _repo(tmp_path, body + "\n")


def test_triage_routes_lines_show_routing_and_table(tmp_path: Path) -> None:
    repo = _routes_repo(tmp_path)
    lines = tui_loop_state.triage_routes_lines(_model(repo, "r").profile)
    text = "\n".join(lines)
    assert "default" in text and "security" in text
    assert "strict" in text and "escalate" in text
    assert "security" in text and "gpt-5.5" in text and "high" in text
    assert "nit" in text and "haiku-4.5" in text


def test_triage_routes_lines_hidden_when_routing_disabled(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n")
    assert tui_loop_state.triage_routes_lines(_model(repo, "p").profile) == ()


def test_triage_routes_lines_reflect_route_overlays(tmp_path: Path) -> None:
    repo = _routes_repo(tmp_path)
    model = _model(repo, "r")
    model.set_field("triage.routes.security.model", "gpt-5.6")
    model.set_field("triage.routes.security.fallback", "nit")
    text = "\n".join(tui_loop_state.triage_routes_lines(model))
    assert "gpt-5.6" in text
    assert "fallback nit" in text


def test_triage_routes_lines_uses_unsaved_routing_enable(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        "[profiles.p]\n[profiles.p.pipeline]\nbase='main'\n"
        "[profiles.p.triage]\n"
        "enabled=true\n"
        'contract = "v2"\n'
        "[profiles.p.triage.routing]\n"
        "enabled=false\n"
        'default_route="security"\n',
    )
    model = _model(repo, "p")
    model.set_field("triage.routes.audit.harness", "codex")
    model.set_field("triage.routes.audit.sandbox", "workspace-write")
    model.set_field("triage.routing.enabled", "true")

    text = "\n".join(tui_loop_state.triage_routes_lines(model))
    assert "audit" in text


def test_triage_routes_lines_uses_unsaved_routing_header_values(tmp_path: Path) -> None:
    repo = _routes_repo(tmp_path)
    model = _model(repo, "r")
    model.set_field("triage.routing.default_route", "nit")
    model.set_field("triage.routing.strict_on_unavailable_route", "true")
    model.set_field("triage.routing.allow_model_escalation", "false")

    header = tui_loop_state.triage_routes_lines(model)[0]

    assert "default nit" in header
    assert "strict True" in header
    assert "escalate False" in header


def test_loop_state_accepts_plain_profile() -> None:
    profile = profiles.Profile(name="plain")
    assert "plain" in tui_loop_state.loop_header_text(profile)
