"""Create deterministic, redacted RevRem bug-report bundles."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path

from code_review_loop import artifacts, redaction, suppressions

BUG_BUNDLE_SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "bug-bundle.json"
DEFAULT_JSON_NAMES = {"summary.json", "diagnostics.json", "events.jsonl"}


@dataclass(frozen=True)
class BundleOptions:
    run_dir: Path
    output_path: Path | None = None
    include_raw_transcripts: bool = False
    redact: bool = True


@dataclass(frozen=True)
class BundleResult:
    output_path: Path
    manifest: dict[str, object]


def create_bug_bundle(options: BundleOptions) -> BundleResult:
    run_dir = options.run_dir.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run directory not found: {options.run_dir}")

    output_path = (options.output_path or default_output_path(run_dir)).resolve()
    entries: list[tuple[str, bytes]] = []
    redaction_counts: dict[str, int] = {}
    for path in _bundle_files(run_dir, include_raw_transcripts=options.include_raw_transcripts):
        arcname = path.relative_to(run_dir).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace")
        if options.redact:
            result = redaction.redact_text(content)
            content = result.text
            _merge_counts(redaction_counts, redaction.redaction_summary(result))
        entries.append((arcname, content.encode("utf-8")))
    for path in _suppression_audit_paths(run_dir):
        summary = suppressions.audit_summary(path)
        if summary is None:
            continue
        arcname = f"suppressions/{path.stem}.summary.json"
        content = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        entries.append((arcname, content.encode("utf-8")))

    manifest = {
        "schema_version": BUG_BUNDLE_SCHEMA_VERSION,
        "run_id": _run_id(run_dir),
        "source_run_dir_name": run_dir.name,
        "include_raw_transcripts": options.include_raw_transcripts,
        "redacted": options.redact,
        "files": [arcname for arcname, _content in entries],
        "suppression_audit_summaries": [
            arcname for arcname, _content in entries if arcname.startswith("suppressions/")
        ],
        "redaction_counts": redaction_counts,
    }
    manifest_bytes = (
        json.dumps(
            artifacts.canonicalize_json(manifest),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        output_path.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        _add_bytes(tar, MANIFEST_NAME, manifest_bytes)
        for arcname, bundle_bytes in entries:
            _add_bytes(tar, arcname, bundle_bytes)
    return BundleResult(output_path=output_path, manifest=manifest)


def default_output_path(run_dir: Path) -> Path:
    return Path.cwd() / f"revrem-bug-{_run_id(run_dir)}.tar.gz"


def _bundle_files(run_dir: Path, *, include_raw_transcripts: bool) -> list[Path]:
    candidates = []
    for path in run_dir.rglob("*"):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(run_dir).as_posix()
        if relative == MANIFEST_NAME:
            continue
        if path.name in DEFAULT_JSON_NAMES or path.name.startswith("check-"):
            candidates.append(path)
            continue
        if include_raw_transcripts and path.name == "suppressions.audit.jsonl":
            candidates.append(path)
            continue
        if include_raw_transcripts and path.suffix == ".txt":
            candidates.append(path)
    return sorted(candidates, key=lambda item: item.relative_to(run_dir).as_posix())


def _add_bytes(tar: tarfile.TarFile, arcname: str, content: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(content)
    info.mtime = 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tar.addfile(info, io.BytesIO(content))


def _run_id(run_dir: Path) -> str:
    summary_path = run_dir / "summary.json"
    if summary_path.is_file() and not summary_path.is_symlink():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary = {}
        run_id = summary.get("run_id") if isinstance(summary, dict) else None
        if isinstance(run_id, str):
            return run_id
    return run_dir.name


def _suppression_audit_paths(run_dir: Path) -> list[Path]:
    paths = []
    for candidate in (
        run_dir / ".revrem" / "suppressions.audit.jsonl",
        run_dir.parent / ".revrem" / "suppressions.audit.jsonl",
    ):
        if candidate.is_file() and not candidate.is_symlink():
            paths.append(candidate)
    return sorted(set(paths))


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value
