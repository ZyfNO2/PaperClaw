"""Explicitly ordered terminal Outbox persistence.

v0.33 terminal metrics must precede the canonical terminal event. Hash-derived
Outbox ids are idempotency identities, not ordering keys. This store persists a
separate ordinal in the same transaction as terminal state and Outbox rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence
import time

from paperclaw.message_bus import MessageDraft
from paperclaw.multiagent.resilient_runtime import (
    OutboxRecord,
    SQLiteResilientChoreographyStore,
    TerminalSnapshot,
    _encode_json,
    _outbox_id,
)


class SQLiteOrderedResilientChoreographyStore(SQLiteResilientChoreographyStore):
    """SQLite resilience store with durable per-terminal publication ordering."""

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(database, clock=clock)
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resilient_team_outbox_order (
                    outbox_id TEXT PRIMARY KEY,
                    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                    FOREIGN KEY(outbox_id)
                        REFERENCES resilient_team_outbox(outbox_id)
                        ON DELETE CASCADE
                )
                """
            )

    def commit_terminal(
        self,
        consumer_id: str,
        message_id: str,
        snapshot: TerminalSnapshot,
        drafts: Sequence[MessageDraft],
    ) -> None:
        now = self._clock()
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE resilient_team_attempts
                SET terminal = 1, updated_at = ?
                WHERE consumer_id = ? AND message_id = ?
                """,
                (now, consumer_id, message_id),
            )
            connection.execute(
                """
                INSERT INTO resilient_team_terminals(
                    consumer_id, message_id, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(consumer_id, message_id) DO UPDATE SET
                    snapshot_json = excluded.snapshot_json
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
                    """
                    INSERT INTO resilient_team_outbox(
                        outbox_id, consumer_id, message_id, topic, sender_id,
                        recipient_id, idempotency_key, payload_json, headers_json,
                        delivered, created_at, delivered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL)
                    ON CONFLICT(outbox_id) DO NOTHING
                    """,
                    (
                        outbox_id,
                        consumer_id,
                        message_id,
                        draft.topic,
                        draft.sender_id,
                        draft.recipient_id,
                        draft.idempotency_key,
                        _encode_json(draft.payload),
                        _encode_json(draft.headers),
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO resilient_team_outbox_order(outbox_id, ordinal)
                    VALUES (?, ?)
                    ON CONFLICT(outbox_id) DO UPDATE SET ordinal = excluded.ordinal
                    """,
                    (outbox_id, ordinal),
                )

    def pending_outbox(
        self,
        consumer_id: str,
        message_id: str,
    ) -> tuple[OutboxRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT outbox.*
                FROM resilient_team_outbox AS outbox
                JOIN resilient_team_outbox_order AS ordering
                  ON ordering.outbox_id = outbox.outbox_id
                WHERE outbox.consumer_id = ?
                  AND outbox.message_id = ?
                  AND outbox.delivered = 0
                ORDER BY ordering.ordinal ASC, outbox.outbox_id ASC
                """,
                (consumer_id, message_id),
            ).fetchall()
            return tuple(self._outbox_from_row(row) for row in rows)


__all__ = ["SQLiteOrderedResilientChoreographyStore"]
