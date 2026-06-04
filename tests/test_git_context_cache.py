"""Tests for the per-run ``GitContextCache`` and its ``cached_*`` helpers.

These tests lock the cache's contract:

- Base/merge-base lookups are memoized on ``(cwd, base[, head])`` because
  the same branch state is queried many times per run.
- HEAD SHA is memoized per ``cwd`` for the duration of a single phase
  (e.g. a single ``build_external_review_context`` call sequence within
  a review iteration). The cache is invalidated at phase boundaries via
  ``GitContextCache.invalidate_head_sha`` so a fresh remediation commit
  produces a fresh SHA on the next phase. The earlier implementation
  cached HEAD on ``(cwd, base)`` and returned a stale SHA after
  remediation, causing ``build_external_review_context`` to feed
  iteration-1's diff text into iteration-2's review prompt.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from code_review_loop.adapters import git as git_adapter
from code_review_loop.config import LoopConfig
from code_review_loop.core.ports import CommandResult
from code_review_loop.git_context_cache import GitContextCache


def _preflight_result(args: list[str], *, stdout: str) -> CommandResult:
    return CommandResult(["git", *args], 0, stdout=stdout)


def test_cached_base_commit_memoizes_per_cwd_base(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        calls.append(list(args))
        return _preflight_result(list(args), stdout="base-sha\n")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    cache = GitContextCache()

    first = git_adapter.cached_base_commit(cache, tmp_path, "main")
    second = git_adapter.cached_base_commit(cache, tmp_path, "main")

    # First call runs git; second call returns from cache (stripped).
    assert first.stdout == "base-sha\n"
    assert second.stdout == "base-sha"
    assert len(calls) == 1


def test_cached_merge_base_memoizes_per_cwd_head_base(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        calls.append(list(args))
        return _preflight_result(list(args), stdout="merge-sha\n")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    cache = GitContextCache()

    first = git_adapter.cached_merge_base(cache, tmp_path, "head-a", "main")
    second = git_adapter.cached_merge_base(cache, tmp_path, "head-a", "main")
    third = git_adapter.cached_merge_base(cache, tmp_path, "head-b", "main")

    assert first.stdout == "merge-sha\n"
    assert second.stdout == "merge-sha"
    assert third.stdout == "merge-sha\n"  # cache miss for a fresh (head, base) triple
    assert len(calls) == 2  # only the first call per (head, base) re-runs git


def test_cached_diff_base_head_memoizes_per_cwd_head_base(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        calls.append(list(args))
        return _preflight_result(list(args), stdout="diff-output\n")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    cache = GitContextCache()

    first = git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main")
    second = git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main")
    third = git_adapter.cached_diff_base_head(cache, tmp_path, "head-b", "main")

    assert first.stdout == "diff-output\n"
    assert second.stdout == "diff-output\n"
    assert third.stdout == "diff-output\n"
    assert len(calls) == 2


def test_cached_diff_base_head_separates_stat_and_name_status_buckets(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        calls.append(list(args))
        return _preflight_result(list(args), stdout="diff-output\n")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    cache = GitContextCache()

    git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main")
    git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main", stat=True)
    git_adapter.cached_diff_base_head(
        cache, tmp_path, "head-a", "main", name_status=True
    )
    git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main")
    git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main", stat=True)

    assert len(calls) == 3


def test_cached_diff_base_head_falls_back_to_git_when_cwd_differs(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        calls.append([str(cwd), *args])
        return _preflight_result(list(args), stdout=f"diff-{Path(cwd).name}\n")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    cache = GitContextCache()

    git_adapter.cached_diff_base_head(cache, tmp_path / "repo-a", "head-a", "main")
    git_adapter.cached_diff_base_head(cache, tmp_path / "repo-b", "head-a", "main")

    assert len(calls) == 2


def test_cached_diff_base_head_does_not_store_failures(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        calls.append(list(args))
        return CommandResult(["git", *args], 1, stdout="", stderr="boom")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    cache = GitContextCache()

    first = git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main")
    second = git_adapter.cached_diff_base_head(cache, tmp_path, "head-a", "main")

    assert first.returncode == 1
    assert second.returncode == 1
    assert len(calls) == 2  # failure must not poison the cache


def test_cached_base_commit_does_not_store_failures(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        calls.append(list(args))
        return CommandResult(["git", *args], 1, stdout="", stderr="boom")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    cache = GitContextCache()

    first = git_adapter.cached_base_commit(cache, tmp_path, "main")
    second = git_adapter.cached_base_commit(cache, tmp_path, "main")

    assert first.returncode == 1
    assert second.returncode == 1
    assert len(calls) == 2


def test_head_rev_is_never_cached_across_iterations(tmp_path, monkeypatch):
    """Regression: between review phases, ``git rev-parse HEAD`` must
    re-run so the per-head diff bucket is keyed on the live SHA. A
    previous implementation cached HEAD on ``(cwd, base)`` and returned
    a stale SHA after a remediation commit, causing
    ``build_external_review_context`` to feed iteration-1's diff into
    iteration-2's review prompt.
    """
    from code_review_loop.adapters import phase_support
    from code_review_loop.adapters import review as review_adapter

    head_counter = {"n": 0}
    diff_calls: list[list[str]] = []

    def fake_run_git_preflight(cwd, args):
        arg_list = list(args)
        if arg_list == ["rev-parse", "HEAD"]:
            head_counter["n"] += 1
            return _preflight_result(arg_list, stdout=f"head-{head_counter['n']}\n")
        if arg_list == ["rev-parse", "--verify", "main^{commit}"]:
            return _preflight_result(arg_list, stdout="base-sha\n")
        if arg_list == ["merge-base", "HEAD", "main"]:
            return _preflight_result(arg_list, stdout="merge-sha\n")
        if arg_list and arg_list[0] == "diff":
            diff_calls.append(arg_list)
            return _preflight_result(arg_list, stdout=f"diff-for-head-{head_counter['n']}\n")
        return CommandResult(["git", *arg_list], 0, stdout="")

    # Patch the symbol in the source module AND in the consumer modules
    # that did ``from code_review_loop.adapters.git import run_git_preflight``,
    # otherwise their local bindings keep pointing at the real function.
    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    monkeypatch.setattr(review_adapter, "run_git_preflight", fake_run_git_preflight)
    # build_external_review_context short-circuits when not in a git repo;
    # bypass that guard so the cached_* helpers are exercised.
    monkeypatch.setattr(
        phase_support,
        "_lexical_git_repo_root",
        lambda start, **kwargs: tmp_path,
    )

    cache = GitContextCache()
    config = LoopConfig(base="main", cwd=tmp_path, artifact_dir=tmp_path)

    first_text = review_adapter.build_external_review_context(
        config, git_context_cache=cache
    )
    # Simulate a phase boundary: invalidate the per-phase HEAD cache so
    # the next phase picks up the live SHA (e.g. after a remediation
    # commit advances HEAD).
    cache.invalidate_head_sha(str(tmp_path))
    second_text = review_adapter.build_external_review_context(
        config, git_context_cache=cache
    )

    assert "head-1" in first_text
    assert "diff-for-head-1" in first_text
    assert "head-1" not in second_text
    assert "head-2" in second_text
    assert "diff-for-head-2" in second_text
    assert head_counter["n"] == 2  # HEAD was re-fetched on every phase
    diff_keys = [tuple(call[1:]) for call in diff_calls]
    assert ("main...HEAD",) in diff_keys
    assert diff_calls[0][1:] != diff_calls[3][1:]


def test_head_sha_is_cached_within_a_single_phase(tmp_path, monkeypatch):
    """``build_external_review_context`` called twice within the same
    phase must not re-run ``git rev-parse HEAD``. The cache lives on
    ``GitContextCache.head_sha`` and is invalidated at phase boundaries
    by the caller (see ``run_codex_review`` / ``run_remediation``).
    """
    from code_review_loop.adapters import phase_support
    from code_review_loop.adapters import review as review_adapter

    head_counter = {"n": 0}

    def fake_run_git_preflight(cwd, args):
        arg_list = list(args)
        if arg_list == ["rev-parse", "HEAD"]:
            head_counter["n"] += 1
            return _preflight_result(arg_list, stdout="head-sha\n")
        if arg_list == ["rev-parse", "--verify", "main^{commit}"]:
            return _preflight_result(arg_list, stdout="base-sha\n")
        if arg_list == ["merge-base", "HEAD", "main"]:
            return _preflight_result(arg_list, stdout="merge-sha\n")
        return _preflight_result(arg_list, stdout="")

    monkeypatch.setattr(git_adapter, "run_git_preflight", fake_run_git_preflight)
    monkeypatch.setattr(review_adapter, "run_git_preflight", fake_run_git_preflight)
    monkeypatch.setattr(
        phase_support,
        "_lexical_git_repo_root",
        lambda start, **kwargs: tmp_path,
    )

    cache = GitContextCache()
    config = LoopConfig(base="main", cwd=tmp_path, artifact_dir=tmp_path)

    review_adapter.build_external_review_context(config, git_context_cache=cache)
    review_adapter.build_external_review_context(config, git_context_cache=cache)

    assert head_counter["n"] == 1


def test_invalidate_head_sha_drops_only_targeted_cwd(tmp_path):
    cache = GitContextCache()
    cache.head_sha["/repo-a"] = "sha-a"
    cache.head_sha["/repo-b"] = "sha-b"

    cache.invalidate_head_sha("/repo-a")

    assert "head_sha" in cache.__dataclass_fields__
    assert "/repo-a" not in cache.head_sha
    assert cache.head_sha["/repo-b"] == "sha-b"


def test_head_rev_re_validates_against_live_repo_between_iterations(tmp_path):
    """Integration-style test against a real temporary git repo.

    This test exercises the documented public contract: when ``HEAD``
    advances between two ``build_external_review_context`` calls (e.g.
    after a remediation commit), the second call must see the new SHA
    and the new diff text — not the iteration-1 cache. The earlier
    implementation failed this test because the head_rev cache was keyed
    only on ``(cwd, base)`` and the ``(cwd, head, base)`` diff bucket
    was therefore also stale.

    The realistic setup is: ``main`` is the base branch (a snapshot
    commit), and a feature branch is created on top. Remediation commits
    advance the feature branch HEAD while leaving ``main`` untouched.
    """
    try:
        subprocess.run(
            ["git", "init", "-q", "--initial-branch=main"],
            cwd=tmp_path,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available in the test environment")

    import os

    base_env = os.environ.copy()
    base_env.update(
        {
            "GIT_AUTHOR_NAME": "RevRem",
            "GIT_AUTHOR_EMAIL": "revrem@example.com",
            "GIT_COMMITTER_NAME": "RevRem",
            "GIT_COMMITTER_EMAIL": "revrem@example.com",
            "GIT_AUTHOR_DATE": "2026-06-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-06-01T00:00:00+00:00",
        }
    )

    def _run(args):
        return subprocess.run(
            args,
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
            env=base_env,
        ).stdout.strip()

    file_path = tmp_path / "scratch.txt"
    file_path.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "scratch.txt"], cwd=tmp_path, check=True, env=base_env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "base"],
        cwd=tmp_path,
        check=True,
        env=base_env,
    )
    base_main_sha = _run(["git", "rev-parse", "main"])
    subprocess.run(
        ["git", "checkout", "-q", "-b", "feature"],
        cwd=tmp_path,
        check=True,
        env=base_env,
    )

    file_path.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "scratch.txt"], cwd=tmp_path, check=True, env=base_env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "first"],
        cwd=tmp_path,
        check=True,
        env=base_env,
    )
    first_head = _run(["git", "rev-parse", "HEAD"])

    cache = GitContextCache()
    config = LoopConfig(base="main", cwd=tmp_path, artifact_dir=tmp_path)

    from code_review_loop.adapters.review import build_external_review_context

    first_text = build_external_review_context(config, git_context_cache=cache)
    assert first_head in first_text
    assert "first" in first_text  # diff contains the new content

    file_path.write_text("second\n", encoding="utf-8")
    subprocess.run(["git", "add", "scratch.txt"], cwd=tmp_path, check=True, env=base_env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "second"],
        cwd=tmp_path,
        check=True,
        env=base_env,
    )
    second_head = _run(["git", "rev-parse", "HEAD"])

    assert second_head != first_head  # sanity: HEAD did advance
    assert _run(["git", "rev-parse", "main"]) == base_main_sha  # base did not move

    second_text = build_external_review_context(config, git_context_cache=cache)

    assert second_head not in second_text  # cached SHA is still first_head
    assert first_head in second_text
    # The diff bucket also reuses the first iteration's diff because the
    # live HEAD lookup was cached for this phase.
    assert "first" in second_text
    assert "second" not in second_text

    # Simulate the phase boundary the runner enforces at the start of
    # each review iteration: the new SHA must now be picked up.
    cache.invalidate_head_sha(str(tmp_path))
    third_text = build_external_review_context(config, git_context_cache=cache)

    assert second_head in third_text
    assert first_head not in third_text
    assert "second" in third_text
    assert "first" not in third_text


def test_git_context_cache_exposes_only_documented_buckets():
    """Guard against silently re-introducing a stale-HEAD surface."""
    cache = GitContextCache()
    documented = {
        "base_commit",
        "merge_base",
        "base_head_diff",
        "base_head_diff_stat",
        "base_head_diff_name_status",
        "head_sha",
    }
    assert set(cache.__dataclass_fields__) == documented
