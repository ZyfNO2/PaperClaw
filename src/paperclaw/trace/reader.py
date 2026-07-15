"""Read-side projection from durable SessionEvent records to TraceEvent v1."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
import json
from pathlib import Path
import sqlite3
from typing import Any, Protocol
from urllib.parse import quote

from paperclaw.context.contracts import SessionEvent
from paperclaw.context.repository import Repository

from .contracts import TraceEvent, validate_trace
from .redaction import TraceRedactor


class TraceReadError(RuntimeError):
    """Raised when a durable trace cannot be read safely."""


class TraceReader(Protocol):
    """Stable read boundary consumed by exporters and later plugins."""

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]: ...

    def iter_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> Iterator[TraceEvent]: ...


_COMPONENT_PREFIXES = {
    "run": "harness",
    "model": "model",
    "tool": "tool",
    "permission": "tool",
    "verification": "verification",
    "reflection": "reflection",
    "node": "runtime",
    "flow": "runtime",
    "context": "context",
    "checkpoint": "context",
}


def _validate_request(run_id: str, since_sequence: int) -> str:
    normalized = run_id.strip()
    if not normalized:
        raise ValueError("run_id must not be empty")
    if since_sequence < 0:
        raise ValueError("since_sequence must be non-negative")
    return normalized


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _duration_ms(payload: dict[str, Any]) -> int | None:
    for key in ("duration_ms", "latency_ms"):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return int(round(value))
    return None


def _derive_component(event_type: str, payload: dict[str, Any]) -> str:
    explicit = _optional_text(payload.get("component"))
    if explicit:
        return explicit
    prefix = event_type.split(".", 1)[0].lower()
    return _COMPONENT_PREFIXES.get(prefix, "runtime")


def _derive_status(event_type: str, payload: dict[str, Any]) -> str | None:
    explicit = _optional_text(payload.get("status"))
    if explicit:
        return explicit
    suffix = event_type.rsplit(".", 1)[-1].lower()
    if suffix in {
        "started",
        "completed",
        "failed",
        "stopped",
        "cancelled",
        "denied",
        "blocked",
    }:
        return suffix
    return None


def project_session_event(
    event: SessionEvent,
    *,
    redactor: TraceRedactor | None = None,
) -> TraceEvent:
    """Project one durable SessionEvent without mutating the source payload."""

    sanitizer = redactor or TraceRedactor()
    payload = sanitizer.redact_payload(event.payload)
    trace = TraceEvent(
        event_id=event.event_id,
        sequence=event.sequence,
        occurred_at=event.created_at,
        conversation_id=event.conversation_id,
        run_id=event.run_id,
        event_type=event.event_type,
        component=_derive_component(event.event_type, payload),
        status=_derive_status(event.event_type, payload),
        span_id=_optional_text(payload.get("span_id")),
        parent_span_id=_optional_text(payload.get("parent_span_id")),
        duration_ms=_duration_ms(payload),
        provider=_optional_text(payload.get("provider")),
        model=_optional_text(payload.get("model")),
        error_code=_optional_text(payload.get("error_code")),
        payload=payload,
    )
    trace.validate()
    return trace


class RepositoryTraceReader:
    """TraceReader backed by an already-open existing Repository."""

    def __init__(
        self,
        repository: Repository,
        *,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self._repository = repository
        self._redactor = redactor or TraceRedactor()

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]:
        normalized = _validate_request(run_id, since_sequence)
        events = (
            project_session_event(event, redactor=self._redactor)
            for event in self._repository.list_events(
                normalized,
                since_sequence=since_sequence,
            )
        )
        return validate_trace(events, require_terminal=require_terminal)

    def iter_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> Iterator[TraceEvent]:
        yield from self.get_run_trace(
            run_id,
            since_sequence=since_sequence,
            require_terminal=require_terminal,
        )


class SQLiteTraceReader:
    """Read a trace from an existing SQLite database without migration or writes.

    The connection uses ``mode=ro`` and ``PRAGMA query_only``.  This mirrors the
    v0.06.1 Safe Session Picker boundary and is suitable for CLI export and
    future inspector plugins.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self._database = Path(database).expanduser().resolve()
        self._redactor = redactor or TraceRedactor()

    @property
    def database(self) -> Path:
        return self._database

    def get_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> tuple[TraceEvent, ...]:
        normalized = _validate_request(run_id, since_sequence)
        connection = self._connect()
        try:
            run_exists = connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                (normalized,),
            ).fetchone()
            if run_exists is None:
                raise TraceReadError(f"run does not exist: {normalized}")
            rows = connection.execute(
                "SELECT event_id, conversation_id, run_id, sequence, event_type, "
                "payload, created_at FROM session_events "
                "WHERE run_id = ? AND sequence > ? ORDER BY sequence ASC",
                (normalized, since_sequence),
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise TraceReadError(
                f"unable to read trace: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc
        finally:
            connection.close()

        session_events: list[SessionEvent] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload"]))
            except json.JSONDecodeError as exc:
                raise TraceReadError(
                    f"invalid session event payload at sequence {row['sequence']}"
                ) from exc
            if not isinstance(payload, dict):
                raise TraceReadError(
                    f"session event payload must be an object at sequence "
                    f"{row['sequence']}"
                )
            session_events.append(
                SessionEvent(
                    event_id=str(row["event_id"]),
                    conversation_id=str(row["conversation_id"]),
                    run_id=str(row["run_id"]),
                    sequence=int(row["sequence"]),
                    event_type=str(row["event_type"]),
                    payload=payload,
                    created_at=str(row["created_at"]),
                )
            )
        return project_events(
            session_events,
            redactor=self._redactor,
            require_terminal=require_terminal,
        )

    def iter_run_trace(
        self,
        run_id: str,
        *,
        since_sequence: int = 0,
        require_terminal: bool = False,
    ) -> Iterator[TraceEvent]:
        yield from self.get_run_trace(
            run_id,
            since_sequence=since_sequence,
            require_terminal=require_terminal,
        )

    def _connect(self) -> sqlite3.Connection:
        if not self._database.is_file():
            raise TraceReadError(
                f"database path does not exist or is not a file: {self._database}"
            )
        connection: sqlite3.Connection | None = None
        try:
            uri_path = quote(self._database.as_posix(), safe="/:")
            connection = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            present = {str(row[0]) for row in rows}
            missing = sorted({"runs", "session_events"} - present)
            if missing:
                raise TraceReadError(
                    "database is missing required trace tables: "
                    + ", ".join(missing)
                )
            return connection
        except TraceReadError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise TraceReadError(
                f"unable to open trace database: "
                f"{type(exc).__name__}: {str(exc)[:300]}"
            ) from exc


def project_events(
    events: Iterable[SessionEvent],
    *,
    redactor: TraceRedactor | None = None,
    require_terminal: bool = False,
) -> tuple[TraceEvent, ...]:
    """Project an in-memory event collection for tests and import tooling."""

    sanitizer = redactor or TraceRedactor()
    return validate_trace(
        (project_session_event(event, redactor=sanitizer) for event in events),
        require_terminal=require_terminal,
    )
