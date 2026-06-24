from __future__ import annotations

from pathlib import Path

from code_review_loop import profiles

ROOT = Path(__file__).resolve().parents[1]


def test_example_profiles_validate():
    paths = sorted((ROOT / "examples").glob("*/.revrem.toml"))
    assert paths
    for path in paths:
        loaded = profiles.load_profile_file(path)
        assert loaded.profiles, f"{path} defines no profiles"
        for profile in loaded.profiles.values():
            profiles.validate_profile(profile, require_implemented=False)
