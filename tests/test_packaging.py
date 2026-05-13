from __future__ import annotations

import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _prepare_temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    script_dir = repo / "scripts"
    script_dir.mkdir(parents=True)

    install_dev = script_dir / "install-dev"
    install_dev.write_text((ROOT / "scripts/install-dev").read_text(encoding="utf-8"), encoding="utf-8")
    install_dev.chmod(0o755)

    return repo


def test_console_entry_points_include_stable_alias():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["code-review-loop"] == "code_review_loop.cli:main"
    assert scripts["revrem"] == "code_review_loop.cli:main"


def test_project_uses_revrem_distribution_identity():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    project = pyproject["project"]

    assert project["name"] == "revrem"
    assert project["description"].startswith("Bounded AI review")
    assert project["urls"]["Homepage"] == "https://github.com/GitCmurf/revrem"
    assert project["urls"]["Source"] == "https://github.com/GitCmurf/revrem"
    assert project["urls"]["Issues"] == "https://github.com/GitCmurf/revrem/issues"
    assert project["urls"]["Changelog"].endswith("/CHANGELOG.md")


def test_project_version_matches_package_version():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    init_text = (ROOT / "src/code_review_loop/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', init_text, re.MULTILINE)

    assert match is not None
    assert pyproject["project"]["version"] == match.group(1)


def test_build_backend_version_is_pinned_for_reproducible_release_builds():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"]["requires"] == ["setuptools==80.9.0"]


def test_ci_builds_and_smokes_revrem_wheel():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "package-smoke:" in workflow
    assert 'os: [ubuntu-latest, macos-latest]' in workflow
    assert 'python-version: ["3.11", "3.12"]' in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "python -m twine check dist/*" in workflow
    assert "wheel=\"$(find dist -maxdepth 1 -name 'revrem-*.whl' -print -quit)\"" in workflow
    assert '.pkg-smoke/bin/python -m pip install "$wheel"' in workflow
    assert ".pkg-smoke/bin/revrem --version" in workflow
    assert ".pkg-smoke/bin/code-review-loop --version" in workflow
    assert "git -C tests/fixtures/reference-repo init" in workflow
    assert "cd tests/fixtures/reference-repo" in workflow
    assert '"$GITHUB_WORKSPACE/.pkg-smoke/bin/revrem" doctor --format json --base main --codex-bin git' in workflow


def test_release_workflow_uses_trusted_publishing_and_dry_run():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "dry_run:" in workflow
    assert '"v*.*.*-rc*"' in workflow
    assert "Validate release version" in workflow
    assert "does not match package version" in workflow
    assert "version.replace('rc', '-rc')" in workflow
    assert "python -m build --sdist --wheel" in workflow
    assert "python -m twine check dist/*" in workflow
    assert "dist/SHA256SUMS" in workflow
    assert "actions/attest-build-provenance" in workflow
    assert "sigstore/gh-action-sigstore-python" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "repository-url: https://test.pypi.org/legacy/" in workflow
    assert "github.event_name == 'push' && contains(github.ref_name, '-rc')" in workflow
    assert "github.event_name == 'push' && !contains(github.ref_name, '-rc')" in workflow
    assert "if: github.event_name == 'push'" in workflow


def test_release_runbook_documents_rollback_and_provenance():
    runbook = (ROOT / "docs/60-runbooks/runbook-001-release-and-rollback.md").read_text(
        encoding="utf-8"
    )
    adr = (ROOT / "docs/45-adr/adr-011-release-trust-and-rollback.md").read_text(
        encoding="utf-8"
    )

    for text in (runbook, adr):
        assert "Trusted Publishing" in text
        assert "TestPyPI" in text
        assert "SHA256SUMS" in text
        assert "Sigstore" in text
        assert "yank" in text.lower()
        assert "hotfix" in text.lower()


def test_release_runbook_documents_task_002_external_gates():
    runbook = (ROOT / "docs/60-runbooks/runbook-001-release-and-rollback.md").read_text(
        encoding="utf-8"
    )

    assert "TASK-002 External Gate Checklist" in runbook
    assert "Merge the implementation branch to `main`" in runbook
    assert "branch protection requires the CI workflow" in runbook
    assert "dry_run=true" in runbook
    assert "Trusted Publisher entries" in runbook
    assert "Publish an RC tag to TestPyPI" in runbook
    assert "Publish the final tag only after the RC install smoke passes" in runbook
    assert "Record final PyPI/TestPyPI/GitHub Release URLs" in runbook


def test_optional_tui_extra_declares_textual_dependency():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    tui_extra = pyproject["project"]["optional-dependencies"]["tui"]

    assert any(dependency.startswith("textual>=") for dependency in tui_extra)
    assert any(dependency.startswith("rich>=") for dependency in tui_extra)


def test_readme_tui_install_and_launch_commands_use_the_same_venv():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert './.venv/bin/pip install -e ".[tui]"' in readme
    assert "./.venv/bin/revrem ui" in readme
    assert "./.venv/bin/revrem ui --profile final-pr" in readme


def test_readme_bundle_command_fence_closes_before_explanatory_prose():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    bundle_snippet = """```bash
revrem bundle-bug-report .revrem/runs/<run-id> --output revrem-bug.tar.gz
```"""

    assert bundle_snippet in readme
    assert "The bundle command ignores symlinked artifacts" in readme
    assert bundle_snippet.index("```", 3) < readme.index(
        "The bundle command ignores symlinked artifacts"
    )


def test_dev_extra_exercises_rich_and_textual_paths():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    dev_extra = pyproject["project"]["optional-dependencies"]["dev"]
    redaction_extra = pyproject["project"]["optional-dependencies"]["redaction"]

    assert any(dependency.startswith("jsonschema>=") for dependency in dev_extra)
    assert any(dependency.startswith("detect-secrets>=") for dependency in redaction_extra)
    assert any(dependency.startswith("rich>=") for dependency in dev_extra)
    assert any(dependency.startswith("textual>=") for dependency in dev_extra)


def test_source_tree_does_not_publish_top_level_dependency_shims():
    assert not (ROOT / "src" / "jsonschema" / "__init__.py").exists()
    assert not (ROOT / "src" / "jsonschema" / "validators.py").exists()
    assert not (ROOT / "src" / "tomli_w.py").exists()


def test_package_data_includes_versioned_prompts():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = pyproject["tool"]["setuptools"]["package-data"]["code_review_loop"]

    assert "prompts/*.txt" in package_data


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


def test_promote_stable_recreates_stale_stable_venv(tmp_path):
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env sh
case "$1" in
  -c)
    if [ "$FAKE_CURRENT_PYTHON_VERSION" = "old" ]; then
      exit 1
    fi
    exit 0
    ;;
  -m)
    if [ "$2" = "venv" ]; then
      marker=${FAKE_VENV_MARKER:?}
      mkdir -p "$3/bin"
      cat > "$3/bin/python" <<'EOF'
#!/usr/bin/env sh
exit 0
EOF
      chmod +x "$3/bin/python"
      touch "$marker"
      exit 0
    fi
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    stable_venv = home / ".local" / "share" / "revrem" / "stable-venv"
    stable_bin = stable_venv / "bin"
    stable_bin.mkdir(parents=True)
    stale_python = stable_bin / "python"
    stale_python.write_text(
        """#!/usr/bin/env sh
case "$1" in
  -c)
    exit 1
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    stale_python.chmod(0o755)
    stale_marker = stable_venv / "obsolete.txt"
    stale_marker.write_text("stale", encoding="utf-8")

    marker = tmp_path / "stable-venv-recreated"
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

    assert result.returncode == 0, result.stderr
    assert marker.exists()
    assert not stale_marker.exists()
    assert "exit 0" in stale_python.read_text(encoding="utf-8")
    assert (home / ".local" / "bin" / "revrem").exists()
    assert (home / ".local" / "bin" / "code-review-loop").exists()


def test_promote_stable_refreshes_runtime_dependency_on_reused_venv(tmp_path):
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env sh
case "$1" in
  -c)
    exit 0
    ;;
  -m)
    if [ "$2" = "pip" ]; then
      touch "${FAKE_PIP_MARKER:?}"
      exit 0
    fi
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    stable_venv = home / ".local" / "share" / "revrem" / "stable-venv"
    stable_bin = stable_venv / "bin"
    stable_bin.mkdir(parents=True)
    stable_python = stable_bin / "python"
    stable_python.write_text(
        """#!/usr/bin/env sh
case "$1" in
  -c)
    exit 0
    ;;
  -m)
    if [ "$2" = "pip" ]; then
      touch "${FAKE_PIP_MARKER:?}"
      exit 0
    fi
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    stable_python.chmod(0o755)
    preserved_marker = stable_venv / "preserved.txt"
    preserved_marker.write_text("keep", encoding="utf-8")

    marker = tmp_path / "pip-called"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "PYTHON": str(fake_python),
        "REVREM_SKIP_CHECKS": "1",
        "FAKE_PIP_MARKER": str(marker),
    }

    result = subprocess.run(
        ["sh", str(ROOT / "scripts/promote-stable")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert marker.exists()
    assert preserved_marker.exists()
    assert (home / ".local" / "bin" / "revrem").exists()
    assert (home / ".local" / "bin" / "code-review-loop").exists()


def test_install_dev_targets_repo_local_virtualenv():
    script = (ROOT / "scripts/install-dev").read_text(encoding="utf-8")

    assert "python -m venv .venv" not in script
    assert '"$PYTHON" -m venv .venv' in script
    assert './.venv/bin/python -m pip install -e ".[dev]"' in script
    assert 'PYTHONPATH="$REPO_ROOT/src\\${PYTHONPATH:+:\\$PYTHONPATH}"' in script


def test_install_dev_refuses_interpreters_older_than_python_311(tmp_path):
    repo = _prepare_temp_repo(tmp_path)
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
      mkdir -p "$3/bin"
      cat > "$3/bin/python" <<'EOF'
#!/usr/bin/env sh
case "$1" in
  -c)
    exit 1
    ;;
  -m)
    if [ "$2" = "pip" ]; then
      touch "${FAKE_PIP_MARKER:?}"
      exit 0
    fi
    ;;
esac
exit 0
EOF
      chmod +x "$3/bin/python"
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
    pip_marker = tmp_path / "unexpected-pip-call"
    venv_marker = tmp_path / "venv-created"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "PYTHON": str(fake_python),
        "FAKE_PIP_MARKER": str(pip_marker),
        "FAKE_VENV_MARKER": str(venv_marker),
    }

    result = subprocess.run(
        ["sh", str(repo / "scripts/install-dev")],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Python 3.11 or newer" in result.stderr
    assert venv_marker.exists()
    assert not pip_marker.exists()
    assert not (repo / ".venv" / "bin" / "code-review-loop").exists()
    assert not (repo / ".venv" / "bin" / "revrem").exists()


def test_install_dev_recreates_stale_virtualenv(tmp_path):
    repo = _prepare_temp_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env sh
case "$1" in
  -c)
    exit 0
    ;;
  -m)
    if [ "$2" = "venv" ]; then
      mkdir -p "$3/bin"
      cat > "$3/bin/python" <<'EOF'
#!/usr/bin/env sh
case "$1" in
  -c)
    exit 0
    ;;
  -m)
    if [ "$2" = "pip" ]; then
      touch "${FAKE_PIP_MARKER:?}"
      exit 0
    fi
    ;;
esac
exit 0
EOF
      chmod +x "$3/bin/python"
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

    venv_dir = repo / ".venv"
    stale_bin = venv_dir / "bin"
    stale_bin.mkdir(parents=True)
    stale_python = stale_bin / "python"
    stale_python.write_text(
        """#!/usr/bin/env sh
case "$1" in
  -c)
    exit 1
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    stale_python.chmod(0o755)
    stale_marker = venv_dir / "obsolete.txt"
    stale_marker.write_text("stale", encoding="utf-8")

    pip_marker = tmp_path / "pip-called"
    venv_marker = tmp_path / "venv-recreated"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "PYTHON": str(fake_python),
        "FAKE_PIP_MARKER": str(pip_marker),
        "FAKE_VENV_MARKER": str(venv_marker),
    }

    result = subprocess.run(
        ["sh", str(repo / "scripts/install-dev")],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert venv_marker.exists()
    assert pip_marker.exists()
    assert not stale_marker.exists()
    assert "exit 0" in stale_python.read_text(encoding="utf-8")
    assert not (repo / ".venv" / "bin" / "code-review-loop").exists()
    assert not (repo / ".venv" / "bin" / "revrem").exists()
