"""Behavioural acceptance for activation, rollback and failed promotion."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "promote_stable", Path(__file__).resolve().parents[1] / "scripts/promote_stable.py")
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    home = tmp_path / "install with 'quotes' $literal"
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("REVREM_STABLE_HOME", str(home))
    monkeypatch.setenv("REVREM_BIN_DIR", str(bin_dir))
    monkeypatch.delenv("REVREM_STABLE_VENV", raising=False)
    monkeypatch.setattr(installer, "smoke", lambda release: None)
    return home, bin_dir


def release(home, name):
    path = home / "releases" / name
    (path / "venv/bin").mkdir(parents=True)
    python = path / "venv/bin/python"
    python.write_text(f"#!/bin/sh\nprintf '%s\\n' '{name}'\nprintf '%s\\n' \"$@\"\n")
    python.chmod(0o755)
    (path / "manifest.json").write_text(json.dumps({"commit": name}))
    return path


def test_promote_and_rollback_both_launchers_outside_checkout(deployment, monkeypatch, tmp_path):
    home, bin_dir = deployment
    first = release(home, "first")
    second = release(home, "second")
    candidates = iter([first, second])
    monkeypatch.setattr(installer, "install_release", lambda *args: next(candidates))
    bin_dir.mkdir()
    (bin_dir / "revrem").write_text("legacy launcher\n")
    for expected in (first, second):
        assert installer.main([]) == 0
        assert (home / "current").resolve() == expected
        for name in ("revrem", "code-review-loop"):
            result = subprocess.run([str(bin_dir / name), "argument with spaces"],
                                    cwd=tmp_path, text=True, capture_output=True, check=True)
            assert result.stdout.splitlines() == [expected.name, "-I", "-m", "code_review_loop", "argument with spaces"]
    assert (bin_dir / "revrem.before-managed-install").read_text() == "legacy launcher\n"
    assert installer.main(["--rollback"]) == 0
    assert (home / "current").resolve() == first
    assert (home / "previous").resolve() == second
    assert installer.main(["--rollback"]) == 0
    assert (home / "current").resolve() == second


def test_failed_install_or_rollback_preserves_active_release(deployment, monkeypatch):
    home, bin_dir = deployment
    old = release(home, "old")
    installer.atomic_link(old, home / "current")
    installer.install_launchers(home, bin_dir)
    original = (bin_dir / "revrem").read_bytes()

    def fail(*args):
        raise subprocess.CalledProcessError(1, ["verification"])

    monkeypatch.setattr(installer, "install_release", fail)
    assert installer.main([]) == 1
    assert (home / "current").resolve() == old
    assert (bin_dir / "revrem").read_bytes() == original
    previous = release(home, "previous")
    installer.atomic_link(previous, home / "previous")
    monkeypatch.setattr(installer, "smoke", fail)
    assert installer.main(["--rollback"]) == 1
    assert (home / "current").resolve() == old
    assert (home / "previous").resolve() == previous


def test_failed_build_removes_only_candidate(deployment, monkeypatch):
    home, _ = deployment
    old = release(home, "old")
    monkeypatch.setenv("REVREM_SKIP_CHECKS", "1")

    def run(argv, **kwargs):
        if argv[1] == "status":
            return ""
        if argv[1] == "rev-parse":
            return "a" * 40
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(installer, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        installer.install_release(home, "")
    assert list((home / "releases").iterdir()) == [old]


def test_dirty_checkout_cannot_be_promoted(deployment, monkeypatch):
    home, _ = deployment
    monkeypatch.setattr(installer, "run", lambda *a, **k: " M changed.py\n")
    with pytest.raises(ValueError, match="clean snapshots"):
        installer.install_release(home, "")
    assert not (home / "releases").exists()


def test_status_is_read_only_and_rollback_requires_previous(deployment, capsys):
    home, _ = deployment
    assert installer.main(["--status"]) == 0
    assert json.loads(capsys.readouterr().out) == {"current": None, "previous": None}
    assert not home.exists()
    assert installer.main(["--rollback"]) == 1
    assert "No previous" in capsys.readouterr().err


def test_refuses_unmanaged_pointer(deployment):
    home, _ = deployment
    (home / "current").mkdir(parents=True)
    assert installer.main([]) == 1
    assert (home / "current").is_dir()


def test_promotion_lock_prevents_concurrent_mutation(deployment):
    home, _ = deployment
    home.mkdir(parents=True)
    with (home / ".promotion.lock").open("a") as lock:
        installer.fcntl.flock(lock, installer.fcntl.LOCK_EX | installer.fcntl.LOCK_NB)
        assert installer.main([]) == 1
    assert not (home / "current").exists()


def test_partial_launcher_failure_restores_legacy_install(deployment, monkeypatch):
    home, bin_dir = deployment
    candidate = release(home, "candidate")
    bin_dir.mkdir()
    for name in ("revrem", "code-review-loop"):
        (bin_dir / name).write_text(f"legacy {name}\n")
    original = installer.install_launchers

    def fail(home, bin_dir):
        original(home, bin_dir)
        raise OSError("simulated activation failure")

    monkeypatch.setattr(installer, "install_launchers", fail)
    with pytest.raises(OSError, match="simulated"):
        installer.activate_release(home, bin_dir, candidate)
    assert not (home / "current").exists()
    for name in ("revrem", "code-review-loop"):
        assert (bin_dir / name).read_text() == f"legacy {name}\n"
