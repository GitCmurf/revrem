from __future__ import annotations

import stat
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
    assert 'cp -R "$REPO_ROOT/src" "$RELEASE_DIR/src"' in script
    assert 'PYTHONPATH="$RELEASE_DIR/src\\${PYTHONPATH:+:\\$PYTHONPATH}"' in script
    assert 'cat > "$BIN_DIR/code-review-loop" <<EOF' in script
    assert 'cat > "$BIN_DIR/revrem" <<EOF' in script


def test_install_dev_targets_repo_local_virtualenv():
    script = (ROOT / "scripts/install-dev").read_text(encoding="utf-8")

    assert "python -m venv .venv" not in script
    assert '"$PYTHON" -m venv .venv' in script
    assert './.venv/bin/python -m pip install -e ".[dev]"' in script
    assert 'PYTHONPATH="$REPO_ROOT/src\\${PYTHONPATH:+:\\$PYTHONPATH}"' in script
