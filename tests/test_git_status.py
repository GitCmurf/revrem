from __future__ import annotations

from code_review_loop.config import LoopConfig
from code_review_loop.git_status import non_artifact_status_lines


def test_non_artifact_status_lines_match_artifact_dir_on_path_boundaries(tmp_path):
    config = LoopConfig(cwd=tmp_path, artifact_dir=tmp_path / "artifacts")

    dirty = non_artifact_status_lines(
        config,
        "\n".join(
            (
                "?? artifacts/review-1.txt",
                "?? artifacts2/leak.txt",
                "?? artifacts-old/leak.txt",
                "?? src/code.py",
            )
        ),
    )

    assert dirty == [
        "?? artifacts2/leak.txt",
        "?? artifacts-old/leak.txt",
        "?? src/code.py",
    ]


def test_non_artifact_status_lines_require_all_rename_paths_to_be_artifacts(tmp_path):
    config = LoopConfig(cwd=tmp_path, artifact_dir=tmp_path / "artifacts")

    dirty = non_artifact_status_lines(
        config,
        "\n".join(
            (
                "R  artifacts/old.txt -> artifacts/new.txt",
                "R  artifacts/old.txt -> artifacts2/new.txt",
            )
        ),
    )

    assert dirty == ["R  artifacts/old.txt -> artifacts2/new.txt"]


def test_non_artifact_status_lines_exempts_revrem_paths_when_run_from_subdirectory(tmp_path):
    """``git status --porcelain`` emits paths relative to the repository root
    even when RevRem is launched from a subdirectory. Artifact lines that
    appear under the cwd as ``subdir/.revrem/...`` must still be filtered out
    so subdirectory runs do not fail the worktree stability guard.
    """
    repo = tmp_path / "repo"
    subdir = repo / "sub"
    subdir.mkdir(parents=True)
    (repo / ".git").mkdir()
    config = LoopConfig(
        cwd=subdir,
        artifact_dir=subdir / ".revrem" / "runs" / "run-1",
    )

    dirty = non_artifact_status_lines(
        config,
        "\n".join(
            (
                "?? sub/.revrem/runs/run-1/review.txt",
                "?? sub/.revrem/runs/run-1/remediation.txt",
                "?? sub/src/code.py",
                "?? sub/note.txt",
            )
        ),
    )

    assert dirty == [
        "?? sub/src/code.py",
        "?? sub/note.txt",
    ]


def test_non_artifact_status_lines_exempts_explicit_artifact_dir_from_subdirectory(tmp_path):
    """When ``artifact_dir`` is configured explicitly under a subdirectory,
    the helper should accept both the cwd-relative form (e.g. ``artifacts/...``)
    and the repo-root-relative form (``sub/artifacts/...``) emitted by
    ``git status`` in a subdirectory run.
    """
    repo = tmp_path / "repo"
    subdir = repo / "sub"
    subdir.mkdir(parents=True)
    (repo / ".git").mkdir()
    config = LoopConfig(cwd=subdir, artifact_dir=subdir / "artifacts")

    dirty = non_artifact_status_lines(
        config,
        "\n".join(
            (
                "?? sub/artifacts/review-1.txt",
                "?? sub/artifacts-old/leak.txt",
                "?? sub/src/code.py",
            )
        ),
    )

    assert dirty == [
        "?? sub/artifacts-old/leak.txt",
        "?? sub/src/code.py",
    ]


def test_non_artifact_status_lines_falls_back_to_cwd_when_no_git_root(tmp_path):
    """Outside a git worktree the helper should still exempt the artifact
    directory when it appears as a cwd-relative path. This preserves the
    original behaviour for non-repo runs.
    """
    config = LoopConfig(cwd=tmp_path, artifact_dir=tmp_path / "artifacts")

    dirty = non_artifact_status_lines(
        config,
        "\n".join(
            (
                "?? artifacts/review-1.txt",
                "?? src/code.py",
            )
        ),
    )

    assert dirty == ["?? src/code.py"]
