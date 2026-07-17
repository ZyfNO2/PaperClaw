"""Durable application service joining v0.12 HTTP and v0.13 execution state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Condition, Event, RLock, Thread
import time
from typing import Any, Callable
from uuid import uuid4

from paperclaw.durability.core import (
    CompareAndSwapError,
    DurableRun,
    DurableRunNotFoundError,
    IdempotencyRecordConflictError,
    InvalidTransitionError,
    RecoveryCoordinator,
)
from paperclaw.durability.service_store import (
    DurableRunEvent,
    SQLiteDurableServiceStore,
)
from paperclaw.harness import QueryEngine

from .contracts import (
    TERMINAL_SERVICE_STATUSES,
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
from .resilience import TimeoutPolicy

EngineFactory = Callable[
    [ServiceRunRequest, Callable[[str, dict], None]], QueryEngine
]

_RUNTIME_TERMINAL_EVENTS = frozenset(
    {
        "run.completed",
        "run.failed",
        "run.stopped",
        "run.blocked",
        "run.budget_exhausted",
    }
)


@dataclass
class _ActiveExecution:
    engine: QueryEngine | None = None
    runtime_run_id: str | None = None
    cancel_requested: bool = False
    heartbeat_stop: Event = field(default_factory=Event)
    timeout_stop: Event = field(default_factory=Event)


class DurableRunApplicationService:
    """SQLite-backed application service with durable queue and SSE replay."""

    def __init__(
        self,
        engine_factory: EngineFactory,
        store: SQLiteDurableServiceStore,
        *,
        max_active_runs: int = 4,
        worker_id: str | None = None,
        lease_seconds: float = 30.0,
        heartbeat_seconds: float = 5.0,
        timeout_policy: TimeoutPolicy | None = None,
        plugins: ServicePluginRegistry | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_active_runs < 1:
            raise ValueError("max_active_runs must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError(
                "heartbeat_seconds must be positive and less than lease_seconds"
            )
        self._engine_factory = engine_factory
        self._store = store
        self._max_active_runs = max_active_runs
        self._worker_id = worker_id or f"svc-worker-{uuid4().hex[:12]}"
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._timeouts = timeout_policy or TimeoutPolicy()
        self._plugins = plugins or ServicePluginRegistry()
        self._clock = clock
        self._executor = ThreadPoolExecutor(
            max_workers=max_active_runs,
            thread_name_prefix="paperclaw-durable-service",
        )
        self._active: dict[str, _ActiveExecution] = {}
        self._lock = RLock()
        self._event_condition = Condition(RLock())
        self._shutting_down = False

        reconciled = RecoveryCoordinator(self._store.run_store).reconcile()
        for item in reconciled:
            if item.applied:
                self._append_event(
                    item.run_id,
                    "service.run.reconciled",
                    {
                        "previous_state": item.previous_state,
                        "next_state": item.next_state,
                        "reason": item.reason,
                        "policy_id": item.policy_id,
                    },
                    terminal=item.next_state == "recovery_required",
                )
        self._schedule_drainers()

    @property
    def store(self) -> SQLiteDurableServiceStore:
        return self._store

    def submit(
        self,
        request: ServiceRunRequest,
        *,
        idempotency_key: str | None = None,
    ) -> SubmitOutcome:
        key = _normalize_idempotency_key(idempotency_key)
        with self._lock:
            if self._shutting_down:
                raise ServiceShuttingDownError("service is shutting down")
        run_id = f"svc-{uuid4().hex[:16]}"
        metadata = {
            "service_request": request.to_metadata(),
            "runtime_run_id": None,
            "stop_reason": None,
            "model_calls": 0,
            "tool_calls": 0,
            "output": None,
            "error": None,
        }
        try:
            run, created = self._store.create_run(
                run_id,
                request.digest(),
                idempotency_key=key,
                metadata=metadata,
            )
        except IdempotencyRecordConflictError as exc:
            raise IdempotencyConflictError(str(exc)) from exc
        if created:
            event = self._append_event(
                run.run_id,
                "service.run.accepted",
                {
                    "conversation_id": request.conversation_id,
                    "client_id": request.client_id,
                    "disconnect_policy": request.disconnect_policy,
                },
                terminal=False,
            )
            self._plugins.event(event)
            view = self._view(self._store.get_run(run.run_id))
            self._plugins.run_created(view)
        else:
            view = self._view(run)
        self._schedule_drainers()
        return SubmitOutcome(view, created=created)

    def get_run(self, service_run_id: str) -> PublicRunView:
        try:
            return self._view(self._store.get_run(service_run_id))
        except DurableRunNotFoundError as exc:
            raise RunNotFoundError(f"unknown service run: {service_run_id}") from exc

    def get_disconnect_policy(self, service_run_id: str) -> str:
        run = self._require(service_run_id)
        request = ServiceRunRequest.from_metadata(
            _mapping(run.metadata.get("service_request"), "service_request")
        )
        return request.disconnect_policy

    def list_events(
        self,
        service_run_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[PublicRunEvent, ...]:
        try:
            events = self._store.list_events(
                service_run_id,
                after_sequence=after_sequence,
            )
        except DurableRunNotFoundError as exc:
            raise RunNotFoundError(f"unknown service run: {service_run_id}") from exc
        return tuple(self._public_event(event) for event in events)

    def wait_for_events(
        self,
        service_run_id: str,
        *,
        after_sequence: int = 0,
        timeout: float = 10.0,
    ) -> tuple[tuple[PublicRunEvent, ...], bool]:
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        if timeout < 0:
            raise ValueError("timeout must not be negative")
        deadline = time.monotonic() + timeout
        while True:
            events = self.list_events(
                service_run_id,
                after_sequence=after_sequence,
            )
            terminal = self.get_run(service_run_id).terminal
            if events or terminal or timeout == 0:
                return events, terminal
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return (), terminal
            with self._event_condition:
                self._event_condition.wait(min(remaining, 0.25))

    def cancel(
        self,
        service_run_id: str,
        *,
        reason: str = "user_requested",
    ) -> PublicRunView:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("cancel reason must not be empty")
        while True:
            run = self._require(service_run_id)
            if run.state in TERMINAL_SERVICE_STATUSES:
                raise RunNotCancellableError("run is already terminal")
            try:
                if run.state == "queued":
                    updated = self._store.transition(
                        run.run_id,
                        expected_state="queued",
                        expected_version=run.version,
                        next_state="stopped",
                        reason=normalized_reason,
                        actor="service:cancel",
                    )
                    self._store.merge_metadata(
                        run.run_id,
                        {"stop_reason": normalized_reason},
                    )
                    self._append_event(
                        run.run_id,
                        "service.run.cancel_requested",
                        {"reason": normalized_reason},
                        terminal=False,
                    )
                    terminal_event = self._append_event(
                        run.run_id,
                        "service.run.stopped",
                        {"reason": normalized_reason, "phase": "queued"},
                        terminal=True,
                    )
                    self._plugins.event(terminal_event)
                    view = self._view(updated)
                    self._plugins.run_terminal(view)
                    return view
                if run.state == "running":
                    self._store.transition(
                        run.run_id,
                        expected_state="running",
                        expected_version=run.version,
                        next_state="cancelling",
                        reason=normalized_reason,
                        actor="service:cancel",
                    )
                    self._store.merge_metadata(
                        run.run_id,
                        {"stop_reason": normalized_reason},
                    )
                    self._append_event(
                        run.run_id,
                        "service.run.cancel_requested",
                        {"reason": normalized_reason},
                        terminal=False,
                    )
                    break
                if run.state == "cancelling":
                    break
                raise RunNotCancellableError(
                    f"run cannot be cancelled from state={run.state}"
                )
            except CompareAndSwapError:
                continue
        with self._lock:
            active = self._active.get(service_run_id)
            if active is not None:
                active.cancel_requested = True
                engine = active.engine
                runtime_run_id = active.runtime_run_id
            else:
                engine = None
                runtime_run_id = None
        if engine is not None and runtime_run_id is not None:
            try:
                engine.request_stop(runtime_run_id, reason=normalized_reason)
            except KeyError:
                pass
        return self.get_run(service_run_id)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._shutting_down = True
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _schedule_drainers(self) -> None:
        with self._lock:
            if self._shutting_down:
                return
            for _ in range(self._max_active_runs):
                self._executor.submit(self._drain_queue)

    def _drain_queue(self) -> None:
        while True:
            with self._lock:
                if self._shutting_down:
                    return
            run = self._store.claim_next(
                self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            if run is None:
                return
            self._execute_claimed(run)

    def _execute_claimed(self, claimed: DurableRun) -> None:
        if self._clock() - claimed.created_at > self._timeouts.queue_timeout_seconds:
            self._fail_claimed(
                claimed,
                code="queue_timeout",
                message="run exceeded queue timeout before execution",
            )
            return
        try:
            request = ServiceRunRequest.from_metadata(
                _mapping(claimed.metadata.get("service_request"), "service_request")
            )
        except Exception as exc:
            self._fail_claimed(
                claimed,
                code="invalid_durable_request",
                message=f"{type(exc).__name__}: {exc}",
            )
            return

        active = _ActiveExecution()
        with self._lock:
            self._active[claimed.run_id] = active
        heartbeat = Thread(
            target=self._heartbeat,
            args=(claimed.run_id, active),
            name=f"paperclaw-heartbeat-{claimed.run_id}",
            daemon=True,
        )
        heartbeat.start()
        timeout_thread = Thread(
            target=self._run_timeout,
            args=(claimed.run_id, active),
            name=f"paperclaw-timeout-{claimed.run_id}",
            daemon=True,
        )
        timeout_thread.start()

        try:
            engine = self._engine_factory(
                request,
                lambda event_type, payload: self._handle_runtime_event(
                    claimed.run_id,
                    event_type,
                    payload,
                ),
            )
            with self._lock:
                active.engine = engine
            result = engine.submit(request.task, limits=request.limits)
            current = self._store.get_run(claimed.run_id)
            desired_state = result.status
            stop_reason = result.stop_reason
            if current.state == "cancelling":
                desired_state = "stopped"
                stop_reason = current.metadata.get("stop_reason") or stop_reason
            if desired_state not in TERMINAL_SERVICE_STATUSES:
                desired_state = "failed"
                stop_reason = "invalid_runtime_terminal_status"
            self._store.merge_metadata(
                claimed.run_id,
                {
                    "runtime_run_id": result.run_id,
                    "stop_reason": stop_reason,
                    "model_calls": result.model_calls,
                    "tool_calls": result.tool_calls,
                    "output": result.output,
                    "error": None,
                },
            )
            current = self._store.get_run(claimed.run_id)
            if not current.terminal:
                self._store.transition(
                    claimed.run_id,
                    expected_state=current.state,
                    expected_version=current.version,
                    next_state=desired_state,
                    reason=str(stop_reason or desired_state),
                    actor=self._worker_id,
                )
            final_event = self._append_event(
                claimed.run_id,
                "service.run.finalized",
                {
                    "status": desired_state,
                    "stop_reason": stop_reason,
                    "model_calls": result.model_calls,
                    "tool_calls": result.tool_calls,
                },
                terminal=True,
            )
            self._plugins.event(final_event)
        except Exception as exc:
            current = self._store.get_run(claimed.run_id)
            self._store.merge_metadata(
                claimed.run_id,
                {
                    "stop_reason": "service_execution_failed",
                    "error": {
                        "code": "runtime_failed",
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:500],
                    },
                },
            )
            current = self._store.get_run(claimed.run_id)
            if not current.terminal:
                next_state = (
                    "failed"
                    if current.state in {"running", "cancelling"}
                    else "recovery_required"
                )
                try:
                    self._store.transition(
                        claimed.run_id,
                        expected_state=current.state,
                        expected_version=current.version,
                        next_state=next_state,
                        reason="service_execution_failed",
                        actor=self._worker_id,
                    )
                except (CompareAndSwapError, InvalidTransitionError):
                    pass
            failed_event = self._append_event(
                claimed.run_id,
                "service.run.failed",
                {
                    "code": "runtime_failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                },
                terminal=True,
            )
            self._plugins.event(failed_event)
        finally:
            active.heartbeat_stop.set()
            active.timeout_stop.set()
            with self._lock:
                self._active.pop(claimed.run_id, None)
            try:
                self._store.release_lease(claimed.run_id, self._worker_id)
            except Exception:
                pass
            self._plugins.run_terminal(self.get_run(claimed.run_id))

    def _handle_runtime_event(
        self,
        service_run_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        terminal = event_type in _RUNTIME_TERMINAL_EVENTS
        event = self._append_event(
            service_run_id,
            event_type,
            payload,
            terminal=terminal,
        )
        self._plugins.event(event)
        runtime_run_id = payload.get("run_id")
        if event_type == "run.started" and isinstance(runtime_run_id, str):
            self._store.merge_metadata(
                service_run_id,
                {"runtime_run_id": runtime_run_id},
            )
            with self._lock:
                active = self._active.get(service_run_id)
                if active is None:
                    return
                active.runtime_run_id = runtime_run_id
                should_cancel = active.cancel_requested
                engine = active.engine
            if should_cancel and engine is not None:
                reason = self._store.get_run(service_run_id).metadata.get(
                    "stop_reason", "user_requested"
                )
                try:
                    engine.request_stop(runtime_run_id, reason=str(reason))
                except KeyError:
                    pass

    def _heartbeat(self, run_id: str, active: _ActiveExecution) -> None:
        while not active.heartbeat_stop.wait(self._heartbeat_seconds):
            try:
                run = self._store.get_run(run_id)
                if run.state not in {"running", "cancelling"}:
                    return
                self._store.renew_lease(
                    run_id,
                    self._worker_id,
                    expected_run_version=run.version,
                    lease_seconds=self._lease_seconds,
                )
            except Exception:
                return

    def _run_timeout(self, run_id: str, active: _ActiveExecution) -> None:
        if active.timeout_stop.wait(self._timeouts.run_timeout_seconds):
            return
        try:
            timeout_event = self._append_event(
                run_id,
                "service.run.timeout",
                {
                    "code": "run_timeout",
                    "seconds": self._timeouts.run_timeout_seconds,
                },
                terminal=False,
            )
            self._plugins.event(timeout_event)
            self.cancel(run_id, reason="run_timeout")
        except (RunNotFoundError, RunNotCancellableError):
            return

    def _fail_claimed(self, run: DurableRun, *, code: str, message: str) -> None:
        self._store.merge_metadata(
            run.run_id,
            {
                "stop_reason": code,
                "error": {"code": code, "message": message[:500]},
            },
        )
        current = self._store.get_run(run.run_id)
        if not current.terminal:
            self._store.transition(
                run.run_id,
                expected_state=current.state,
                expected_version=current.version,
                next_state="failed",
                reason=code,
                actor=self._worker_id,
            )
        event = self._append_event(
            run.run_id,
            "service.run.failed",
            {"code": code, "message": message[:500]},
            terminal=True,
        )
        self._plugins.event(event)
        self._plugins.run_terminal(self.get_run(run.run_id))

    def _append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        terminal: bool,
    ) -> PublicRunEvent:
        event = self._store.append_event(
            run_id,
            event_type,
            sanitize_public(payload),
            terminal=terminal,
        )
        public = self._public_event(event)
        with self._event_condition:
            self._event_condition.notify_all()
        return public

    def _require(self, service_run_id: str) -> DurableRun:
        try:
            return self._store.get_run(service_run_id)
        except DurableRunNotFoundError as exc:
            raise RunNotFoundError(f"unknown service run: {service_run_id}") from exc

    def _view(self, run: DurableRun) -> PublicRunView:
        metadata = run.metadata
        return PublicRunView(
            service_run_id=run.run_id,
            runtime_run_id=_optional_text(metadata.get("runtime_run_id")),
            status=run.state,
            created_at=run.created_at,
            updated_at=run.updated_at,
            last_event_sequence=self._store.last_event_sequence(run.run_id),
            stop_reason=_optional_text(
                metadata.get("stop_reason") or run.terminal_reason
            ),
            model_calls=_nonnegative_int(metadata.get("model_calls")),
            tool_calls=_nonnegative_int(metadata.get("tool_calls")),
            output=_optional_text(metadata.get("output")),
            error=(
                sanitize_public(metadata.get("error"))
                if isinstance(metadata.get("error"), dict)
                else None
            ),
        )

    @staticmethod
    def _public_event(event: DurableRunEvent) -> PublicRunEvent:
        return PublicRunEvent(
            service_run_id=event.run_id,
            sequence=event.sequence,
            event_type=event.event_type,
            payload=sanitize_public(event.payload),
            terminal=event.terminal,
            timestamp=event.timestamp,
        )


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 200 or any(char.isspace() for char in normalized):
        raise ValueError(
            "idempotency key must be a compact identifier up to 200 characters"
        )
    return normalized


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
