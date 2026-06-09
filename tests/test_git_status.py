from __future__ import annotations

from code_review_loop.config import LoopConfig
from code_review_loop.git_status import (
    is_artifact_path,
    non_artifact_status_entries_from_status_z,
    non_artifact_status_lines,
    untracked_paths_from_status_z,
)


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


def test_untracked_paths_from_status_z_returns_paths_verbatim() -> None:
    """The NUL-delimited parser must not strip, quote, or escape anything
    from the untracked path entries — that is the whole point of switching
    from ``--porcelain`` to ``-z`` for the cleanliness check.
    """
    assert untracked_paths_from_status_z("") == []
    assert untracked_paths_from_status_z("?? src/new.py\0?? tests/test_new.py\0") == [
        "src/new.py",
        "tests/test_new.py",
    ]
    assert untracked_paths_from_status_z("?? a b\0") == ["a b"]
    assert untracked_paths_from_status_z("?? back\\slash\0") == ["back\\slash"]
    assert untracked_paths_from_status_z('?? quote"file\0') == ['quote"file']
    # ``git status -z`` preserves literal newline bytes inside the path
    # component because NUL is the only record separator; a path that
    # contains a real newline stays intact between two ``?? `` status
    # codes on either side.
    assert untracked_paths_from_status_z("?? has\nnewline\0?? plain\0") == [
        "has\nnewline",
        "plain",
    ]


def test_untracked_paths_from_status_z_ignores_non_untracked_entries() -> None:
    """Only ``??`` status codes are relevant to the cleanliness check;
    other status codes (modified, deleted, renamed, etc.) must be skipped
    even when they appear between untracked entries.
    """
    stdout = (
        " M src/existing.py\0"  # modified, not untracked
        "?? src/added.py\0"  # untracked
        "D  src/removed.py\0"  # deleted, not untracked
        "?? docs/note.md\0"  # untracked
        "R  old.txt\0new.txt\0"  # renamed (3-part entry)
    )
    assert untracked_paths_from_status_z(stdout) == [
        "src/added.py",
        "docs/note.md",
    ]


def test_untracked_paths_from_status_z_skips_empty_path_entries() -> None:
    """Defensive: a malformed status line with no path after ``?? `` should
    be dropped rather than forwarded as an empty pathspec to ``git add``.
    """
    assert untracked_paths_from_status_z("?? \0?? src/real.py\0") == ["src/real.py"]


def test_non_artifact_status_entries_from_status_z_filters_artifacts(tmp_path):
    config = LoopConfig(cwd=tmp_path, artifact_dir=tmp_path / ".revrem" / "runs" / "r1")

    entries = non_artifact_status_entries_from_status_z(
        config,
        " M src/changed.py\0?? .revrem/runs/r1/review-1.txt\0?? docs/new note.md\0",
    )

    assert entries == (" M src/changed.py", "?? docs/new note.md")


def test_non_artifact_status_entries_from_status_z_handles_renames(tmp_path):
    config = LoopConfig(cwd=tmp_path, artifact_dir=tmp_path / "artifacts")

    entries = non_artifact_status_entries_from_status_z(
        config,
        "R  src/new.py\0src/old.py\0R  artifacts/new.txt\0artifacts/old.txt\0",
    )

    assert entries == ("R  src/old.py -> src/new.py",)


def test_is_artifact_path_matches_revrem_and_explicit_artifact_dir(tmp_path) -> None:
    """Path-based artifact check mirrors the line-based check, so a caller
    that already has decoded paths from ``git status -z`` can apply the
    same exemption without re-synthesising status lines.
    """
    (tmp_path / "artifacts").mkdir()
    config = LoopConfig(cwd=tmp_path, artifact_dir=tmp_path / "artifacts")

    assert is_artifact_path(config, "artifacts/review-1.txt") is True
    assert is_artifact_path(config, "artifacts") is True
    assert is_artifact_path(config, ".revrem/runs/run-1/x.txt") is True
    assert is_artifact_path(config, "src/code.py") is False
    assert is_artifact_path(config, "artifacts-old/leak.txt") is False
    assert is_artifact_path(config, "") is True
