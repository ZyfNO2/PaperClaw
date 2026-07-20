"""Resilient Message Bus choreography for PaperClaw MultiAgent runs.

The existing Coordinator remains the scheduling authority. This module adds the
failure boundaries that v0.32 deliberately left explicit:

* terminal state and terminal-event Outbox rows commit in one SQLite transaction;
* restart recovery flushes pending Outbox rows before acknowledging the request;
* exact Message Bus idempotency makes publish-before-mark-delivered recovery safe;
* durable cancellation messages call the existing ``Coordinator.cancel`` path;
* deterministic fault-injection checkpoints exercise crash windows;
* failure disposition distinguishes retryable, permanent, and unknown failures.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from queue import Empty, Queue
import re
import sqlite3
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from paperclaw.eval.aggregate import UsageCollector, summarize_observations
from paperclaw.message_bus import MessageBusStore, MessageDraft, MessageEnvelope
from paperclaw.multiagent.bus_runtime import (
    CoordinatorFactory,
    TEAM_DLQ_TOPIC,
    TEAM_EVENT_TOPIC,
    TEAM_REQUEST_TOPIC,
    TeamRunOutcome,
    TeamRunRequest,
)
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.coordinator import Coordinator, CoordinatorResult

TEAM_CANCEL_TOPIC = "multiagent.team.cancellations.v1"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SUCCESS_STOP_REASONS = frozenset({"completed", "all_tasks_completed"})


class FailureDisposition(str, Enum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class InjectedCrash(RuntimeError):
    """A deterministic process-crash surrogate used by resilience acceptance tests."""


class FaultInjector(Protocol):
    def __call__(self, checkpoint: str, context: Mapping[str, Any]) -> None: ...


class RetryClassifier(Protocol):
    def __call__(self, error: Exception) -> FailureDisposition: ...


@dataclass(frozen=True)
class TeamCancellationRequest:
    cancellation_id: str
    request_id: str
    task_ids: tuple[str, ...] = ()
    reason: str = "operator requested cancellation"

    def __post_init__(self) -> None:
        if _SAFE_ID.fullmatch(self.cancellation_id) is None:
            raise ValueError("cancellation_id must be a safe identifier")
        if _SAFE_ID.fullmatch(self.request_id) is None:
            raise ValueError("request_id must be a safe identifier")
        if not all(isinstance(task_id, str) and task_id for task_id in self.task_ids):
            raise ValueError("task_ids must contain non-empty strings")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task_ids must be unique")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be non-empty")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "cancellation_id": self.cancellation_id,
            "request_id": self.request_id,
            "task_ids": list(self.task_ids),
            "reason": self.reason,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TeamCancellationRequest":
        if payload.get("schema_version") != "v1":
            raise ValueError("unsupported cancellation schema_version")
        raw_task_ids = payload.get("task_ids", ())
        if not isinstance(raw_task_ids, Sequence) or isinstance(
            raw_task_ids, (str, bytes, bytearray)
        ):
            raise ValueError("task_ids must be a list")
        return cls(
            cancellation_id=str(payload.get("cancellation_id", "")),
            request_id=str(payload.get("request_id", "")),
            task_ids=tuple(str(item) for item in raw_task_ids),
            reason=str(payload.get("reason", "")),
        )


@dataclass(frozen=True)
class ResilientAttemptState:
    consumer_id: str
    message_id: str
    attempts: int
    terminal: bool
    last_failure_category: str | None
    last_failure_disposition: FailureDisposition | None


@dataclass(frozen=True)
class OutboxRecord:
    outbox_id: str
    topic: str
    sender_id: str
    recipient_id: str | None
    idempotency_key: str
    payload: Mapping[str, Any]
    headers: Mapping[str, Any]
    delivered: bool

    def to_draft(self) -> MessageDraft:
        return MessageDraft(
            topic=self.topic,
            sender_id=self.sender_id,
            recipient_id=self.recipient_id,
            idempotency_key=self.idempotency_key,
            payload=dict(self.payload),
            headers=dict(self.headers),
        )


@dataclass(frozen=True)
class TerminalSnapshot:
    request_id: str
    request_message_id: str
    request_sequence: int
    attempt: int
    failure_category: str | None
    failure_disposition: FailureDisposition | None
    dead_lettered: bool
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "request_id": self.request_id,
                "request_message_id": self.request_message_id,
                "request_sequence": self.request_sequence,
                "attempt": self.attempt,
                "failure_category": self.failure_category,
                "failure_disposition": (
                    self.failure_disposition.value
                    if self.failure_disposition is not None
                    else None
                ),
                "dead_lettered": self.dead_lettered,
                "metrics": dict(self.metrics),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, encoded: str) -> "TerminalSnapshot":
        payload = json.loads(encoded)
        disposition = payload.get("failure_disposition")
        return cls(
            request_id=str(payload["request_id"]),
            request_message_id=str(payload["request_message_id"]),
            request_sequence=int(payload["request_sequence"]),
            attempt=int(payload["attempt"]),
            failure_category=(
                str(payload["failure_category"])
                if payload.get("failure_category") is not None
                else None
            ),
            failure_disposition=(
                FailureDisposition(str(disposition)) if disposition is not None else None
            ),
            dead_lettered=bool(payload.get("dead_lettered")),
            metrics=dict(payload.get("metrics", {})),
        )


class SQLiteResilientChoreographyStore:
    """Attempt, terminal snapshot, and Outbox state in one SQLite database."""

    def __init__(self, database: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS resilient_team_attempts (
                    consumer_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL CHECK(attempts >= 0),
                    terminal INTEGER NOT NULL CHECK(terminal IN (0, 1)),
                    last_failure_category TEXT,
                    last_failure_disposition TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(consumer_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS resilient_team_terminals (
                    consumer_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(consumer_id, message_id),
                    FOREIGN KEY(consumer_id, message_id)
                        REFERENCES resilient_team_attempts(consumer_id, message_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS resilient_team_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    consumer_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    recipient_id TEXT,
                    idempotency_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    headers_json TEXT NOT NULL,
                    delivered INTEGER NOT NULL CHECK(delivered IN (0, 1)),
                    created_at REAL NOT NULL,
                    delivered_at REAL,
                    UNIQUE(consumer_id, message_id, idempotency_key),
                    FOREIGN KEY(consumer_id, message_id)
                        REFERENCES resilient_team_attempts(consumer_id, message_id)
                        ON DELETE CASCADE
                );
                """
            )

    def begin_attempt(self, consumer_id: str, message_id: str) -> ResilientAttemptState:
        now = self._clock()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO resilient_team_attempts(
                    consumer_id, message_id, attempts, terminal,
                    last_failure_category, last_failure_disposition, updated_at
                ) VALUES (?, ?, 1, 0, NULL, NULL, ?)
                ON CONFLICT(consumer_id, message_id) DO UPDATE SET
                    attempts = CASE
                        WHEN resilient_team_attempts.terminal = 1
                            THEN resilient_team_attempts.attempts
                        ELSE resilient_team_attempts.attempts + 1
                    END,
                    updated_at = excluded.updated_at
                """,
                (consumer_id, message_id, now),
            )
            return self._read_attempt(connection, consumer_id, message_id)

    def mark_failure(
        self,
        consumer_id: str,
        message_id: str,
        category: str,
        disposition: FailureDisposition,
    ) -> ResilientAttemptState:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE resilient_team_attempts
                SET last_failure_category = ?, last_failure_disposition = ?, updated_at = ?
                WHERE consumer_id = ? AND message_id = ?
                """,
                (category, disposition.value, self._clock(), consumer_id, message_id),
            )
            return self._read_attempt(connection, consumer_id, message_id)

    def commit_terminal(
        self,
        consumer_id: str,
        message_id: str,
        snapshot: TerminalSnapshot,
        drafts: Sequence[MessageDraft],
    ) -> None:
        """Atomically mark terminal and persist every terminal publication intent."""

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
            for index, draft in enumerate(drafts):
                outbox_id = _outbox_id(consumer_id, message_id, draft.idempotency_key, index)
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

    def get_attempt(
        self,
        consumer_id: str,
        message_id: str,
    ) -> ResilientAttemptState | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM resilient_team_attempts
                WHERE consumer_id = ? AND message_id = ?
                """,
                (consumer_id, message_id),
            ).fetchone()
            return self._from_attempt_row(row) if row is not None else None

    def get_terminal(
        self,
        consumer_id: str,
        message_id: str,
    ) -> TerminalSnapshot | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT snapshot_json FROM resilient_team_terminals
                WHERE consumer_id = ? AND message_id = ?
                """,
                (consumer_id, message_id),
            ).fetchone()
            return TerminalSnapshot.from_json(str(row[0])) if row is not None else None

    def pending_outbox(
        self,
        consumer_id: str,
        message_id: str,
    ) -> tuple[OutboxRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resilient_team_outbox
                WHERE consumer_id = ? AND message_id = ? AND delivered = 0
                ORDER BY created_at, outbox_id
                """,
                (consumer_id, message_id),
            ).fetchall()
            return tuple(self._outbox_from_row(row) for row in rows)

    def mark_outbox_delivered(self, outbox_id: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE resilient_team_outbox
                SET delivered = 1, delivered_at = ?
                WHERE outbox_id = ?
                """,
                (self._clock(), outbox_id),
            )

    def all_outbox_delivered(self, consumer_id: str, message_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM resilient_team_outbox
                WHERE consumer_id = ? AND message_id = ? AND delivered = 0
                """,
                (consumer_id, message_id),
            ).fetchone()
            return int(row[0]) == 0

    def _read_attempt(
        self,
        connection: sqlite3.Connection,
        consumer_id: str,
        message_id: str,
    ) -> ResilientAttemptState:
        row = connection.execute(
            """
            SELECT * FROM resilient_team_attempts
            WHERE consumer_id = ? AND message_id = ?
            """,
            (consumer_id, message_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("resilient choreography state row is missing")
        return self._from_attempt_row(row)

    @staticmethod
    def _from_attempt_row(row: sqlite3.Row) -> ResilientAttemptState:
        raw_disposition = row["last_failure_disposition"]
        return ResilientAttemptState(
            consumer_id=str(row["consumer_id"]),
            message_id=str(row["message_id"]),
            attempts=int(row["attempts"]),
            terminal=bool(row["terminal"]),
            last_failure_category=(
                str(row["last_failure_category"])
                if row["last_failure_category"] is not None
                else None
            ),
            last_failure_disposition=(
                FailureDisposition(str(raw_disposition))
                if raw_disposition is not None
                else None
            ),
        )

    @staticmethod
    def _outbox_from_row(row: sqlite3.Row) -> OutboxRecord:
        return OutboxRecord(
            outbox_id=str(row["outbox_id"]),
            topic=str(row["topic"]),
            sender_id=str(row["sender_id"]),
            recipient_id=(
                str(row["recipient_id"]) if row["recipient_id"] is not None else None
            ),
            idempotency_key=str(row["idempotency_key"]),
            payload=json.loads(str(row["payload_json"])),
            headers=json.loads(str(row["headers_json"])),
            delivered=bool(row["delivered"]),
        )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
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
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()


class ResilientBusDrivenTeamRuntime:
    """Bus-driven Coordinator runtime with Outbox recovery and cancellation."""

    def __init__(
        self,
        bus: MessageBusStore,
        state_store: SQLiteResilientChoreographyStore,
        coordinator_factory: CoordinatorFactory,
        *,
        consumer_id: str = "multiagent-runtime",
        max_attempts: int = 3,
        usage_factory: Callable[[], UsageCollector] = UsageCollector,
        clock: Callable[[], float] = time.perf_counter,
        fault_injector: FaultInjector | None = None,
        retry_classifier: RetryClassifier | None = None,
        cancellation_poll_seconds: float = 0.02,
    ) -> None:
        if not consumer_id:
            raise ValueError("consumer_id must be non-empty")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if cancellation_poll_seconds <= 0:
            raise ValueError("cancellation_poll_seconds must be positive")
        self._bus = bus
        self._state_store = state_store
        self._coordinator_factory = coordinator_factory
        self.consumer_id = consumer_id
        self.max_attempts = max_attempts
        self._usage_factory = usage_factory
        self._clock = clock
        self._fault_injector = fault_injector
        self._retry_classifier = retry_classifier or default_retry_classifier
        self._cancellation_poll_seconds = cancellation_poll_seconds

    def submit(
        self,
        request: TeamRunRequest,
        *,
        sender_id: str = "team-client",
    ) -> MessageEnvelope:
        return self._bus.publish(
            MessageDraft(
                topic=TEAM_REQUEST_TOPIC,
                sender_id=sender_id,
                recipient_id=self.consumer_id,
                idempotency_key=request.request_id,
                payload=request.to_payload(),
                headers={"schema_version": "v1", "message_type": "team.run.requested"},
            )
        ).message

    def submit_cancellation(
        self,
        cancellation: TeamCancellationRequest,
        *,
        sender_id: str = "team-client",
    ) -> MessageEnvelope:
        return self._bus.publish(
            MessageDraft(
                topic=TEAM_CANCEL_TOPIC,
                sender_id=sender_id,
                recipient_id=_cancel_consumer_id(self.consumer_id, cancellation.request_id),
                idempotency_key=cancellation.cancellation_id,
                payload=cancellation.to_payload(),
                headers={"schema_version": "v1", "message_type": "team.cancel.requested"},
            )
        ).message

    def run_once(self, *, limit: int = 1) -> tuple[TeamRunOutcome, ...]:
        messages = self._bus.pull(self.consumer_id, TEAM_REQUEST_TOPIC, limit=limit)
        return tuple(self._process(message) for message in messages)

    def execute(
        self,
        request: TeamRunRequest,
        *,
        sender_id: str = "team-client",
        max_cycles: int = 10,
    ) -> TeamRunOutcome:
        message = self.submit(request, sender_id=sender_id)
        for _ in range(max_cycles):
            for outcome in self.run_once(limit=50):
                if (
                    outcome.request_message_id == message.message_id
                    and outcome.terminal
                    and outcome.acknowledged
                ):
                    return outcome
        raise RuntimeError("team request did not durably finalize within max_cycles")

    def _process(self, message: MessageEnvelope) -> TeamRunOutcome:
        state = self._state_store.begin_attempt(self.consumer_id, message.message_id)
        request_id = _request_id(message)
        if state.terminal:
            return self._recover_terminal(message)

        self._checkpoint(
            "after_attempt_started",
            {"request_id": request_id, "attempt": state.attempts},
        )
        usage = self._usage_factory()
        started = self._clock()
        event_lock = threading.Lock()
        local_sequence = 0

        def publish_event(event_type: str, envelope: dict[str, Any]) -> None:
            nonlocal local_sequence
            with event_lock:
                local_sequence += 1
                event_id = str(envelope.get("event_id") or f"local-{local_sequence}")
            self._publish_event(
                request_id,
                event_type,
                envelope,
                idempotency_suffix=event_id,
            )

        try:
            request = TeamRunRequest.from_payload(message.payload)
            self._publish_event(
                request.request_id,
                "team.request.accepted",
                {
                    "request_message_id": message.message_id,
                    "attempt": state.attempts,
                    "task_count": len(request.tasks),
                },
                idempotency_suffix=f"attempt-{state.attempts}-accepted",
            )
            coordinator = self._coordinator_factory(request.budget, publish_event, usage)
            result = self._run_with_cancellation(coordinator, request)
            self._checkpoint(
                "after_coordinator_completed",
                {"request_id": request.request_id, "attempt": state.attempts},
            )
            metrics = self._build_metrics(result, usage, started, state.attempts)
            snapshot = TerminalSnapshot(
                request_id=request.request_id,
                request_message_id=message.message_id,
                request_sequence=message.sequence,
                attempt=state.attempts,
                failure_category=None,
                failure_disposition=None,
                dead_lettered=False,
                metrics=metrics,
            )
            drafts = (
                self._event_draft(
                    request.request_id,
                    "team.run.metrics",
                    metrics,
                    idempotency_suffix=f"attempt-{state.attempts}-metrics",
                ),
                self._event_draft(
                    request.request_id,
                    "team.run.terminal",
                    {
                        "request_message_id": message.message_id,
                        "attempt": state.attempts,
                        "stop_reason": _enum_value(result.stop_reason),
                        "summary": result.summary[:500],
                        "task_statuses": {
                            task_id: _enum_value(worker_result.status)
                            for task_id, worker_result in result.task_results.items()
                        },
                        "review_finding_count": len(result.review_findings),
                    },
                    idempotency_suffix=f"attempt-{state.attempts}-terminal",
                ),
            )
            self._state_store.commit_terminal(
                self.consumer_id,
                message.message_id,
                snapshot,
                drafts,
            )
            self._checkpoint(
                "after_terminal_committed",
                {"request_id": request.request_id, "attempt": state.attempts},
            )
            return self._recover_terminal(
                message,
                result=result,
                metrics=metrics,
            )
        except InjectedCrash:
            raise
        except Exception as exc:
            return self._handle_execution_failure(message, state, usage, started, exc)

    def _handle_execution_failure(
        self,
        message: MessageEnvelope,
        state: ResilientAttemptState,
        usage: UsageCollector,
        started: float,
        error: Exception,
    ) -> TeamRunOutcome:
        request_id = _request_id(message)
        category = _failure_category(error)
        disposition = self._retry_classifier(error)
        self._state_store.mark_failure(
            self.consumer_id,
            message.message_id,
            category,
            disposition,
        )
        terminal = (
            disposition == FailureDisposition.PERMANENT
            or state.attempts >= self.max_attempts
        )
        metrics = {
            "wall_duration_ms": max(0, round((self._clock() - started) * 1000)),
            **summarize_observations(usage.snapshot()),
        }
        if not terminal:
            self._bus.publish(
                MessageDraft(
                    topic=TEAM_EVENT_TOPIC,
                    sender_id=self.consumer_id,
                    idempotency_key=_bounded_idempotency_key(
                        message.message_id,
                        f"attempt-{state.attempts}-retry",
                    ),
                    payload={
                        "schema_version": "v1",
                        "request_id": request_id,
                        "request_message_id": message.message_id,
                        "event_type": "team.run.retry_scheduled",
                        "attempt": state.attempts,
                        "max_attempts": self.max_attempts,
                        "failure_category": category,
                        "failure_disposition": disposition.value,
                    },
                    headers={"schema_version": "v1"},
                )
            )
            return TeamRunOutcome(
                request_id=request_id,
                request_message_id=message.message_id,
                attempt=state.attempts,
                terminal=False,
                acknowledged=False,
                failure_category=category,
                metrics={**metrics, "failure_disposition": disposition.value},
            )

        snapshot = TerminalSnapshot(
            request_id=request_id,
            request_message_id=message.message_id,
            request_sequence=message.sequence,
            attempt=state.attempts,
            failure_category=category,
            failure_disposition=disposition,
            dead_lettered=True,
            metrics={**metrics, "failure_disposition": disposition.value},
        )
        dlq = MessageDraft(
            topic=TEAM_DLQ_TOPIC,
            sender_id=self.consumer_id,
            idempotency_key=_bounded_idempotency_key(
                message.message_id,
                f"attempt-{state.attempts}-dlq",
            ),
            payload={
                "schema_version": "v1",
                "request_id": request_id,
                "request_message_id": message.message_id,
                "event_type": "team.run.dead_lettered",
                "attempt": state.attempts,
                "max_attempts": self.max_attempts,
                "failure_category": category,
                "failure_disposition": disposition.value,
            },
            headers={"schema_version": "v1"},
        )
        self._state_store.commit_terminal(
            self.consumer_id,
            message.message_id,
            snapshot,
            (dlq,),
        )
        self._checkpoint(
            "after_terminal_committed",
            {"request_id": request_id, "attempt": state.attempts, "dlq": True},
        )
        return self._recover_terminal(message, metrics=snapshot.metrics)

    def _recover_terminal(
        self,
        message: MessageEnvelope,
        *,
        result: CoordinatorResult | None = None,
        metrics: Mapping[str, Any] | None = None,
    ) -> TeamRunOutcome:
        snapshot = self._state_store.get_terminal(self.consumer_id, message.message_id)
        if snapshot is None:
            # Compatibility with a manually terminalized state in low-level tests.
            self._bus.ack(self.consumer_id, TEAM_REQUEST_TOPIC, message.sequence)
            state = self._state_store.get_attempt(self.consumer_id, message.message_id)
            return TeamRunOutcome(
                request_id=_request_id(message),
                request_message_id=message.message_id,
                attempt=state.attempts if state is not None else 0,
                terminal=True,
                acknowledged=True,
            )

        try:
            for record in self._state_store.pending_outbox(
                self.consumer_id,
                message.message_id,
            ):
                self._bus.publish(record.to_draft())
                self._checkpoint(
                    "after_outbox_published",
                    {
                        "request_id": snapshot.request_id,
                        "outbox_id": record.outbox_id,
                    },
                )
                self._state_store.mark_outbox_delivered(record.outbox_id)
            if not self._state_store.all_outbox_delivered(
                self.consumer_id,
                message.message_id,
            ):
                raise RuntimeError("terminal Outbox still has pending rows")
            self._checkpoint(
                "before_request_ack",
                {"request_id": snapshot.request_id, "attempt": snapshot.attempt},
            )
            self._bus.ack(self.consumer_id, TEAM_REQUEST_TOPIC, message.sequence)
        except InjectedCrash:
            raise
        except Exception:
            return TeamRunOutcome(
                request_id=snapshot.request_id,
                request_message_id=message.message_id,
                attempt=snapshot.attempt,
                terminal=True,
                acknowledged=False,
                result=result,
                metrics=dict(metrics or snapshot.metrics),
                failure_category="outbox_delivery_failed",
                dead_lettered=snapshot.dead_lettered,
            )

        return TeamRunOutcome(
            request_id=snapshot.request_id,
            request_message_id=message.message_id,
            attempt=snapshot.attempt,
            terminal=True,
            acknowledged=True,
            result=result,
            metrics=dict(metrics or snapshot.metrics),
            failure_category=snapshot.failure_category,
            dead_lettered=snapshot.dead_lettered,
        )

    def _run_with_cancellation(
        self,
        coordinator: Coordinator,
        request: TeamRunRequest,
    ) -> CoordinatorResult:
        result_queue: Queue[tuple[str, Any]] = Queue(maxsize=1)
        tasks = list(request.tasks)

        def target() -> None:
            try:
                result_queue.put(("result", coordinator.run(request.user_goal, tasks)))
            except BaseException as exc:
                result_queue.put(("error", exc))

        thread = threading.Thread(
            target=target,
            name=f"paperclaw-team-{request.request_id}",
            daemon=True,
        )
        thread.start()
        cancel_consumer = _cancel_consumer_id(self.consumer_id, request.request_id)
        known_tasks = {task.task_id for task in tasks}
        while thread.is_alive():
            cancellations = self._bus.pull(cancel_consumer, TEAM_CANCEL_TOPIC, limit=50)
            ready = not isinstance(coordinator, Coordinator) or hasattr(coordinator, "_cancel_lock")
            if ready:
                for message in cancellations:
                    cancellation = TeamCancellationRequest.from_payload(message.payload)
                    selected = cancellation.task_ids or tuple(sorted(known_tasks))
                    accepted = [task_id for task_id in selected if task_id in known_tasks]
                    rejected = [task_id for task_id in selected if task_id not in known_tasks]
                    for task_id in accepted:
                        coordinator.cancel(task_id, tasks)
                    self._publish_event(
                        request.request_id,
                        "team.cancel.accepted" if accepted else "team.cancel.rejected",
                        {
                            "cancellation_id": cancellation.cancellation_id,
                            "accepted_task_ids": accepted,
                            "rejected_task_ids": rejected,
                            "reason": cancellation.reason,
                        },
                        idempotency_suffix=f"cancel-{cancellation.cancellation_id}",
                    )
                    self._bus.ack(cancel_consumer, TEAM_CANCEL_TOPIC, message.sequence)
            thread.join(timeout=self._cancellation_poll_seconds)

        try:
            kind, value = result_queue.get_nowait()
        except Empty as exc:
            raise RuntimeError("Coordinator thread exited without a result") from exc
        if kind == "error":
            if isinstance(value, BaseException):
                raise value
            raise RuntimeError("Coordinator failed with an invalid error payload")
        if not isinstance(value, CoordinatorResult):
            raise RuntimeError("Coordinator returned an invalid result")
        return value

    def _publish_event(
        self,
        request_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        idempotency_suffix: str,
    ) -> MessageEnvelope:
        return self._bus.publish(
            self._event_draft(
                request_id,
                event_type,
                payload,
                idempotency_suffix=idempotency_suffix,
            )
        ).message

    def _event_draft(
        self,
        request_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        idempotency_suffix: str,
    ) -> MessageDraft:
        return MessageDraft(
            topic=TEAM_EVENT_TOPIC,
            sender_id=self.consumer_id,
            idempotency_key=_bounded_idempotency_key(request_id, idempotency_suffix),
            payload={
                "schema_version": "v1",
                "request_id": request_id,
                "event_type": event_type,
                "event": dict(payload),
            },
            headers={"schema_version": "v1", "message_type": event_type},
        )

    def _build_metrics(
        self,
        result: CoordinatorResult,
        usage: UsageCollector,
        started: float,
        attempt: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "attempt": attempt,
            "wall_duration_ms": max(0, round((self._clock() - started) * 1000)),
            "succeeded": _enum_value(result.stop_reason) in _SUCCESS_STOP_REASONS,
            "stop_reason": _enum_value(result.stop_reason),
            "worker_count": len(result.task_results),
            "completed_workers": sum(
                _enum_value(item.status) == "completed"
                for item in result.task_results.values()
            ),
            "step_count": sum(item.step_count for item in result.task_results.values()),
            "model_call_count": sum(
                item.model_call_count for item in result.task_results.values()
            ),
            "tool_call_count": sum(
                item.tool_call_count for item in result.task_results.values()
            ),
            "review_finding_count": len(result.review_findings),
            **summarize_observations(usage.snapshot()),
        }

    def _checkpoint(self, checkpoint: str, context: Mapping[str, Any]) -> None:
        if self._fault_injector is not None:
            self._fault_injector(checkpoint, dict(context))


def default_retry_classifier(error: Exception) -> FailureDisposition:
    if isinstance(error, (ValueError, TypeError, PermissionError, FileNotFoundError)):
        return FailureDisposition.PERMANENT
    if isinstance(error, (TimeoutError, ConnectionError, InterruptedError)):
        return FailureDisposition.RETRYABLE
    if isinstance(error, OSError):
        return FailureDisposition.RETRYABLE
    return FailureDisposition.UNKNOWN


def _cancel_consumer_id(consumer_id: str, request_id: str) -> str:
    digest = sha256(request_id.encode("utf-8")).hexdigest()[:16]
    return f"{consumer_id}.cancel.{digest}"


def _outbox_id(
    consumer_id: str,
    message_id: str,
    idempotency_key: str,
    index: int,
) -> str:
    raw = f"{consumer_id}\0{message_id}\0{idempotency_key}\0{index}"
    return sha256(raw.encode("utf-8")).hexdigest()


def _encode_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _bounded_idempotency_key(prefix: str, suffix: str) -> str:
    candidate = f"{prefix}:{suffix}"
    if len(candidate) <= 200 and re.fullmatch(r"[A-Za-z0-9_.:-]+", candidate):
        return candidate
    digest = sha256(candidate.encode("utf-8")).hexdigest()
    safe_prefix = re.sub(r"[^A-Za-z0-9_.:-]", "_", prefix)[:120] or "message"
    return f"{safe_prefix}:{digest}"


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _request_id(message: MessageEnvelope) -> str:
    value = message.payload.get("request_id")
    return value if isinstance(value, str) and value else message.message_id


def _failure_category(error: Exception) -> str:
    name = type(error).__name__.strip() or "Exception"
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in name)
    return normalized.strip("_")[:100] or "execution_error"


__all__ = [
    "FailureDisposition",
    "FaultInjector",
    "InjectedCrash",
    "OutboxRecord",
    "ResilientAttemptState",
    "ResilientBusDrivenTeamRuntime",
    "RetryClassifier",
    "SQLiteResilientChoreographyStore",
    "TEAM_CANCEL_TOPIC",
    "TeamCancellationRequest",
    "TerminalSnapshot",
    "default_retry_classifier",
]
