from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from code_review_loop import profiles

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "tests" / "fixtures" / "expert_repo" / "EXPECTED.json"
MATRIX = ROOT / "tests" / "artifacts" / "profile_overlap_matrix.json"


def _expected_profiles() -> dict[str, set[str]]:
    data = json.loads(EXPECTED.read_text(encoding="utf-8"))
    return {
        name: {finding["fingerprint"] for finding in findings}
        for name, findings in data["profiles"].items()
    }


def test_expert_profile_expected_findings_are_distinct():
    expected = _expected_profiles()
    assert len(expected) >= 4
    matrix: dict[str, float] = {}
    for left, right in combinations(sorted(expected), 2):
        left_set = expected[left]
        right_set = expected[right]
        overlap = len(left_set & right_set) / max(1, len(left_set | right_set))
        matrix[f"{left}|{right}"] = overlap
        assert overlap <= 0.2
    assert matrix == json.loads(MATRIX.read_text(encoding="utf-8"))


def test_expert_profiles_resolve_for_overlap_profiles(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    for name in _expected_profiles():
        resolved = profiles.resolve_profile(
            name, cwd=repo, home=tmp_path / "home", require_implemented=False
        )
        assert resolved.name == name
        assert resolved.source == profiles.BUILTIN_PROFILE_SOURCE


def test_live_expert_profile_smoke_is_documented_but_not_hermetic():
    """Tier 2 release managers must record one real-model distinctness run.

    This hermetic suite validates configured profile distinctness only; it does
    not claim a real model will discover the seeded issues without a live smoke.
    """
    plan = (ROOT / "docs" / "05-planning" / "plan-005-next-steps-v0.5.0.md").read_text(
        encoding="utf-8"
    )
    assert "live-smoke run" in plan
    assert "real model output" in plan
