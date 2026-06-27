from __future__ import annotations

from pathlib import Path

from code_review_loop import profiles
from code_review_loop.cli.commands import config as config_cmd


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_config_set_updates_field(tmp_path, monkeypatch):
    _write(tmp_path / ".revrem.toml", '[profiles.demo]\nreview.model = "old"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    code = config_cmd.main(["set", "demo", "review.model", "gpt-5.5"])
    assert code == 0
    reloaded = profiles.load_profile_file(tmp_path / ".revrem.toml").raw_profiles["demo"]
    assert reloaded["review"]["model"] == "gpt-5.5"


def test_config_set_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    code = config_cmd.main(["set", "ghost", "review.model", "x"])
    assert code != 0
