"""Thread-backed application service over the synchronous QueryEngine."""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Condition, RLock
import time
from typing import Any, Callable
from uuid import uuid4

from paperclaw.harness import QueryEngine

from .contracts import (
    ACTIVE_SERVICE_STATUSES,
    TERMINAL_SERVICE_STATUSES,
    ConcurrencyLimitError,
    IdempotencyConflictError,
    PublicRunEvent,
    PublicRunView,
    RunNotCancellableError,
    RunNotFoundError,
    ServiceRunRequest,
    ServiceShuttingDownError,
    SubmitOutcome,
    sanitize_public,
)
from .plugins import ServicePluginRegistry

EngineFactory = Callable[
    [ServiceRunRequest, Callable[[str, dict], None]], QueryEngine
]


@dataclass
class _RunRecord:
    service_run_id: str
    request: ServiceRunRequest
    created_at: float
    updated_at: float
    status: str = "accepted"
    runtime_run_id: str | None = None
    stop_reason: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    output: str | None = None
    error: dict[str, Any] | None = None
    events: deque[PublicRunEvent] = field(default_factory=deque)
    next_sequence: int = 1
    terminal_event_seen: bool = False
    cancel_requested: bool = False
    engine: QueryEngine | None = None
    future: Future[None] | None = None
    condition: Condition = field(default_factory=lambda: Condition(RLock()))


class RunApplicationService:
    """Own service-level concurrency, idempotency and public event projection."""

    def __init__(
        self,
        engine_factory: EngineFactory,
        *,
        max_active_runs: int = 4,
        event_capacity: int = 512,
        plugins: ServicePluginRegistry | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_active_runs < 1:
            raise ValueError("max_active_runs must be positive")
        if event_capacity < 8:
            raise ValueError("event_capacity must be at least 8")
        self._engine_factory = engine_factory
        self._max_active_runs = max_active_runs
        self._event_capacity = event_capacity
        self._plugins = plugins or ServicePluginRegistry()
        self._clock = clock
        self._executor = ThreadPoolExecutor(
            max_workers=max_active_runs, thread_name_prefix="paperclaw-service"
        )
        self._runs: dict[str, _RunRecord] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._lock = RLock()
        self._shutting_down = False

    def submit(
        self,
        request: ServiceRunRequest,
        *,
        idempotency_key: str | None = None,
    ) -> SubmitOutcome:
        key = _normalize_idempotency_key(idempotency_key)
        digest = request.digest()
        now = self._clock()

        with self._lock:
            if self._shutting_down:
                raise ServiceShuttingDownError("service is shutting down")
            if key and key in self._idempotency:
                existing_digest, run_id = self._idempotency[key]
                if existing_digest != digest:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for another request"
                    )
                return SubmitOutcome(self._view(self._runs[run_id]), created=False)
            active = sum(
                record.status in ACTIVE_SERVICE_STATUSES
                for record in self._runs.values()
            )
            if active >= self._max_active_runs:
                raise ConcurrencyLimitError("global active-run limit reached")
            service_run_id = f"svc-{uuid4().hex[:16]}"
            record = _RunRecord(
                service_run_id=service_run_id,
                request=request,
                created_at=now,
                updated_at=now,
                events=deque(maxlen=self._event_capacity),
            )
            self._runs[service_run_id] = record
            if key:
                self._idempotency[key] = (digest, service_run_id)
            with record.condition:
                self._append_event_locked(
                    record,
                    "service.run.accepted",
                    {
                        "conversation_id": request.conversation_id,
                        "client_id": request.client_id,
                    },
                    terminal=False,
                )
            record.future = self._executor.submit(self._execute, record)

        view = self._view(record)
        self._plugins.run_created(view)
        return SubmitOutcome(view, created=True)

    def get_run(self, service_run_id: str) -> PublicRunView:
        return self._view(self._require(service_run_id))

    def list_events(
        self, service_run_id: str, *, after_sequence: int = 0
    ) -> tuple[PublicRunEvent, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        record = self._require(service_run_id)
        with record.condition:
            return tuple(
                event for event in record.events if event.sequence > after_sequence
            )

    def wait_for_events(
        self,
        service_run_id: str,
        *,
        after_sequence: int = 0,
        timeout: float = 10.0,
    ) -> tuple[tuple[PublicRunEvent, ...], bool]:
        if timeout < 0:
            raise ValueError("timeout must not be negative")
        record = self._require(service_run_id)
        with record.condition:
            events = tuple(
                event for event in record.events if event.sequence > after_sequence
            )
            if not events and record.status not in TERMINAL_SERVICE_STATUSES:
                record.condition.wait(timeout)
                events = tuple(
                    event
                    for event in record.events
                    if event.sequence > after_sequence
                )
            return events, record.status in TERMINAL_SERVICE_STATUSES

    def cancel(self, service_run_id: str, *, reason: str = "user_requested") -> PublicRunView:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("cancel reason must not be empty")
        record = self._require(service_run_id)
        engine: QueryEngine | None
        runtime_run_id: str | None
        with record.condition:
            if record.status in TERMINAL_SERVICE_STATUSES:
                raise RunNotCancellableError("run is already terminal")
            record.cancel_requested = True
            record.status = "cancelling"
            record.stop_reason = normalized_reason
            record.updated_at = self._clock()
            engine = record.engine
            runtime_run_id = record.runtime_run_id
            self._append_event_locked(
                record,
                "service.run.cancel_requested",
                {"reason": normalized_reason},
                terminal=False,
            )
        if engine is not None and runtime_run_id is not None:
            engine.request_stop(runtime_run_id, reason=normalized_reason)
        return self._view(record)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._shutting_down = True
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _execute(self, record: _RunRecord) -> None:
        try:
            engine = self._engine_factory(
                record.request,
                lambda event_type, payload: self._handle_runtime_event(
                    record, event_type, payload
                ),
            )
            with record.condition:
                record.engine = engine
                if record.status == "accepted":
                    record.status = "running"
                record.updated_at = self._clock()
            result = engine.submit(record.request.task, limits=record.request.limits)
            with record.condition:
                record.status = result.status
                record.stop_reason = result.stop_reason
                record.model_calls = result.model_calls
                record.tool_calls = result.tool_calls
                record.output = result.output
                record.updated_at = self._clock()
                if not record.terminal_event_seen:
                    self._append_event_locked(
                        record,
                        f"service.run.{result.status}",
                        {
                            "status": result.status,
                            "stop_reason": result.stop_reason,
                            "model_calls": result.model_calls,
                            "tool_calls": result.tool_calls,
                        },
                        terminal=True,
                    )
        except Exception as exc:
            with record.condition:
                record.status = "failed"
                record.stop_reason = "service_execution_failed"
                record.error = {
                    "code": "runtime_failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                }
                record.updated_at = self._clock()
                if not record.terminal_event_seen:
                    self._append_event_locked(
                        record,
                        "service.run.failed",
                        record.error,
                        terminal=True,
                    )
        finally:
            self._plugins.run_terminal(self._view(record))

    def _handle_runtime_event(
        self, record: _RunRecord, event_type: str, payload: dict
    ) -> None:
        request_stop = False
        engine: QueryEngine | None = None
        runtime_run_id: str | None = None
        terminal = event_type in {
            "run.completed",
            "run.failed",
            "run.stopped",
            "run.blocked",
            "run.budget_exhausted",
        }
        with record.condition:
            runtime_id = payload.get("run_id")
            if event_type == "run.started" and isinstance(runtime_id, str):
                record.runtime_run_id = runtime_id
                runtime_run_id = runtime_id
                record.status = (
                    "cancelling" if record.cancel_requested else "running"
                )
                request_stop = record.cancel_requested
                engine = record.engine
            if terminal:
                record.terminal_event_seen = True
                terminal_status = event_type.removeprefix("run.")
                record.status = terminal_status
                record.stop_reason = _optional_text(payload.get("stop_reason"))
                record.model_calls = _nonnegative_int(payload.get("model_calls"))
                record.tool_calls = _nonnegative_int(payload.get("tool_calls"))
            record.updated_at = self._clock()
            self._append_event_locked(record, event_type, payload, terminal=terminal)
        if request_stop and engine is not None and runtime_run_id is not None:
            engine.request_stop(
                runtime_run_id,
                reason=record.stop_reason or "user_requested",
            )

    def _append_event_locked(
        self,
        record: _RunRecord,
        event_type: str,
        payload: dict[str, Any],
        *,
        terminal: bool,
    ) -> PublicRunEvent:
        event = PublicRunEvent(
            service_run_id=record.service_run_id,
            sequence=record.next_sequence,
            event_type=event_type[:160],
            payload=sanitize_public(payload),
            terminal=terminal,
            timestamp=self._clock(),
        )
        record.next_sequence += 1
        record.events.append(event)
        record.updated_at = event.timestamp
        record.condition.notify_all()
        self._plugins.event(event)
        return event

    def _require(self, service_run_id: str) -> _RunRecord:
        with self._lock:
            try:
                return self._runs[service_run_id]
            except KeyError as exc:
                raise RunNotFoundError(
                    f"unknown service run: {service_run_id}"
                ) from exc

    @staticmethod
    def _view(record: _RunRecord) -> PublicRunView:
        with record.condition:
            return PublicRunView(
                service_run_id=record.service_run_id,
                runtime_run_id=record.runtime_run_id,
                status=record.status,
                created_at=record.created_at,
                updated_at=record.updated_at,
                last_event_sequence=record.next_sequence - 1,
                stop_reason=record.stop_reason,
                model_calls=record.model_calls,
                tool_calls=record.tool_calls,
                output=record.output,
                error=sanitize_public(record.error) if record.error else None,
            )


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 200:
        raise ValueError("idempotency key exceeds 200 characters")
    return normalized


def _optional_text(value: object) -> str | None:
    return value[:500] if isinstance(value, str) else None


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0
