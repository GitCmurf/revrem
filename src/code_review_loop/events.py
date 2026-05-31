"""Event envelope and JSONL replay helpers for RevRem."""

from __future__ import annotations

import errno
import json
import os
import queue
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from code_review_loop import artifacts
from code_review_loop.clock import SYSTEM_CLOCK, Clock, utc_iso

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
    "routing_decision",
    "routing_outcome",
)
FLUSH_KINDS = frozenset({"phase_result", "failure", "summary", "cancellation", "cost_ceiling_hit"})


@dataclass(frozen=True)
class Event:
    run_id: str
    seq: int
    kind: str
    phase: str | None = None
    iteration: int | str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))  # det-exempt: dataclass default is a test-time fallback; production stamps ts via the injected Clock at sink-emit time
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


class RendererSink:
    """Asynchronously adapt events to a live renderer callback."""

    def __init__(
        self,
        run_id: str,
        renderer: Callable[[Event], None],
        *,
        max_queue: int = 256,
        close_timeout_seconds: float = 2.0,
    ):
        if max_queue < 1:
            raise ValueError("renderer sink max_queue must be positive")
        if close_timeout_seconds < 0:
            raise ValueError("renderer sink close timeout must be non-negative")
        self.run_id = run_id
        self.dropped_events = 0
        self.render_errors = 0
        self._seq = 0
        self._lock = threading.Lock()
        self._renderer = renderer
        self._close_timeout_seconds = close_timeout_seconds
        self._closed = False
        self._queue: queue.Queue[Event | None] = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._drain, name="revrem-renderer-sink", daemon=True)
        self._thread.start()

    def emit(
        self,
        kind: str,
        *,
        phase: str | None = None,
        iteration: int | str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        with self._lock:
            if self._closed:
                raise ValueError("renderer sink is closed")
            self._seq += 1
            seq = self._seq
        event = make_event(
            run_id=self.run_id,
            seq=seq,
            kind=kind,
            phase=phase,
            iteration=iteration,
            payload=payload or {},
        )
        with self._lock:
            if self._closed:
                self.dropped_events += 1
                return event
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            with self._lock:
                self.dropped_events += 1
        return event

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._queue.put(None, timeout=self._close_timeout_seconds)
        except queue.Full:
            return
        self._thread.join(timeout=self._close_timeout_seconds)

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                try:
                    self._renderer(item)
                except Exception:
                    self.render_errors += 1
            finally:
                self._queue.task_done()


class JsonlSink:
    def __init__(self, run_dir: Path, run_id: str, *, clock: Clock = SYSTEM_CLOCK):
        self.run_dir = run_dir
        self.run_id = run_id
        self.path = artifacts.safe_artifact_path(run_dir, EVENTS_FILENAME)
        self._seq = 0
        self._clock = clock
        self._handle = _open_fresh_artifact(self.path)

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
            ts=utc_iso(self._clock.now()),
        )
        self._handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        if kind in FLUSH_KINDS:
            self._handle.flush()
        return event

    def close(self) -> None:
        self._handle.flush()
        self._handle.close()


def _open_fresh_artifact(path: Path):
    if path.is_symlink():
        raise artifacts.ArtifactPathError(f"artifact path must not be a symlink: {path}")

    flags = os.O_TRUNC | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(path, flags, 0o666)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise artifacts.ArtifactPathError(f"artifact path must not be a symlink: {path}") from exc
        raise

    try:
        return os.fdopen(fd, "a", encoding="utf-8")
    except Exception:
        os.close(fd)
        raise


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
        ts=ts or datetime.now(UTC).isoformat().replace("+00:00", "Z"),  # det-exempt: fallback when no ts is supplied; production sinks pass an injected-Clock ts
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
            if not isinstance(payload, dict):
                raise ValueError("event line must be a JSON object")
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


def first_run_id(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if isinstance(payload, dict) and isinstance(payload.get("run_id"), str):
                return str(payload["run_id"])
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        break
    return None


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
        detail = compact_detail(event)
        label_part = f"|{label}" if label else ""
        detail_part = f": {detail}" if detail else ""
        lines.append(f"{event.seq:04d}|{phase}{label_part}|{event.kind}{detail_part}")
    return "\n".join(lines) + ("\n" if lines else "")


def compact_detail(event: Event) -> str:
    if event.kind == "routing_decision":
        effective_route = event.payload.get("effective_route")
        policy_decision = event.payload.get("policy_decision")
        if isinstance(effective_route, dict) and isinstance(policy_decision, dict):
            decision = policy_decision.get("decision")
            route_tier = effective_route.get("route_tier")
            harness = effective_route.get("harness")
            if all(isinstance(value, str) for value in (decision, route_tier, harness)):
                return f"{decision} {route_tier} via {harness}"
    if event.kind == "routing_outcome":
        checks_passed = event.payload.get("checks_passed")
        exit_code = event.payload.get("exit_code")
        if isinstance(checks_passed, bool) and isinstance(exit_code, int):
            status = "checks_passed" if checks_passed else "checks_failed"
            return f"{status} exit={exit_code}"
    for key in ("status", "reason", "message", "summary", "path"):
        value = event.payload.get(key)
        if isinstance(value, str):
            return value
    return ""
