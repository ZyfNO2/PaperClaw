"""Durable Message Bus entrypoint for Coordinator/Worker/Reviewer choreography.

The existing Coordinator remains the authoritative scheduler. This module adds a
durable request boundary: clients publish a structured team request, a runtime
consumer executes it, mirrors live team events to the Message Bus, publishes a
terminal result/metrics event, and acknowledges only after terminal persistence.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from paperclaw.eval.aggregate import UsageCollector, summarize_observations
from paperclaw.message_bus import MessageBusStore, MessageDraft, MessageEnvelope
from paperclaw.multiagent.contracts import AgentTask, TeamBudget
from paperclaw.multiagent.coordinator import Coordinator, CoordinatorResult

TEAM_REQUEST_TOPIC = "multiagent.team.requests.v1"
TEAM_EVENT_TOPIC = "multiagent.team.events.v1"
TEAM_DLQ_TOPIC = "multiagent.team.dlq.v1"


class CoordinatorFactory(Protocol):
    def __call__(
        self,
        budget: TeamBudget,
        event_handler: Callable[[str, dict[str, Any]], None],
        usage: UsageCollector,
    ) -> Coordinator: ...


@dataclass(frozen=True)
class TeamRunRequest:
    request_id: str
    user_goal: str
    tasks: tuple[AgentTask, ...]
    budget: TeamBudget = field(default_factory=TeamBudget)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be non-empty")
        if not isinstance(self.user_goal, str) or not self.user_goal.strip():
            raise ValueError("user_goal must be non-empty")
        if not self.tasks:
            raise ValueError("tasks must not be empty")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("task ids must be unique")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "request_id": self.request_id,
            "user_goal": self.user_goal,
            "tasks": [task.to_dict() for task in self.tasks],
            "budget": self.budget.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TeamRunRequest":
        if payload.get("schema_version") != "v1":
            raise ValueError("unsupported team request schema_version")
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, Sequence) or isinstance(
            raw_tasks, (str, bytes, bytearray)
        ):
            raise ValueError("tasks must be a list")
        tasks: list[AgentTask] = []
        for row in raw_tasks:
            if not isinstance(row, Mapping):
                raise ValueError("each task must be an object")
            tasks.append(AgentTask(**dict(row)))
        raw_budget = payload.get("budget", {})
        if not isinstance(raw_budget, Mapping):
            raise ValueError("budget must be an object")
        raw_metadata = payload.get("metadata", {})
        if not isinstance(raw_metadata, Mapping):
            raise ValueError("metadata must be an object")
        return cls(
            request_id=str(payload.get("request_id", "")),
            user_goal=str(payload.get("user_goal", "")),
            tasks=tuple(tasks),
            budget=TeamBudget(**dict(raw_budget)),
            metadata=dict(raw_metadata),
        )


@dataclass(frozen=True)
class TeamRunOutcome:
    request_id: str
    request_message_id: str
    attempt: int
    terminal: bool
    acknowledged: bool
    result: CoordinatorResult | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    failure_category: str | None = None
    dead_lettered: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "request_message_id": self.request_message_id,
            "attempt": self.attempt,
            "terminal": self.terminal,
            "acknowledged": self.acknowledged,
            "result": self.result.to_dict() if self.result is not None else None,
            "metrics": dict(self.metrics),
            "failure_category": self.failure_category,
            "dead_lettered": self.dead_lettered,
        }


@dataclass(frozen=True)
class AttemptState:
    consumer_id: str
    message_id: str
    attempts: int
    terminal: bool
    last_failure_category: str | None


class SQLiteChoreographyStateStore:
    """Durable retry/terminal state for one Message Bus consumer."""

    def __init__(self, database: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS team_bus_attempts (
                    consumer_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL CHECK(attempts >= 0),
                    terminal INTEGER NOT NULL CHECK(terminal IN (0, 1)),
                    last_failure_category TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(consumer_id, message_id)
                )
                """
            )

    def begin_attempt(self, consumer_id: str, message_id: str) -> AttemptState:
        now = self._clock()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO team_bus_attempts(
                    consumer_id, message_id, attempts, terminal,
                    last_failure_category, updated_at
                ) VALUES (?, ?, 1, 0, NULL, ?)
                ON CONFLICT(consumer_id, message_id) DO UPDATE SET
                    attempts = CASE
                        WHEN team_bus_attempts.terminal = 1 THEN team_bus_attempts.attempts
                        ELSE team_bus_attempts.attempts + 1
                    END,
                    updated_at = excluded.updated_at
                """,
                (consumer_id, message_id, now),
            )
            return self._read(connection, consumer_id, message_id)

    def mark_failure(
        self,
        consumer_id: str,
        message_id: str,
        failure_category: str,
    ) -> AttemptState:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE team_bus_attempts
                SET last_failure_category = ?, updated_at = ?
                WHERE consumer_id = ? AND message_id = ?
                """,
                (failure_category, self._clock(), consumer_id, message_id),
            )
            return self._read(connection, consumer_id, message_id)

    def mark_terminal(self, consumer_id: str, message_id: str) -> AttemptState:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE team_bus_attempts
                SET terminal = 1, updated_at = ?
                WHERE consumer_id = ? AND message_id = ?
                """,
                (self._clock(), consumer_id, message_id),
            )
            return self._read(connection, consumer_id, message_id)

    def get(self, consumer_id: str, message_id: str) -> AttemptState | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM team_bus_attempts
                WHERE consumer_id = ? AND message_id = ?
                """,
                (consumer_id, message_id),
            ).fetchone()
            return self._from_row(row) if row is not None else None

    def _read(
        self,
        connection: sqlite3.Connection,
        consumer_id: str,
        message_id: str,
    ) -> AttemptState:
        row = connection.execute(
            """
            SELECT * FROM team_bus_attempts
            WHERE consumer_id = ? AND message_id = ?
            """,
            (consumer_id, message_id),
        ).fetchone()
        assert row is not None
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AttemptState:
        return AttemptState(
            consumer_id=str(row["consumer_id"]),
            message_id=str(row["message_id"]),
            attempts=int(row["attempts"]),
            terminal=bool(row["terminal"]),
            last_failure_category=(
                str(row["last_failure_category"])
                if row["last_failure_category"] is not None
                else None
            ),
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

    def _transaction(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return _SQLiteTransaction(connection)


class _SQLiteTransaction:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        self.connection.execute("BEGIN IMMEDIATE")
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
        return False


class BusDrivenTeamRuntime:
    """Consume durable team requests and execute the existing Coordinator."""

    def __init__(
        self,
        bus: MessageBusStore,
        state_store: SQLiteChoreographyStateStore,
        coordinator_factory: CoordinatorFactory,
        *,
        consumer_id: str = "multiagent-runtime",
        max_attempts: int = 3,
        usage_factory: Callable[[], UsageCollector] = UsageCollector,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not consumer_id:
            raise ValueError("consumer_id must be non-empty")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self._bus = bus
        self._state_store = state_store
        self._coordinator_factory = coordinator_factory
        self.consumer_id = consumer_id
        self.max_attempts = max_attempts
        self._usage_factory = usage_factory
        self._clock = clock

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
                if outcome.request_message_id == message.message_id and outcome.terminal:
                    return outcome
        raise RuntimeError("team request did not reach a terminal state within max_cycles")

    def _process(self, message: MessageEnvelope) -> TeamRunOutcome:
        state = self._state_store.begin_attempt(self.consumer_id, message.message_id)
        request_id = _request_id(message)
        if state.terminal:
            self._bus.ack(self.consumer_id, TEAM_REQUEST_TOPIC, message.sequence)
            return TeamRunOutcome(
                request_id=request_id,
                request_message_id=message.message_id,
                attempt=state.attempts,
                terminal=True,
                acknowledged=True,
                failure_category=state.last_failure_category,
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
            result = coordinator.run(request.user_goal, list(request.tasks))
            metrics = self._build_metrics(result, usage, started, state.attempts)
            self._publish_event(
                request.request_id,
                "team.run.metrics",
                metrics,
                idempotency_suffix=f"attempt-{state.attempts}-metrics",
            )
            self._publish_event(
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
            )
            self._state_store.mark_terminal(self.consumer_id, message.message_id)
            self._bus.ack(self.consumer_id, TEAM_REQUEST_TOPIC, message.sequence)
            return TeamRunOutcome(
                request_id=request.request_id,
                request_message_id=message.message_id,
                attempt=state.attempts,
                terminal=True,
                acknowledged=True,
                result=result,
                metrics=metrics,
            )
        except Exception as exc:
            failure_category = _failure_category(exc)
            self._state_store.mark_failure(
                self.consumer_id,
                message.message_id,
                failure_category,
            )
            terminal = state.attempts >= self.max_attempts
            target_topic = TEAM_DLQ_TOPIC if terminal else TEAM_EVENT_TOPIC
            self._bus.publish(
                MessageDraft(
                    topic=target_topic,
                    sender_id=self.consumer_id,
                    idempotency_key=(
                        f"{message.message_id}:attempt-{state.attempts}:"
                        f"{'dlq' if terminal else 'retry'}"
                    ),
                    payload={
                        "schema_version": "v1",
                        "request_id": request_id,
                        "request_message_id": message.message_id,
                        "event_type": "team.run.dead_lettered" if terminal else "team.run.retry_scheduled",
                        "attempt": state.attempts,
                        "max_attempts": self.max_attempts,
                        "failure_category": failure_category,
                    },
                    headers={"schema_version": "v1"},
                )
            )
            if terminal:
                self._state_store.mark_terminal(self.consumer_id, message.message_id)
                self._bus.ack(self.consumer_id, TEAM_REQUEST_TOPIC, message.sequence)
            return TeamRunOutcome(
                request_id=request_id,
                request_message_id=message.message_id,
                attempt=state.attempts,
                terminal=terminal,
                acknowledged=terminal,
                failure_category=failure_category,
                dead_lettered=terminal,
                metrics={
                    "wall_duration_ms": max(0, round((self._clock() - started) * 1000)),
                    **summarize_observations(usage.snapshot()),
                },
            )

    def _publish_event(
        self,
        request_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        idempotency_suffix: str,
    ) -> MessageEnvelope:
        return self._bus.publish(
            MessageDraft(
                topic=TEAM_EVENT_TOPIC,
                sender_id=self.consumer_id,
                idempotency_key=f"{request_id}:{idempotency_suffix}",
                payload={
                    "schema_version": "v1",
                    "request_id": request_id,
                    "event_type": event_type,
                    "event": dict(payload),
                },
                headers={"schema_version": "v1", "message_type": event_type},
            )
        ).message

    def _build_metrics(
        self,
        result: CoordinatorResult,
        usage: UsageCollector,
        started: float,
        attempt: int,
    ) -> dict[str, Any]:
        observations = summarize_observations(usage.snapshot())
        return {
            "schema_version": "v1",
            "attempt": attempt,
            "wall_duration_ms": max(0, round((self._clock() - started) * 1000)),
            "succeeded": _enum_value(result.stop_reason) in {"completed", "all_tasks_completed"},
            "stop_reason": _enum_value(result.stop_reason),
            "worker_count": len(result.task_results),
            "completed_workers": sum(
                _enum_value(item.status) == "completed" for item in result.task_results.values()
            ),
            "step_count": sum(item.step_count for item in result.task_results.values()),
            "model_call_count": sum(
                item.model_call_count for item in result.task_results.values()
            ),
            "tool_call_count": sum(item.tool_call_count for item in result.task_results.values()),
            "review_finding_count": len(result.review_findings),
            **observations,
        }


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _request_id(message: MessageEnvelope) -> str:
    value = message.payload.get("request_id")
    if isinstance(value, str) and value:
        return value
    return message.message_id


def _failure_category(exc: Exception) -> str:
    name = type(exc).__name__.strip() or "Exception"
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in name)
    return normalized.strip("_")[:100] or "execution_error"


__all__ = [
    "AttemptState",
    "BusDrivenTeamRuntime",
    "CoordinatorFactory",
    "SQLiteChoreographyStateStore",
    "TEAM_DLQ_TOPIC",
    "TEAM_EVENT_TOPIC",
    "TEAM_REQUEST_TOPIC",
    "TeamRunOutcome",
    "TeamRunRequest",
]
