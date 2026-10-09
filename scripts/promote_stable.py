"""Install and activate isolated local releases; never mutate the active venv."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(argv: list[str], *, cwd: Path, capture: bool = False) -> str:
    result = subprocess.run(argv, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout or ""


def atomic_link(target: Path, link: Path) -> None:
    temporary = link.with_name(f".{link.name}-{os.getpid()}")
    try:
        temporary.symlink_to(target)
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)


def selected_release(home: Path, name: str) -> Path | None:
    link = home / name
    if not link.is_symlink():
        if link.exists():
            raise ValueError(f"Refusing to replace non-symlink {link}")
        return None
    release = link.resolve(strict=True)
    if release.parent != (home / "releases").resolve():
        raise ValueError(f"{link} points outside the managed releases directory")
    return release


def smoke(release: Path) -> None:
    """Import installed resources outside the checkout, ignoring PYTHONPATH."""
    python = str(release / "venv/bin/python")
    with tempfile.TemporaryDirectory(prefix="revrem-installed-") as directory:
        cwd = Path(directory)
        run([python, "-I", "-m", "pip", "check"], cwd=cwd)
        for command in ("revrem", "code-review-loop"):
            run([str(release / "venv/bin" / command), "--version"], cwd=cwd)
        run([python, "-I", "-m", "code_review_loop", "--help"], cwd=cwd, capture=True)
        run([python, "-I", "-c",
             "import jsonschema, tomli_w; from importlib.resources import files; "
             "p=files('code_review_loop'); "
             "assert p.joinpath('catalog.toml').is_file(); "
             "assert list(p.joinpath('schemas').iterdir()); "
             "assert list(p.joinpath('prompts').iterdir()); "
             "assert list(p.joinpath('expert_profiles').iterdir())"], cwd=cwd)
        run([python, "-I", str(release / "source/scripts/smoke_installed.py"), python], cwd=cwd)


def install_release(home: Path, extras: str) -> Path:
    dirty = run(["git", "status", "--porcelain"], cwd=ROOT, capture=True)
    if dirty.strip():
        raise ValueError("Commit or stash changes before promotion; only clean snapshots are promoted.")
    commit = run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture=True).strip()
    if os.environ.get("REVREM_SKIP_CHECKS") != "1":
        run([str(ROOT / "scripts/dev-check")], cwd=ROOT)
    # Check again: verification hooks must not silently change the candidate.
    if run(["git", "status", "--porcelain"], cwd=ROOT, capture=True).strip():
        raise ValueError("Verification changed the worktree; commit the result before promotion.")
    if run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture=True).strip() != commit:
        raise ValueError("HEAD changed during verification; retry promotion.")
    releases = home / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    release = Path(tempfile.mkdtemp(
        prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + commit[:12] + "-",
        dir=releases,
    ))
    try:
        # Archive the exact commit, excluding ignored/untracked transcripts and artifacts.
        archive = release / "source.tar"
        run(["git", "archive", "--format=tar", f"--output={archive}", commit], cwd=ROOT)
        source = release / "source"
        source.mkdir()
        run(["tar", "-xf", str(archive), "-C", str(source)], cwd=release)
        run([sys.executable, "-m", "venv", str(release / "venv")], cwd=release)
        python = str(release / "venv/bin/python")
        wheels = release / "wheels"
        run([python, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels),
             str(source)], cwd=release)
        wheel, = wheels.glob("revrem-*.whl")
        requirement = str(wheel) + (f"[{extras}]" if extras else "")
        run([python, "-m", "pip", "install", requirement], cwd=release)
        smoke(release)
        if extras:
            run([python, "-I", "-c", "import textual, rich"], cwd=release)
        manifest = {
            "commit": commit, "created_at": datetime.now(UTC).isoformat(),
            "wheel": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "extras": extras, "python": sys.version,
            "checks_skipped": os.environ.get("REVREM_SKIP_CHECKS") == "1",
            "packages": run([python, "-m", "pip", "freeze"], cwd=release, capture=True).splitlines(),
        }
        (release / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return release
    except BaseException:
        # The active install has not been touched. Delete only our new candidate.
        shutil.rmtree(release)
        raise


def install_launchers(home: Path, bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    body = ("#!/usr/bin/env sh\nset -eu\n"
            f"release=$(CDPATH= cd -- {shlex.quote(str(home / 'current'))} && pwd -P)\n"
            'exec "$release/venv/bin/python" -I -m code_review_loop "$@"\n')
    for name in ("revrem", "code-review-loop"):
        launcher = bin_dir / name
        # Preserve the pre-migration launcher once, including symlink targets.
        backup = bin_dir / f"{name}.before-managed-install"
        if (launcher.exists() or launcher.is_symlink()) and not backup.exists() and not backup.is_symlink():
            shutil.copy2(launcher, backup, follow_symlinks=False)
        fd, temporary = tempfile.mkstemp(prefix=f".{name}-", dir=bin_dir)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(body)
            os.chmod(temporary, 0o755)
            os.replace(temporary, launcher)
        finally:
            Path(temporary).unlink(missing_ok=True)


def activate_release(home: Path, bin_dir: Path, candidate: Path) -> None:
    """Restore both pointers and launchers if activation fails partway through."""
    current = selected_release(home, "current")
    previous = selected_release(home, "previous")
    bin_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".revrem-activation-", dir=bin_dir) as directory:
        backup_dir = Path(directory)
        for name in ("revrem", "code-review-loop"):
            launcher = bin_dir / name
            if launcher.exists() or launcher.is_symlink():
                shutil.copy2(launcher, backup_dir / name, follow_symlinks=False)
        try:
            install_launchers(home, bin_dir)
            if current is not None:
                atomic_link(current, home / "previous")
            atomic_link(candidate, home / "current")
        except BaseException:
            for name, target in (("current", current), ("previous", previous)):
                if target is None:
                    (home / name).unlink(missing_ok=True)
                else:
                    atomic_link(target, home / name)
            for name in ("revrem", "code-review-loop"):
                saved = backup_dir / name
                if saved.exists() or saved.is_symlink():
                    os.replace(saved, bin_dir / name)
                else:
                    (bin_dir / name).unlink(missing_ok=True)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rollback", action="store_true", help="Reactivate the previous installed release")
    mode.add_argument("--status", action="store_true", help="Print active and previous release manifests")
    parser.add_argument("--extras", choices=("tui",), default="", help="Include optional TUI and rich progress")
    args = parser.parse_args(argv)
    if os.environ.get("REVREM_STABLE_VENV"):
        parser.error("REVREM_STABLE_VENV is obsolete; use REVREM_STABLE_HOME for isolated releases")
    home = Path(os.environ.get("REVREM_STABLE_HOME", Path.home() / ".local/share/revrem")).expanduser().absolute()
    bin_dir = Path(os.environ.get("REVREM_BIN_DIR", Path.home() / ".local/bin")).expanduser().absolute()
    try:
        if args.status:
            result = {}
            for name in ("current", "previous"):
                release = selected_release(home, name)
                result[name] = None if release is None else {
                    "path": str(release), **json.loads((release / "manifest.json").read_text())}
            print(json.dumps(result, indent=2))
            return 0
        home.mkdir(parents=True, exist_ok=True)
        with (home / ".promotion.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Another promotion or rollback is running") from exc
            selected_release(home, "current")
            previous = selected_release(home, "previous")
            if args.rollback:
                if previous is None:
                    raise ValueError("No previous managed release to roll back to")
                smoke(previous)
                candidate = previous
            else:
                candidate = install_release(home, args.extras)
            # Both launchers resolve one pointer. Prepare them before switching.
            # On first migration, keep originals available for manual restoration.
            activate_release(home, bin_dir, candidate)
            print(f"Active release: {candidate}\nLaunchers: {bin_dir}/revrem, {bin_dir}/code-review-loop")
            print("Rollback: ./scripts/promote-stable --rollback")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
