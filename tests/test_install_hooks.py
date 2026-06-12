from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from code_review_loop.cli.main import main as cli_main


def _init_repo(path: Path) -> None:
    path.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)


def test_install_hooks_installs_managed_executable_hooks(tmp_path, capsys):
    _init_repo(tmp_path)

    rc = cli_main(["install-hooks", "--cwd", str(tmp_path), "--format", "json"])

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert [item["hook"] for item in output] == ["pre-commit", "pre-push"]
    for hook_name in ("pre-commit", "pre-push"):
        hook = tmp_path / ".git" / "hooks" / hook_name
        text = hook.read_text(encoding="utf-8")
        assert "REVREM_MANAGED_HOOK: begin" in text
        assert f'REVREM_HOOK_TYPE="{hook_name}"' in text
        assert os.access(hook, os.X_OK)


def test_install_hooks_uses_configured_hooks_path(tmp_path, capsys):
    _init_repo(tmp_path)
    subprocess.run(
        ["git", "config", "core.hooksPath", ".custom-hooks"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    rc = cli_main(["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit"])

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    installed_path = Path(output[0]["path"])
    expected_path = tmp_path / ".custom-hooks" / "pre-commit"
    assert installed_path == expected_path
    assert installed_path.read_text(encoding="utf-8").startswith("#!/bin/sh\n# REVREM_MANAGED_HOOK: begin")
    assert not (tmp_path / ".git" / "hooks" / "pre-commit").exists()


def test_install_hooks_rejects_non_repo_cwd_even_with_global_hooks_path(
    tmp_path, capsys, monkeypatch
):
    home = tmp_path / "home"
    config_home = home / ".config"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    subprocess.run(
        ["git", "config", "--global", "core.hooksPath", ".global-hooks"],
        check=True,
        capture_output=True,
    )
    cwd = tmp_path / "not-a-repo"
    cwd.mkdir()

    rc = cli_main(["install-hooks", "--cwd", str(cwd), "--type", "pre-commit"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "not a Git repository" in captured.err
    assert not (cwd / ".global-hooks" / "pre-commit").exists()


def test_install_hooks_refuses_unmanaged_hook_without_force(tmp_path, capsys):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    rc = cli_main(["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "not RevRem-managed" in captured.err


def test_install_hooks_refuses_broken_symlink_hook_without_force(tmp_path, capsys):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    target = tmp_path / "outside" / "pre-commit"
    hook = hooks / "pre-commit"
    hook.symlink_to(target)

    rc = cli_main(["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "not RevRem-managed" in captured.err
    assert hook.is_symlink()
    assert hook.readlink() == target
    assert not target.exists()


def test_install_hooks_force_backs_up_unmanaged_hook(tmp_path, capsys):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)

    rc = cli_main(
        ["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit", "--force"]
    )

    assert rc == 0
    capsys.readouterr()
    backup = hooks / "pre-commit.revrem-backup"
    assert backup.read_text(encoding="utf-8") == "#!/bin/sh\necho existing\n"
    assert "REVREM_MANAGED_HOOK: begin" in hook.read_text(encoding="utf-8")


def test_install_hooks_force_backs_up_broken_symlink_hook(tmp_path, capsys):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    target = tmp_path / "outside" / "pre-commit"
    hook = hooks / "pre-commit"
    hook.symlink_to(target)

    rc = cli_main(
        ["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit", "--force"]
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    backup = hooks / "pre-commit.revrem-backup"
    assert output[0]["backup_path"] == str(backup)
    assert backup.is_symlink()
    assert backup.readlink() == target
    assert not target.exists()
    assert not hook.is_symlink()
    assert "REVREM_MANAGED_HOOK: begin" in hook.read_text(encoding="utf-8")


def test_install_hooks_refuses_symlink_to_managed_text_without_force(tmp_path, capsys):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    target = tmp_path / "outside" / "shared-pre-commit"
    target.parent.mkdir()
    target.write_text(
        "#!/bin/sh\n# REVREM_MANAGED_HOOK: begin\nexit 0\n# REVREM_MANAGED_HOOK: end\n",
        encoding="utf-8",
    )
    hook = hooks / "pre-commit"
    hook.symlink_to(target)

    rc = cli_main(["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "not RevRem-managed" in captured.err
    assert hook.is_symlink()
    assert hook.readlink() == target
    assert target.read_text(encoding="utf-8").startswith("#!/bin/sh\n# REVREM_MANAGED_HOOK")


def test_install_hooks_force_backs_up_symlink_to_managed_text(tmp_path, capsys):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    target = tmp_path / "outside" / "shared-pre-commit"
    target.parent.mkdir()
    target_text = (
        "#!/bin/sh\n# REVREM_MANAGED_HOOK: begin\nexit 0\n# REVREM_MANAGED_HOOK: end\n"
    )
    target.write_text(target_text, encoding="utf-8")
    hook = hooks / "pre-commit"
    hook.symlink_to(target)

    rc = cli_main(
        ["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit", "--force"]
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    backup = hooks / "pre-commit.revrem-backup"
    assert output[0]["backup_path"] == str(backup)
    assert backup.is_symlink()
    assert backup.readlink() == target
    assert target.read_text(encoding="utf-8") == target_text
    assert not hook.is_symlink()
    assert "REVREM_MANAGED_HOOK: begin" in hook.read_text(encoding="utf-8")


def test_install_hooks_uninstall_skips_symlink_to_managed_text(tmp_path, capsys):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    target = tmp_path / "outside" / "shared-pre-commit"
    target.parent.mkdir()
    target.write_text(
        "#!/bin/sh\n# REVREM_MANAGED_HOOK: begin\nexit 0\n# REVREM_MANAGED_HOOK: end\n",
        encoding="utf-8",
    )
    hook = hooks / "pre-commit"
    hook.symlink_to(target)

    rc = cli_main(
        ["install-hooks", "--cwd", str(tmp_path), "--type", "pre-commit", "--uninstall"]
    )

    output = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert output[0]["status"] == "skipped"
    assert hook.is_symlink()
    assert hook.readlink() == target
    assert target.exists()


def test_install_hooks_uninstall_only_removes_managed_hooks(tmp_path, capsys):
    _init_repo(tmp_path)
    assert cli_main(["install-hooks", "--cwd", str(tmp_path), "--type", "pre-push"]) == 0
    capsys.readouterr()

    rc = cli_main(
        ["install-hooks", "--cwd", str(tmp_path), "--type", "pre-push", "--uninstall"]
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output[0]["status"] == "removed"
    assert not (tmp_path / ".git" / "hooks" / "pre-push").exists()


def test_install_hooks_resolves_git_file_worktree_hook_dir(tmp_path, capsys):
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    _init_repo(repo)
    subprocess.run(
        ["git", "config", "user.email", "revrem@example.test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "RevRem Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(linked), "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert (linked / ".git").is_file()

    rc = cli_main(["install-hooks", "--cwd", str(linked), "--type", "pre-commit"])

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    installed = Path(output[0]["path"])
    assert installed.exists()
    assert installed.name == "pre-commit"
    assert installed.parent != linked / ".git" / "hooks"
    assert "REVREM_MANAGED_HOOK: begin" in installed.read_text(encoding="utf-8")
