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
