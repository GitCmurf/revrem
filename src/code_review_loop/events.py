"""Event envelope and JSONL replay helpers for RevRem."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from code_review_loop import artifacts

EVENT_SCHEMA_VERSION = "1.0"
EVENTS_FILENAME = "events.jsonl"
EVENT_KINDS = (
    "phase_start",
    "phase_output",
    "phase_result",
    "status_classification",
    "check_result",
    "artifact_write",
    "warning",
    "failure",
    "summary",
    "suppressed",
    "cancellation",
    "cost_charge",
    "cost_ceiling_hit",
)


@dataclass(frozen=True)
class Event:
    run_id: str
    seq: int
    kind: str
    phase: str | None = None
    iteration: int | str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    schema_version: str = EVENT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], artifacts.canonicalize_json(asdict(self)))


class EventSink(Protocol):
    def emit(
        self,
        kind: str,
        *,
        phase: str | None = None,
        iteration: int | str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        """Record one event."""

    def close(self) -> None:
        """Flush resources held by the sink."""


class InMemorySink:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.events: list[Event] = []

    def emit(
        self,
        kind: str,
        *,
        phase: str | None = None,
        iteration: int | str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        event = make_event(
            run_id=self.run_id,
            seq=len(self.events) + 1,
            kind=kind,
            phase=phase,
            iteration=iteration,
            payload=payload or {},
        )
        self.events.append(event)
        return event

    def close(self) -> None:
        return None


class JsonlSink:
    def __init__(self, run_dir: Path, run_id: str):
        self.run_dir = run_dir
        self.run_id = run_id
        self.path = artifacts.safe_artifact_path(run_dir, EVENTS_FILENAME)
        self._seq = 0
        self._handle = self.path.open("a", encoding="utf-8")

    def emit(
        self,
        kind: str,
        *,
        phase: str | None = None,
        iteration: int | str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        self._seq += 1
        event = make_event(
            run_id=self.run_id,
            seq=self._seq,
            kind=kind,
            phase=phase,
            iteration=iteration,
            payload=payload or {},
        )
        self._handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        if kind in {"phase_result", "failure", "summary", "cancellation", "cost_ceiling_hit"}:
            self._handle.flush()
        return event

    def close(self) -> None:
        self._handle.flush()
        self._handle.close()


def make_event(
    *,
    run_id: str,
    seq: int,
    kind: str,
    phase: str | None = None,
    iteration: int | str | None = None,
    payload: dict[str, Any] | None = None,
    ts: str | None = None,
) -> Event:
    if seq < 1:
        raise ValueError("event seq must be positive")
    if kind not in EVENT_KINDS:
        raise ValueError(f"unsupported event kind: {kind}")
    return Event(
        run_id=run_id,
        seq=seq,
        kind=kind,
        phase=phase,
        iteration=iteration,
        payload=payload or {},
        ts=ts or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def read_events(path: Path) -> tuple[list[Event], bool]:
    events: list[Event] = []
    truncated = False
    expected_seq = 1
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            event = event_from_dict(payload)
        except (json.JSONDecodeError, ValueError, TypeError):
            truncated = True
            break
        if event.seq != expected_seq:
            raise ValueError(f"event seq gap: expected {expected_seq}, got {event.seq}")
        events.append(event)
        expected_seq += 1
    if truncated and events:
        events.append(
            make_event(
                run_id=events[-1].run_id,
                seq=expected_seq,
                kind="failure",
                phase="replay",
                payload={"reason": "truncated_events_jsonl"},
            )
        )
    return events, truncated


def event_from_dict(payload: dict[str, Any]) -> Event:
    if payload.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError("unsupported event schema_version")
    run_id = payload.get("run_id")
    seq = payload.get("seq")
    kind = payload.get("kind")
    event_payload = payload.get("payload", {})
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("event run_id must be a non-empty string")
    if not isinstance(seq, int):
        raise ValueError("event seq must be an integer")
    if not isinstance(kind, str):
        raise ValueError("event kind must be a string")
    if not isinstance(event_payload, dict):
        raise ValueError("event payload must be an object")
    phase = payload.get("phase")
    if phase is not None and not isinstance(phase, str):
        raise ValueError("event phase must be a string or null")
    iteration = payload.get("iteration")
    if iteration is not None and not isinstance(iteration, int | str):
        raise ValueError("event iteration must be a string, integer, or null")
    ts = payload.get("ts")
    if not isinstance(ts, str):
        raise ValueError("event ts must be a string")
    return make_event(
        run_id=run_id,
        seq=seq,
        kind=kind,
        phase=phase,
        iteration=iteration,
        payload=event_payload,
        ts=ts,
    )


def render_compact(events: list[Event]) -> str:
    lines: list[str] = []
    for event in events:
        phase = event.phase or event.kind
        label = "" if event.iteration is None else str(event.iteration)
        detail = _compact_detail(event)
        label_part = f"|{label}" if label else ""
        detail_part = f": {detail}" if detail else ""
        lines.append(f"{event.seq:04d}|{phase}{label_part}|{event.kind}{detail_part}")
    return "\n".join(lines) + ("\n" if lines else "")


def _compact_detail(event: Event) -> str:
    for key in ("status", "reason", "message", "summary"):
        value = event.payload.get(key)
        if isinstance(value, str):
            return value
    return ""
