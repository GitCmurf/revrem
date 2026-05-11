from __future__ import annotations

import json
from decimal import Decimal

import pytest

from code_review_loop import artifacts


def test_write_json_artifact_is_canonical_and_schema_stamped(tmp_path):
    run_dir = tmp_path / "run"

    path = artifacts.write_json_artifact(
        run_dir,
        "summary.json",
        {
            "usd": Decimal("0.0345"),
            "message": "Cafe\u0301",
            "nested": {"b": 2, "a": 1},
        },
    )

    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert json.loads(content) == {
        "message": "Café",
        "nested": {"a": 1, "b": 2},
        "schema_version": "1.0",
        "usd": "0.0345",
    }
    assert content.index('"a"') < content.index('"b"')


def test_write_json_artifact_round_trip_is_byte_identical(tmp_path):
    run_dir = tmp_path / "run"
    payload = {"items": [{"name": "alpha"}, {"name": "beta"}]}

    first = artifacts.write_json_artifact(run_dir, "events/summary.json", payload)
    first_bytes = first.read_bytes()
    second = artifacts.write_json_artifact(run_dir, "events/summary.json", json.loads(first.read_text()))

    assert second.read_bytes() == first_bytes


@pytest.mark.parametrize(
    "relative_path",
    [
        "../summary.json",
        "/tmp/summary.json",
        "nested/../summary.json",
        ".",
    ],
)
def test_safe_artifact_path_rejects_traversal(tmp_path, relative_path):
    with pytest.raises(artifacts.ArtifactPathError):
        artifacts.safe_artifact_path(tmp_path / "run", relative_path)


def test_safe_artifact_path_rejects_symlink_escape(tmp_path):
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.mkdir()
    run_dir.mkdir()
    (run_dir / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(artifacts.ArtifactPathError):
        artifacts.safe_artifact_path(run_dir, "linked/summary.json")
