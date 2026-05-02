from __future__ import annotations

import os
import stat
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_console_entry_points_include_stable_alias():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["code-review-loop"] == "code_review_loop.cli:main"
    assert scripts["revrem"] == "code_review_loop.cli:main"


def test_distribution_scripts_are_executable_and_posix_sh():
    for relative in ("scripts/install-dev", "scripts/promote-stable"):
        path = ROOT / relative
        mode = path.stat().st_mode
        first_line = path.read_text(encoding="utf-8").splitlines()[0]

        assert first_line == "#!/usr/bin/env sh"
        assert mode & stat.S_IXUSR, f"{relative} must be executable"


def test_promote_stable_uses_home_local_stable_install_boundary():
    script = (ROOT / "scripts/promote-stable").read_text(encoding="utf-8")

    assert 'STABLE_HOME=${REVREM_STABLE_HOME:-"$HOME/.local/share/revrem"}' in script
    assert 'BIN_DIR=${REVREM_BIN_DIR:-"$HOME/.local/bin"}' in script
    assert 'RELEASES_DIR=$STABLE_HOME/releases' in script
    assert 'mkdir -p "$RELEASES_DIR" "$BIN_DIR"' in script
    assert 'RELEASE_SUFFIX=0' in script
    assert 'if mkdir "$RELEASE_DIR"; then' in script
    assert 'if [ -d "$RELEASE_DIR" ]; then' in script
    assert 'cp -R "$REPO_ROOT/src" "$RELEASE_DIR/src"' in script
    assert 'PYTHONPATH="$RELEASE_DIR/src\\${PYTHONPATH:+:\\$PYTHONPATH}"' in script
    assert 'cat > "$BIN_DIR/code-review-loop" <<EOF' in script
    assert 'cat > "$BIN_DIR/revrem" <<EOF' in script


def test_promote_stable_refuses_interpreters_older_than_python_311(tmp_path):
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env sh
case "$1" in
  -c)
    exit 1
    ;;
  -m)
    if [ "$2" = "venv" ]; then
      touch "${FAKE_VENV_MARKER:?}"
      exit 0
    fi
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    marker = tmp_path / "unexpected-venv-call"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "PYTHON": str(fake_python),
        "REVREM_SKIP_CHECKS": "1",
        "FAKE_VENV_MARKER": str(marker),
    }

    result = subprocess.run(
        ["sh", str(ROOT / "scripts/promote-stable")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Python 3.11 or newer" in result.stderr
    assert not marker.exists()
    assert not (home / ".local" / "share" / "revrem" / "releases").exists()
    assert not (home / ".local" / "bin" / "revrem").exists()


def test_install_dev_targets_repo_local_virtualenv():
    script = (ROOT / "scripts/install-dev").read_text(encoding="utf-8")

    assert "python -m venv .venv" not in script
    assert '"$PYTHON" -m venv .venv' in script
    assert './.venv/bin/python -m pip install -e ".[dev]"' in script
    assert 'PYTHONPATH="$REPO_ROOT/src\\${PYTHONPATH:+:\\$PYTHONPATH}"' in script
