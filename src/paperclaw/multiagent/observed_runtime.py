"""Observed MultiAgent composition for durable Team Run -> Trace/Eval closure.

This module composes around the existing Message Bus and Coordinator rather than
introducing another scheduler. Bus events are projected into the existing
SessionEvent repository so ``SQLiteTraceReader`` and ``paperclaw-observe`` can
inspect the exact same run that ``paperclaw-team-run`` executed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
from typing import Any, Mapping
from uuid import uuid4

from paperclaw.context.repository import SQLiteRepository
from paperclaw.eval.aggregate import (
    ModelCallObservation,
    PricingTable,
    UsageCollector,
)
from paperclaw.message_bus import MessageBusStore, MessageDraft
from paperclaw.multiagent.bus_runtime import (
    TEAM_DLQ_TOPIC,
    TEAM_EVENT_TOPIC,
    TEAM_REQUEST_TOPIC,
)
from paperclaw.multiagent.coordinator import Coordinator
from paperclaw.multiagent.events import emit_team_event
from paperclaw.multiagent.worker import Worker

_TRACE_SCHEMA_VERSION = 1
_SUCCESS_STOP_REASONS = frozenset({"completed", "all_tasks_completed"})


def team_run_id(request_id: str) -> str:
    """Return the stable trace run id for one idempotent team request."""

    normalized = request_id.strip()
    if not normalized:
        raise ValueError("request_id must not be empty")
    return f"team-{normalized}"


def team_conversation_id(request_id: str) -> str:
    normalized = request_id.strip()
    if not normalized:
        raise ValueError("request_id must not be empty")
    return f"team-conversation-{normalized}"


class SQLiteTeamTraceBridge:
    """MessageBus decorator that writes durable, queryable team traces.

    The delegate remains authoritative for delivery, cursor, and acknowledgement
    semantics. This bridge only observes successful publishes and projects them
    into the existing Context Repository schema consumed by ``SQLiteTraceReader``.
    Event ids are derived from durable Message Bus message ids, so an exact
    idempotent publish can be replayed without duplicating a trace event.
    """

    def __init__(self, delegate: MessageBusStore, database: str | Path) -> None:
        self._delegate = delegate
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._repository = SQLiteRepository(self.database)
        self._lock = threading.RLock()
        self._started: set[str] = set()

    def publish(self, draft: MessageDraft):
        result = self._delegate.publish(draft)
        self._observe_message(result.message)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def close(self) -> None:
        self._repository.close()

    def record_model_call(
        self,
        request_id: str,
        observation: ModelCallObservation,
    ) -> None:
        """Append one normalized model span from a metered provider call."""

        call_id = uuid4().hex
        common = {
            "schema_version": _TRACE_SCHEMA_VERSION,
            "request_id": request_id,
            "provider": observation.provider,
            "model": observation.model,
        }
        self._append(
            request_id,
            "model.started",
            common,
            event_id=f"model-started-{call_id}",
        )
        terminal_type = "model.completed" if observation.succeeded else "model.failed"
        payload = {
            **common,
            "status": "completed" if observation.succeeded else "failed",
            "duration_ms": observation.duration_ms,
            "input_tokens": observation.input_tokens,
            "output_tokens": observation.output_tokens,
            "total_tokens": observation.total_tokens,
            "retry_count": observation.retry_count,
            "estimated_cost_usd": observation.estimated_cost_usd,
        }
        if not observation.succeeded:
            payload["error_code"] = "provider_call_failed"
        self._append(
            request_id,
            terminal_type,
            payload,
            event_id=f"model-terminal-{call_id}",
        )

    def _observe_message(self, message: Any) -> None:
        encoded = message.to_dict()
        payload = encoded.get("payload", {})
        if not isinstance(payload, dict):
            return
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return

        message_id = str(encoded.get("message_id", ""))
        occurred_at = _timestamp(float(encoded.get("created_at", 0.0)))

        if message.topic == TEAM_REQUEST_TOPIC:
            self._ensure_run(
                request_id,
                metadata={
                    "request_message_id": message_id,
                    "task_count": _count(payload.get("tasks")),
                },
            )
            self._append(
                request_id,
                "team.request.published",
                {
                    "schema_version": _TRACE_SCHEMA_VERSION,
                    "request_id": request_id,
                    "request_message_id": message_id,
                    "task_count": _count(payload.get("tasks")),
                },
                event_id=f"bus-{message_id}",
                created_at=occurred_at,
            )
            return

        if message.topic == TEAM_DLQ_TOPIC:
            self._append(
                request_id,
                "run.failed",
                {
                    "schema_version": _TRACE_SCHEMA_VERSION,
                    "request_id": request_id,
                    "status": "failed",
                    "error_code": str(payload.get("failure_category") or "dead_lettered"),
                    "attempt": payload.get("attempt"),
                    "max_attempts": payload.get("max_attempts"),
                    "source_event_type": payload.get("event_type"),
                },
                event_id=f"bus-{message_id}",
                created_at=occurred_at,
            )
            return

        if message.topic != TEAM_EVENT_TOPIC:
            return

        source_type = str(payload.get("event_type") or "team.event")
        nested = payload.get("event")
        body = dict(nested) if isinstance(nested, Mapping) else dict(payload)
        body.update(
            {
                "schema_version": _TRACE_SCHEMA_VERSION,
                "request_id": request_id,
                "source_event_type": source_type,
                "message_id": message_id,
            }
        )

        if source_type == "team.run.terminal":
            stop_reason = str(body.get("stop_reason") or "unknown")
            succeeded = stop_reason in _SUCCESS_STOP_REASONS
            body["status"] = "completed" if succeeded else "failed"
            if not succeeded:
                body.setdefault("error_code", stop_reason)
            trace_type = "run.completed" if succeeded else "run.failed"
        elif source_type == "team.run.metrics":
            trace_type = "run.metrics"
        else:
            trace_type = source_type

        self._append(
            request_id,
            trace_type,
            body,
            event_id=f"bus-{message_id}",
            created_at=occurred_at,
        )

    def _ensure_run(
        self,
        request_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        run_id = team_run_id(request_id)
        with self._lock:
            if run_id in self._started:
                return
            conversation_id = team_conversation_id(request_id)
            self._repository.create_conversation(
                conversation_id,
                metadata={"request_id": request_id, "runtime": "multiagent"},
            )
            try:
                self._repository.start_run(
                    run_id,
                    conversation_id,
                    "multiagent-runtime",
                    "coordinator",
                    metadata={"request_id": request_id, **dict(metadata or {})},
                )
            except sqlite3.IntegrityError:
                # The same idempotent request may be retried after process restart.
                # Existing Run and SessionEvent rows remain authoritative.
                pass
            self._started.add(run_id)
            self._append_locked(
                request_id,
                "run.started",
                {
                    "schema_version": _TRACE_SCHEMA_VERSION,
                    "request_id": request_id,
                    "status": "started",
                    **dict(metadata or {}),
                },
                event_id=f"run-started-{request_id}",
            )

    def _append(
        self,
        request_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        event_id: str,
        created_at: str | None = None,
    ) -> None:
        with self._lock:
            self._ensure_run(request_id)
            self._append_locked(
                request_id,
                event_type,
                payload,
                event_id=event_id,
                created_at=created_at,
            )

    def _append_locked(
        self,
        request_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        event_id: str,
        created_at: str | None = None,
    ) -> None:
        normalized = _json_safe(payload)
        normalized.setdefault("schema_version", _TRACE_SCHEMA_VERSION)
        self._repository.append_event_with_auto_sequence(
            event_id=event_id,
            conversation_id=team_conversation_id(request_id),
            run_id=team_run_id(request_id),
            event_type=event_type,
            payload=normalized,
            created_at=created_at,
        )
        if event_type in {"run.completed", "run.failed", "run.stopped", "run.cancelled"}:
            self._repository.end_run(
                team_run_id(request_id),
                stop_reason=str(normalized.get("error_code") or normalized.get("status") or event_type),
            )


class TraceUsageCollector(UsageCollector):
    """UsageCollector that durably emits model spans as calls complete."""

    def __init__(
        self,
        pricing: PricingTable,
        bridge: SQLiteTeamTraceBridge,
        request_id: str,
    ) -> None:
        super().__init__(pricing)
        self._bridge = bridge
        self._request_id = request_id

    def record(self, **kwargs: Any) -> ModelCallObservation:
        observation = super().record(**kwargs)
        self._bridge.record_model_call(self._request_id, observation)
        return observation


class ObservedWorker(Worker):
    """Worker that forwards bounded Tool lifecycle facts into the team event stream."""

    def _on_runtime_event(
        self,
        event: str,
        payload: dict[str, Any],
        task_id: str,
        counters: Any,
    ) -> None:
        super()._on_runtime_event(event, payload, task_id, counters)
        if event == "tool_call":
            emit_team_event(
                self._team_state,
                "tool.started",
                self.agent_id,
                task_id,
                tool=payload.get("tool"),
                step=payload.get("step"),
            )
        elif event == "tool_result":
            succeeded = bool(payload.get("ok"))
            emit_team_event(
                self._team_state,
                "tool.completed" if succeeded else "tool.failed",
                self.agent_id,
                task_id,
                tool=payload.get("tool"),
                step=payload.get("step"),
                status="completed" if succeeded else "failed",
                error_code=payload.get("error_code"),
            )


class ObservedCoordinator(Coordinator):
    """Existing Coordinator with an observed Worker factory."""

    def _make_worker(self, agent_id: str) -> Worker:
        return ObservedWorker(
            agent_id=agent_id,
            model=self._model_factory(agent_id),
            guard=self._guard,
            lease_manager=self._lease_manager,
            team_state=self._team_state,
            enable_verification_gate=self.enable_verification_gate,
        )


def _timestamp(value: float) -> str:
    if value <= 0:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _count(value: Any) -> int:
    return len(value) if isinstance(value, (list, tuple)) else 0


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


__all__ = [
    "ObservedCoordinator",
    "ObservedWorker",
    "SQLiteTeamTraceBridge",
    "TraceUsageCollector",
    "team_conversation_id",
    "team_run_id",
]
