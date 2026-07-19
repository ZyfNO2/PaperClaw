"""Durable pull/cursor Agent Message Bus reference store."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Protocol
from uuid import uuid4

from .contracts import (
    ConsumerCursor,
    MessageBusAckError,
    MessageBusCapacityError,
    MessageBusConflictError,
    MessageBusEvent,
    MessageDraft,
    MessageEnvelope,
    PublishResult,
    canonical_draft_bytes,
    canonical_json_bytes,
    thaw_json,
)


class MessageBusStore(Protocol):
    def publish(self, draft: MessageDraft) -> PublishResult: ...

    def pull(
        self,
        consumer_id: str,
        topic: str,
        *,
        limit: int = 50,
    ) -> tuple[MessageEnvelope, ...]: ...

    def ack(self, consumer_id: str, topic: str, sequence: int) -> ConsumerCursor: ...

    def get_cursor(self, consumer_id: str, topic: str) -> ConsumerCursor: ...

    def list_events(
        self,
        *,
        topic: str | None = None,
        after_event_id: int = 0,
        limit: int = 500,
    ) -> tuple[MessageBusEvent, ...]: ...


class _TopicAtCapacity(RuntimeError):
    def __init__(self, retained_count: int) -> None:
        super().__init__("topic at capacity")
        self.retained_count = retained_count


class SQLiteMessageBusStore:
    """Same-filesystem durable bus with transactional topic sequencing.

    SQLite is the local reference backend. `BEGIN IMMEDIATE` serializes writers
    so independent processes sharing one DB file cannot allocate the same topic
    sequence. This is not a multi-host broker claim.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        max_messages_per_topic: int = 10_000,
        max_payload_bytes: int = 1_048_576,
        max_headers_bytes: int = 65_536,
        max_draft_bytes: int = 1_310_720,
        clock: Callable[[], float] = time.time,
        busy_timeout_ms: int = 10_000,
    ) -> None:
        for name, value in (
            ("max_messages_per_topic", max_messages_per_topic),
            ("max_payload_bytes", max_payload_bytes),
            ("max_headers_bytes", max_headers_bytes),
            ("max_draft_bytes", max_draft_bytes),
            ("busy_timeout_ms", busy_timeout_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if max_draft_bytes < max_payload_bytes:
            raise ValueError("max_draft_bytes must not be below max_payload_bytes")
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.max_messages_per_topic = max_messages_per_topic
        self.max_payload_bytes = max_payload_bytes
        self.max_headers_bytes = max_headers_bytes
        self.max_draft_bytes = max_draft_bytes
        self._clock = clock
        self._busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def publish(self, draft: MessageDraft) -> PublishResult:
        encoded_draft = canonical_draft_bytes(draft)
        self._validate_draft_size(draft, encoded_draft)
        digest = hashlib.sha256(encoded_draft).hexdigest()
        now = self._clock()
        try:
            with self._transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT * FROM agent_bus_messages
                    WHERE topic = ? AND sender_id = ? AND idempotency_key = ?
                    """,
                    (draft.topic, draft.sender_id, draft.idempotency_key),
                ).fetchone()
                if existing is not None:
                    if existing["request_digest"] != digest:
                        raise MessageBusConflictError(
                            "idempotency key is already bound to a different message"
                        )
                    envelope = self._message_from_row(existing)
                    self._append_event(
                        connection,
                        "message.publish_deduplicated",
                        draft.topic,
                        sequence=envelope.sequence,
                        message_id=envelope.message_id,
                        metadata={"sender_id": draft.sender_id},
                        created_at=now,
                    )
                    return PublishResult(envelope, False)

                count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) AS count FROM agent_bus_messages
                        WHERE topic = ?
                        """,
                        (draft.topic,),
                    ).fetchone()["count"]
                )
                if count >= self.max_messages_per_topic:
                    raise _TopicAtCapacity(count)

                state = connection.execute(
                    "SELECT last_sequence FROM agent_bus_topics WHERE topic = ?",
                    (draft.topic,),
                ).fetchone()
                sequence = (
                    int(state["last_sequence"]) + 1 if state is not None else 1
                )
                connection.execute(
                    """
                    INSERT INTO agent_bus_topics(topic, last_sequence, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(topic) DO UPDATE SET
                        last_sequence = excluded.last_sequence,
                        updated_at = excluded.updated_at
                    """,
                    (draft.topic, sequence, now),
                )
                message_id = f"msg-{uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO agent_bus_messages(
                        message_id, topic, sequence, sender_id, recipient_id,
                        idempotency_key, request_digest, payload_json,
                        headers_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        draft.topic,
                        sequence,
                        draft.sender_id,
                        draft.recipient_id,
                        draft.idempotency_key,
                        digest,
                        _json_dump(draft.payload),
                        _json_dump(draft.headers),
                        now,
                    ),
                )
                self._append_event(
                    connection,
                    "message.published",
                    draft.topic,
                    sequence=sequence,
                    message_id=message_id,
                    metadata={
                        "sender_id": draft.sender_id,
                        "recipient_id": draft.recipient_id,
                    },
                    created_at=now,
                )
                row = connection.execute(
                    "SELECT * FROM agent_bus_messages WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                assert row is not None
                return PublishResult(self._message_from_row(row), True)
        except _TopicAtCapacity as exc:
            # The publish transaction has rolled back and released its writer
            # lock. Record the rejection in a distinct transaction so the audit
            # survives the business exception returned to the caller.
            self._record_capacity_rejection(
                draft.topic,
                retained_count=exc.retained_count,
                created_at=now,
            )
            raise MessageBusCapacityError(
                "topic retained-message capacity is exhausted"
            ) from exc

    def pull(
        self,
        consumer_id: str,
        topic: str,
        *,
        limit: int = 50,
    ) -> tuple[MessageEnvelope, ...]:
        _bounded_id(consumer_id, "consumer_id")
        _bounded_topic(topic)
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be in [1, 1000]")
        with self._connection() as connection:
            cursor = self._cursor_locked(connection, consumer_id, topic)
            rows = connection.execute(
                """
                SELECT * FROM agent_bus_messages
                WHERE topic = ? AND sequence > ?
                  AND (recipient_id IS NULL OR recipient_id = ?)
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (topic, cursor.ack_sequence, consumer_id, limit),
            ).fetchall()
            return tuple(self._message_from_row(row) for row in rows)

    def ack(self, consumer_id: str, topic: str, sequence: int) -> ConsumerCursor:
        _bounded_id(consumer_id, "consumer_id")
        _bounded_topic(topic)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        now = self._clock()
        with self._transaction() as connection:
            current = self._cursor_locked(connection, consumer_id, topic)
            if sequence <= current.ack_sequence:
                return current
            eligible = connection.execute(
                """
                SELECT 1 FROM agent_bus_messages
                WHERE topic = ? AND sequence = ?
                  AND (recipient_id IS NULL OR recipient_id = ?)
                """,
                (topic, sequence, consumer_id),
            ).fetchone()
            if eligible is None:
                raise MessageBusAckError(
                    "ack sequence is not an eligible message for this consumer"
                )
            connection.execute(
                """
                INSERT INTO agent_bus_cursors(
                    consumer_id, topic, ack_sequence, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(consumer_id, topic) DO UPDATE SET
                    ack_sequence = excluded.ack_sequence,
                    updated_at = excluded.updated_at
                WHERE excluded.ack_sequence > agent_bus_cursors.ack_sequence
                """,
                (consumer_id, topic, sequence, now),
            )
            self._append_event(
                connection,
                "message.cursor_acknowledged",
                topic,
                sequence=sequence,
                consumer_id=consumer_id,
                metadata={},
                created_at=now,
            )
            return self._cursor_locked(connection, consumer_id, topic)

    def get_cursor(self, consumer_id: str, topic: str) -> ConsumerCursor:
        _bounded_id(consumer_id, "consumer_id")
        _bounded_topic(topic)
        with self._connection() as connection:
            return self._cursor_locked(connection, consumer_id, topic)

    def list_events(
        self,
        *,
        topic: str | None = None,
        after_event_id: int = 0,
        limit: int = 500,
    ) -> tuple[MessageBusEvent, ...]:
        if topic is not None:
            _bounded_topic(topic)
        if after_event_id < 0 or not 1 <= limit <= 5_000:
            raise ValueError("invalid event query bounds")
        query = "SELECT * FROM agent_bus_events WHERE event_id > ?"
        params: list[object] = [after_event_id]
        if topic is not None:
            query += " AND topic = ?"
            params.append(topic)
        query += " ORDER BY event_id ASC LIMIT ?"
        params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
            return tuple(self._event_from_row(row) for row in rows)

    def count_topic(self, topic: str) -> int:
        _bounded_topic(topic)
        with self._connection() as connection:
            return int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM agent_bus_messages
                    WHERE topic = ?
                    """,
                    (topic,),
                ).fetchone()["count"]
            )

    def latest_sequence(self, topic: str) -> int:
        _bounded_topic(topic)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT last_sequence FROM agent_bus_topics WHERE topic = ?",
                (topic,),
            ).fetchone()
            return int(row["last_sequence"]) if row is not None else 0

    def _validate_draft_size(
        self,
        draft: MessageDraft,
        encoded_draft: bytes,
    ) -> None:
        payload_size = len(canonical_json_bytes(draft.payload))
        headers_size = len(canonical_json_bytes(draft.headers))
        if payload_size > self.max_payload_bytes:
            raise MessageBusCapacityError(
                f"message payload exceeds {self.max_payload_bytes} bytes"
            )
        if headers_size > self.max_headers_bytes:
            raise MessageBusCapacityError(
                f"message headers exceed {self.max_headers_bytes} bytes"
            )
        if len(encoded_draft) > self.max_draft_bytes:
            raise MessageBusCapacityError(
                f"message draft exceeds {self.max_draft_bytes} bytes"
            )

    def _record_capacity_rejection(
        self,
        topic: str,
        *,
        retained_count: int,
        created_at: float,
    ) -> None:
        with self._transaction() as connection:
            self._append_event(
                connection,
                "message.publish_rejected_capacity",
                topic,
                metadata={"retained_count": retained_count},
                created_at=created_at,
            )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_bus_topics (
                    topic TEXT PRIMARY KEY,
                    last_sequence INTEGER NOT NULL CHECK(last_sequence >= 0),
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_bus_messages (
                    message_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    sender_id TEXT NOT NULL,
                    recipient_id TEXT,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    headers_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(topic, sequence),
                    UNIQUE(topic, sender_id, idempotency_key)
                );

                CREATE INDEX IF NOT EXISTS idx_agent_bus_messages_topic_sequence
                ON agent_bus_messages(topic, sequence);

                CREATE INDEX IF NOT EXISTS idx_agent_bus_messages_recipient
                ON agent_bus_messages(topic, recipient_id, sequence);

                CREATE TABLE IF NOT EXISTS agent_bus_cursors (
                    consumer_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    ack_sequence INTEGER NOT NULL CHECK(ack_sequence >= 0),
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(consumer_id, topic)
                );

                CREATE TABLE IF NOT EXISTS agent_bus_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    sequence INTEGER,
                    message_id TEXT,
                    consumer_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(
            self.database,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _cursor_locked(
        self,
        connection: sqlite3.Connection,
        consumer_id: str,
        topic: str,
    ) -> ConsumerCursor:
        row = connection.execute(
            """
            SELECT ack_sequence, updated_at FROM agent_bus_cursors
            WHERE consumer_id = ? AND topic = ?
            """,
            (consumer_id, topic),
        ).fetchone()
        if row is None:
            return ConsumerCursor(consumer_id, topic, 0, None)
        return ConsumerCursor(
            consumer_id,
            topic,
            int(row["ack_sequence"]),
            float(row["updated_at"]),
        )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        event_type: str,
        topic: str,
        *,
        sequence: int | None = None,
        message_id: str | None = None,
        consumer_id: str | None = None,
        metadata: dict[str, object],
        created_at: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO agent_bus_events(
                event_type, topic, sequence, message_id, consumer_id,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                topic,
                sequence,
                message_id,
                consumer_id,
                _json_dump(metadata),
                created_at,
            ),
        )

    def _message_from_row(self, row: sqlite3.Row) -> MessageEnvelope:
        return MessageEnvelope(
            message_id=row["message_id"],
            topic=row["topic"],
            sequence=int(row["sequence"]),
            sender_id=row["sender_id"],
            recipient_id=row["recipient_id"],
            idempotency_key=row["idempotency_key"],
            payload=_json_object(row["payload_json"]),
            headers=_json_object(row["headers_json"]),
            created_at=float(row["created_at"]),
        )

    def _event_from_row(self, row: sqlite3.Row) -> MessageBusEvent:
        return MessageBusEvent(
            event_id=int(row["event_id"]),
            event_type=row["event_type"],
            topic=row["topic"],
            sequence=(
                int(row["sequence"]) if row["sequence"] is not None else None
            ),
            message_id=row["message_id"],
            consumer_id=row["consumer_id"],
            metadata=_json_object(row["metadata_json"]),
            created_at=float(row["created_at"]),
        )


def _json_dump(value: object) -> str:
    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_object(value: str) -> dict[str, object]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("persisted message JSON is not an object")
    return decoded


def _bounded_id(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError(f"{name} must be a bounded non-empty string")
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
    if any(char not in allowed for char in value):
        raise ValueError(f"{name} contains unsupported characters")
    return value


def _bounded_topic(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("topic must be a bounded non-empty string")
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/-"
    if any(char not in allowed for char in value):
        raise ValueError("topic contains unsupported characters")
    return value


__all__ = ["MessageBusStore", "SQLiteMessageBusStore"]
