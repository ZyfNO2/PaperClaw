"""PostgreSQL resilient choreography and ordered terminal Outbox store."""

from __future__ import annotations

from contextlib import contextmanager
import json
import re
import time
from typing import Any, Callable, Sequence

from paperclaw.message_bus import MessageDraft
from paperclaw.multiagent.resilient_runtime import (
    FailureDisposition,
    OutboxRecord,
    ResilientAttemptState,
    TerminalSnapshot,
    _encode_json,
    _outbox_id,
)


class PostgreSQLResilientChoreographyStore:
    """Multi-host choreography state backed by PostgreSQL transactions."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "paperclaw",
        clock: Callable[[], float] = time.time,
        connect: Callable[..., Any] | None = None,
    ) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", schema) is None:
            raise ValueError("schema must be a safe PostgreSQL identifier")
        if connect is None:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL backend requires the 'distributed' optional dependency"
                ) from exc
            connect = psycopg.connect
        self.dsn = dsn
        self.schema = schema
        self._clock = clock
        self._connect_callable = connect
        self._initialize()

    def begin_attempt(self, consumer_id: str, message_id: str) -> ResilientAttemptState:
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                f"""
                INSERT INTO {self._table('team_attempts')}(
                    consumer_id, message_id, attempts, terminal,
                    last_failure_category, last_failure_disposition, updated_at
                ) VALUES (%s, %s, 1, FALSE, NULL, NULL, %s)
                ON CONFLICT(consumer_id, message_id) DO UPDATE SET
                    attempts = CASE
                        WHEN {self._table('team_attempts')}.terminal
                            THEN {self._table('team_attempts')}.attempts
                        ELSE {self._table('team_attempts')}.attempts + 1
                    END,
                    updated_at = EXCLUDED.updated_at
                RETURNING consumer_id, message_id, attempts, terminal,
                          last_failure_category, last_failure_disposition
                """,
                (consumer_id, message_id, now),
            ).fetchone()
            return self._attempt_from_row(row)

    def mark_failure(
        self,
        consumer_id: str,
        message_id: str,
        category: str,
        disposition: FailureDisposition,
    ) -> ResilientAttemptState:
        with self._transaction() as connection:
            row = connection.execute(
                f"""
                UPDATE {self._table('team_attempts')}
                SET last_failure_category = %s,
                    last_failure_disposition = %s,
                    updated_at = %s
                WHERE consumer_id = %s AND message_id = %s
                RETURNING consumer_id, message_id, attempts, terminal,
                          last_failure_category, last_failure_disposition
                """,
                (
                    category,
                    disposition.value,
                    self._clock(),
                    consumer_id,
                    message_id,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("PostgreSQL choreography state row is missing")
            return self._attempt_from_row(row)

    def commit_terminal(
        self,
        consumer_id: str,
        message_id: str,
        snapshot: TerminalSnapshot,
        drafts: Sequence[MessageDraft],
    ) -> None:
        now = self._clock()
        with self._transaction() as connection:
            updated = connection.execute(
                f"""
                UPDATE {self._table('team_attempts')}
                SET terminal = TRUE, updated_at = %s
                WHERE consumer_id = %s AND message_id = %s
                """,
                (now, consumer_id, message_id),
            ).rowcount
            if updated != 1:
                raise RuntimeError("PostgreSQL choreography state row is missing")
            connection.execute(
                f"""
                INSERT INTO {self._table('team_terminals')}(
                    consumer_id, message_id, snapshot_json, created_at
                ) VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT(consumer_id, message_id) DO UPDATE SET
                    snapshot_json = EXCLUDED.snapshot_json
                """,
                (consumer_id, message_id, snapshot.to_json(), now),
            )
            for ordinal, draft in enumerate(drafts):
                outbox_id = _outbox_id(
                    consumer_id,
                    message_id,
                    draft.idempotency_key,
                    ordinal,
                )
                connection.execute(
                    f"""
                    INSERT INTO {self._table('team_outbox')}(
                        outbox_id, consumer_id, message_id, ordinal, topic,
                        sender_id, recipient_id, idempotency_key, payload_json,
                        headers_json, delivered, created_at, delivered_at,
                        claimed_by, claimed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, FALSE, %s, NULL, NULL, NULL
                    )
                    ON CONFLICT(outbox_id) DO NOTHING
                    """,
                    (
                        outbox_id,
                        consumer_id,
                        message_id,
                        ordinal,
                        draft.topic,
                        draft.sender_id,
                        draft.recipient_id,
                        draft.idempotency_key,
                        _encode_json(draft.payload),
                        _encode_json(draft.headers),
                        now,
                    ),
                )

    def get_attempt(
        self,
        consumer_id: str,
        message_id: str,
    ) -> ResilientAttemptState | None:
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT consumer_id, message_id, attempts, terminal,
                       last_failure_category, last_failure_disposition
                FROM {self._table('team_attempts')}
                WHERE consumer_id = %s AND message_id = %s
                """,
                (consumer_id, message_id),
            ).fetchone()
            return self._attempt_from_row(row) if row is not None else None

    def get_terminal(
        self,
        consumer_id: str,
        message_id: str,
    ) -> TerminalSnapshot | None:
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT snapshot_json
                FROM {self._table('team_terminals')}
                WHERE consumer_id = %s AND message_id = %s
                """,
                (consumer_id, message_id),
            ).fetchone()
            if row is None:
                return None
            value = row[0]
            encoded = value if isinstance(value, str) else json.dumps(value)
            return TerminalSnapshot.from_json(encoded)

    def pending_outbox(
        self,
        consumer_id: str,
        message_id: str,
    ) -> tuple[OutboxRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT outbox_id, topic, sender_id, recipient_id,
                       idempotency_key, payload_json, headers_json, delivered
                FROM {self._table('team_outbox')}
                WHERE consumer_id = %s AND message_id = %s AND delivered = FALSE
                ORDER BY ordinal ASC, outbox_id ASC
                """,
                (consumer_id, message_id),
            ).fetchall()
            return tuple(self._outbox_from_row(row) for row in rows)

    def claim_pending_outbox(
        self,
        *,
        worker_id: str,
        limit: int = 100,
        stale_after_seconds: float = 30.0,
    ) -> tuple[OutboxRecord, ...]:
        """Claim cross-run Outbox rows safely across multiple processes."""

        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be in [1, 1000]")
        cutoff = self._clock() - stale_after_seconds
        with self._transaction() as connection:
            rows = connection.execute(
                f"""
                WITH candidates AS (
                    SELECT outbox_id
                    FROM {self._table('team_outbox')}
                    WHERE delivered = FALSE
                      AND (claimed_at IS NULL OR claimed_at < %s)
                    ORDER BY created_at ASC, ordinal ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE {self._table('team_outbox')} AS outbox
                SET claimed_by = %s, claimed_at = %s
                FROM candidates
                WHERE outbox.outbox_id = candidates.outbox_id
                RETURNING outbox.outbox_id, outbox.topic, outbox.sender_id,
                          outbox.recipient_id, outbox.idempotency_key,
                          outbox.payload_json, outbox.headers_json,
                          outbox.delivered
                """,
                (cutoff, limit, worker_id, self._clock()),
            ).fetchall()
            return tuple(self._outbox_from_row(row) for row in rows)

    def mark_outbox_delivered(self, outbox_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                f"""
                UPDATE {self._table('team_outbox')}
                SET delivered = TRUE, delivered_at = %s,
                    claimed_by = NULL, claimed_at = NULL
                WHERE outbox_id = %s
                """,
                (self._clock(), outbox_id),
            )

    def all_outbox_delivered(self, consumer_id: str, message_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM {self._table('team_outbox')}
                WHERE consumer_id = %s AND message_id = %s AND delivered = FALSE
                """,
                (consumer_id, message_id),
            ).fetchone()
            return int(row[0]) == 0

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table('team_attempts')} (
                    consumer_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL CHECK(attempts >= 0),
                    terminal BOOLEAN NOT NULL,
                    last_failure_category TEXT,
                    last_failure_disposition TEXT,
                    updated_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY(consumer_id, message_id)
                )
                """
            )
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table('team_terminals')} (
                    consumer_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    snapshot_json JSONB NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY(consumer_id, message_id),
                    FOREIGN KEY(consumer_id, message_id)
                        REFERENCES {self._table('team_attempts')}(consumer_id, message_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table('team_outbox')} (
                    outbox_id TEXT PRIMARY KEY,
                    consumer_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                    topic TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    recipient_id TEXT,
                    idempotency_key TEXT NOT NULL,
                    payload_json JSONB NOT NULL,
                    headers_json JSONB NOT NULL,
                    delivered BOOLEAN NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    delivered_at DOUBLE PRECISION,
                    claimed_by TEXT,
                    claimed_at DOUBLE PRECISION,
                    UNIQUE(consumer_id, message_id, idempotency_key),
                    FOREIGN KEY(consumer_id, message_id)
                        REFERENCES {self._table('team_attempts')}(consumer_id, message_id)
                        ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                f"""
                CREATE INDEX IF NOT EXISTS team_outbox_pending_idx
                ON {self._table('team_outbox')}(delivered, created_at, ordinal)
                """
            )

    def _table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    @contextmanager
    def _connection(self):
        connection = self._connect_callable(self.dsn)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as connection:
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _attempt_from_row(row: Any) -> ResilientAttemptState:
        disposition = row[5]
        return ResilientAttemptState(
            consumer_id=str(row[0]),
            message_id=str(row[1]),
            attempts=int(row[2]),
            terminal=bool(row[3]),
            last_failure_category=str(row[4]) if row[4] is not None else None,
            last_failure_disposition=(
                FailureDisposition(str(disposition)) if disposition is not None else None
            ),
        )

    @staticmethod
    def _outbox_from_row(row: Any) -> OutboxRecord:
        payload = row[5]
        headers = row[6]
        return OutboxRecord(
            outbox_id=str(row[0]),
            topic=str(row[1]),
            sender_id=str(row[2]),
            recipient_id=str(row[3]) if row[3] is not None else None,
            idempotency_key=str(row[4]),
            payload=(json.loads(payload) if isinstance(payload, str) else dict(payload)),
            headers=(json.loads(headers) if isinstance(headers, str) else dict(headers)),
            delivered=bool(row[7]),
        )


__all__ = ["PostgreSQLResilientChoreographyStore"]
