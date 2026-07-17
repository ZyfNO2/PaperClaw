"""Durable service projection built on the v0.13 SQLite run state machine."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Iterator, Mapping

from .core import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    DurableRun,
    DurableRunNotFoundError,
    InvalidTransitionError,
    LeaseConflictError,
    SQLiteDurableRunStore,
)


@dataclass(frozen=True)
class DurableRunEvent:
    run_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    terminal: bool
    timestamp: float


class SQLiteDurableServiceStore:
    """Adds durable event replay and mutable service metadata to run storage.

    ``SQLiteDurableRunStore`` remains the owner of state transitions, leases,
    idempotency and action receipts. This class deliberately uses the same
    SQLite file so a run and its public event stream share one durable source.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self._clock = clock
        self.run_store = SQLiteDurableRunStore(self.path, clock=clock)
        self._initialize_service_schema()

    def create_run(self, *args: Any, **kwargs: Any):
        return self.run_store.create_run(*args, **kwargs)

    def get_run(self, run_id: str) -> DurableRun:
        return self.run_store.get_run(run_id)

    def transition(self, *args: Any, **kwargs: Any) -> DurableRun:
        return self.run_store.transition(*args, **kwargs)

    def claim_next(self, *args: Any, **kwargs: Any) -> DurableRun | None:
        return self.run_store.claim_next(*args, **kwargs)

    def renew_lease(self, *args: Any, **kwargs: Any) -> float:
        return self.run_store.renew_lease(*args, **kwargs)

    def release_lease(self, *args: Any, **kwargs: Any) -> bool:
        return self.run_store.release_lease(*args, **kwargs)

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        terminal: bool = False,
    ) -> DurableRunEvent:
        normalized_type = event_type.strip()
        if not normalized_type:
            raise ValueError("event_type must not be empty")
        now = self._clock()
        encoded = json.dumps(
            _sanitize(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        with self._transaction() as connection:
            exists = connection.execute(
                "SELECT 1 FROM durable_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(f"unknown durable run: {run_id}")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                "FROM durable_run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            sequence = int(row["next_sequence"])
            connection.execute(
                """
                INSERT INTO durable_run_events (
                    run_id, sequence, event_type, payload_json, terminal, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    sequence,
                    normalized_type[:160],
                    encoded,
                    1 if terminal else 0,
                    now,
                ),
            )
        return DurableRunEvent(
            run_id=run_id,
            sequence=sequence,
            event_type=normalized_type[:160],
            payload=json.loads(encoded),
            terminal=terminal,
            timestamp=now,
        )

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1_000,
    ) -> tuple[DurableRunEvent, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be in [1, 10000]")
        self.get_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT run_id, sequence, event_type, payload_json, terminal, timestamp
                FROM durable_run_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (run_id, after_sequence, limit),
            ).fetchall()
        return tuple(
            DurableRunEvent(
                run_id=row["run_id"],
                sequence=int(row["sequence"]),
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                terminal=bool(row["terminal"]),
                timestamp=float(row["timestamp"]),
            )
            for row in rows
        )

    def last_event_sequence(self, run_id: str) -> int:
        self.get_run(run_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence "
                "FROM durable_run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return int(row["sequence"])

    def merge_metadata(
        self,
        run_id: str,
        patch: Mapping[str, Any],
    ) -> DurableRun:
        sanitized_patch = _sanitize(patch)
        if not isinstance(sanitized_patch, dict):
            raise ValueError("metadata patch must be an object")
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM durable_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown durable run: {run_id}")
            metadata = json.loads(row["metadata_json"])
            metadata.update(sanitized_patch)
            connection.execute(
                "UPDATE durable_runs SET metadata_json = ?, updated_at = ? "
                "WHERE run_id = ?",
                (
                    json.dumps(
                        metadata,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    now,
                    run_id,
                ),
            )
        return self.get_run(run_id)

    def finalize_run(
        self,
        run_id: str,
        *,
        worker_id: str,
        requested_state: str,
        stop_reason: str,
        metadata_patch: Mapping[str, Any],
        event_type: str = "service.run.finalized",
        event_payload: Mapping[str, Any] | None = None,
    ) -> tuple[DurableRun, DurableRunEvent | None]:
        """Atomically persist terminal metadata, state, lease release and event.

        The worker lease is checked inside the same ``BEGIN IMMEDIATE``
        transaction. A stale worker therefore cannot overwrite a run reclaimed
        by another worker. Cancellation wins over a concurrently produced
        runtime result; a run timeout is classified as ``failed`` while an
        explicit user cancellation is classified as ``stopped``.
        """

        worker = worker_id.strip()
        if not worker:
            raise ValueError("worker_id must not be empty")
        requested = requested_state.strip()
        if requested not in TERMINAL_STATES:
            raise ValueError("requested_state must be terminal")
        reason = stop_reason.strip()
        if not reason:
            raise ValueError("stop_reason must not be empty")
        normalized_event_type = event_type.strip()[:160]
        if not normalized_event_type:
            raise ValueError("event_type must not be empty")
        patch = _sanitize(metadata_patch)
        payload = _sanitize(event_payload or {})
        if not isinstance(patch, dict) or not isinstance(payload, dict):
            raise ValueError("metadata and event payload must be objects")

        now = self._clock()
        stored_event: DurableRunEvent | None = None
        already_terminal = False
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT state, version, metadata_json FROM durable_runs "
                "WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise DurableRunNotFoundError(f"unknown durable run: {run_id}")
            current_state = str(row["state"])
            if current_state in TERMINAL_STATES:
                already_terminal = True
            else:
                lease = connection.execute(
                    "SELECT worker_id, expires_at FROM durable_worker_leases "
                    "WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if (
                    lease is None
                    or lease["worker_id"] != worker
                    or float(lease["expires_at"]) <= now
                ):
                    raise LeaseConflictError(
                        "worker does not own a live lease for finalization"
                    )

                metadata = json.loads(row["metadata_json"])
                final_state = requested
                final_reason = reason
                if current_state == "cancelling":
                    persisted_reason = metadata.get("stop_reason")
                    if isinstance(persisted_reason, str) and persisted_reason.strip():
                        final_reason = persisted_reason.strip()
                    final_state = (
                        "failed" if final_reason == "run_timeout" else "stopped"
                    )
                if final_state not in ALLOWED_TRANSITIONS.get(
                    current_state, frozenset()
                ):
                    raise InvalidTransitionError(
                        f"transition not allowed: {current_state} -> {final_state}"
                    )

                metadata.update(patch)
                metadata["stop_reason"] = final_reason
                if final_reason == "run_timeout":
                    timeout_error = metadata.get("error")
                    if not isinstance(timeout_error, dict) or (
                        timeout_error.get("code") != "run_timeout"
                    ):
                        metadata["error"] = {
                            "code": "run_timeout",
                            "message": "run exceeded whole-run timeout",
                        }

                version = int(row["version"])
                next_version = version + 1
                connection.execute(
                    "UPDATE durable_runs SET state = ?, version = ?, "
                    "updated_at = ?, terminal_reason = ?, metadata_json = ? "
                    "WHERE run_id = ?",
                    (
                        final_state,
                        next_version,
                        now,
                        final_reason,
                        json.dumps(
                            metadata,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                        run_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO durable_run_transitions (
                        run_id, from_state, to_state, version, reason, actor,
                        timestamp, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}')
                    """,
                    (
                        run_id,
                        current_state,
                        final_state,
                        next_version,
                        final_reason,
                        worker,
                        now,
                    ),
                )

                event_data = dict(payload)
                event_data["status"] = final_state
                event_data["stop_reason"] = final_reason
                encoded = json.dumps(
                    event_data,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                sequence_row = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                    "FROM durable_run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                sequence = int(sequence_row["next_sequence"])
                connection.execute(
                    """
                    INSERT INTO durable_run_events (
                        run_id, sequence, event_type, payload_json, terminal,
                        timestamp
                    ) VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (run_id, sequence, normalized_event_type, encoded, now),
                )
                connection.execute(
                    "DELETE FROM durable_worker_leases WHERE run_id = ?",
                    (run_id,),
                )
                stored_event = DurableRunEvent(
                    run_id=run_id,
                    sequence=sequence,
                    event_type=normalized_event_type,
                    payload=json.loads(encoded),
                    terminal=True,
                    timestamp=now,
                )

        run = self.get_run(run_id)
        return run, None if already_terminal else stored_event

    def queued_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM durable_runs WHERE state = 'queued'"
            ).fetchone()
            return int(row["count"])

    def _initialize_service_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_run_events (
                    run_id TEXT NOT NULL REFERENCES durable_runs(run_id),
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    terminal INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS durable_run_events_lookup_idx
                ON durable_run_events(run_id, sequence);
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:20_000]
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:200]:
            key = str(raw_key)[:120]
            normalized = key.casefold().replace("-", "_")
            if any(
                marker in normalized
                for marker in (
                    "api_key",
                    "authorization",
                    "password",
                    "secret",
                    "credential",
                )
            ):
                continue
            output[key] = _sanitize(raw_value, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(item, depth=depth + 1) for item in list(value)[:200]]
    return str(value)[:20_000]
