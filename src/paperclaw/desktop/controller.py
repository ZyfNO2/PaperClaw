"""Threaded desktop controller over the existing synchronous QueryEngine."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock, Thread, current_thread
from typing import Any, Protocol

from paperclaw.harness import RunLimits
from paperclaw.tui.state import EventReducer

from .contracts import (
    DesktopPublicError,
    DesktopRunRequest,
    DesktopRunSnapshot,
    public_event_row,
    sanitize_public_message,
)
from .event_queue import DesktopEventQueue
from .runtime_factory import DesktopRuntimeFactory


class RuntimeFactoryLike(Protocol):
    def create(self, request: DesktopRunRequest, event_handler: Any) -> Any: ...


_PROVIDER_ERROR_MAP = {
    "AUTHENTICATION_FAILED": (
        "provider_authentication_error",
        "Provider authentication failed.",
    ),
    "PERMISSION_DENIED": (
        "provider_authentication_error",
        "Provider rejected the supplied credentials or permission.",
    ),
    "RATE_LIMITED": ("provider_rate_limited", "Provider rate limit was reached."),
    "PROVIDER_NETWORK_ERROR": (
        "provider_network_error",
        "Provider could not be reached.",
    ),
    "PROVIDER_TEMPORARILY_UNAVAILABLE": (
        "provider_server_error",
        "Provider is temporarily unavailable.",
    ),
    "PROVIDER_SERVER_ERROR": (
        "provider_server_error",
        "Provider returned a server error.",
    ),
    "INVALID_PROVIDER_RESPONSE": (
        "provider_invalid_response",
        "Provider returned an invalid response.",
    ),
    "EMPTY_PROVIDER_RESPONSE": (
        "provider_invalid_response",
        "Provider returned an empty response.",
    ),
    "THINKING_ONLY_RESPONSE": (
        "provider_invalid_response",
        "Provider returned no usable final response.",
    ),
    "MODEL_OR_ENDPOINT_NOT_FOUND": (
        "provider_configuration_error",
        "Provider endpoint or model was not found.",
    ),
    "INVALID_REQUEST": (
        "provider_configuration_error",
        "Provider rejected the request configuration.",
    ),
}


class DesktopController:
    """Own one desktop window lifecycle and exactly one active run."""

    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactoryLike | None = None,
        event_queue: DesktopEventQueue | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory or DesktopRuntimeFactory()
        self._queue = event_queue or DesktopEventQueue()
        self._reducer = EventReducer()
        self._lock = RLock()
        self._engine: Any | None = None
        self._worker: Thread | None = None
        self._active = False
        self._closed = False
        self._cancel_requested = False
        self._active_secret = ""
        self._verification_status: str | None = None
        self._verification_summary: str | None = None
        self._final_result: str | None = None
        self._error_code: str | None = None
        self._error_message: str | None = None
        self._status_override: str | None = None
        self._stop_reason_override: str | None = None
        self._terminal_override: bool | None = None

    def start_run(self, value: Mapping[str, Any]) -> dict[str, object]:
        try:
            request = DesktopRunRequest.from_mapping(value)
        except DesktopPublicError as exc:
            return exc.to_public_dict()

        with self._lock:
            if self._closed:
                return DesktopPublicError(
                    "runtime_error",
                    "Desktop window is closing and cannot start a new run.",
                ).to_public_dict()
            if self._active:
                return DesktopPublicError(
                    "run_already_active",
                    "A run is already active in this window.",
                ).to_public_dict()

            self._reset_for_run_locked(secret=request.api_key)
            self._active = True
            self._status_override = "starting"
            worker = Thread(
                target=self._run_worker,
                args=(request,),
                name="paperclaw-desktop-run",
                daemon=True,
            )
            self._worker = worker
            self._publish_snapshot_locked()
            try:
                worker.start()
            except RuntimeError:
                self._active = False
                self._worker = None
                self._status_override = "failed"
                self._stop_reason_override = "worker_start_failed"
                self._terminal_override = True
                self._set_public_error_locked(
                    "runtime_error",
                    "Desktop worker could not be started.",
                )
                self._publish_snapshot_locked()
                self._active_secret = ""
                return DesktopPublicError(
                    "runtime_error",
                    "Desktop worker could not be started.",
                ).to_public_dict()

            return {
                "ok": True,
                "accepted": True,
                "status": "starting",
            }

    def cancel_run(self) -> dict[str, object]:
        engine: Any | None = None
        run_id: str | None = None
        with self._lock:
            if not self._active:
                return DesktopPublicError(
                    "run_not_active",
                    "There is no active run to cancel.",
                ).to_public_dict()
            if self._cancel_requested:
                return {"ok": True, "accepted": False, "status": "stopping"}
            self._cancel_requested = True
            engine = self._engine
            run_id = self._reducer.snapshot.run_id

        accepted = True
        if engine is not None and run_id is not None:
            accepted = self._request_stop(engine, run_id)
        return {
            "ok": True,
            "accepted": accepted,
            "status": "stopping" if accepted else self.get_state()["state"]["status"],
        }

    def poll_events(self, limit: int = 200) -> dict[str, object]:
        try:
            items = self._queue.drain(limit)
        except ValueError as exc:
            return DesktopPublicError("validation_error", str(exc)).to_public_dict()
        return {
            "ok": True,
            "items": items,
            "dropped_count": self._queue.dropped_count,
        }

    def get_state(self) -> dict[str, object]:
        with self._lock:
            state = self._snapshot_locked().to_public_dict(secret=self._active_secret)
            state["active"] = self._active
            state["closed"] = self._closed
            return {"ok": True, "state": state}

    def shutdown(self, *, join_timeout: float = 2.0) -> None:
        with self._lock:
            self._closed = True
            active = self._active
            worker = self._worker
        if active:
            self.cancel_run()
        if (
            worker is not None
            and worker.is_alive()
            and worker is not current_thread()
            and join_timeout > 0
        ):
            worker.join(timeout=join_timeout)

    def _run_worker(self, request: DesktopRunRequest) -> None:
        secret = request.api_key
        try:
            engine = self._runtime_factory.create(request, self._handle_event)
            task = request.task
            limits = RunLimits(
                max_steps=request.max_steps,
                max_model_calls=request.max_model_calls,
                max_tool_calls=request.max_tool_calls,
            )
            request = None  # type: ignore[assignment]
            with self._lock:
                self._engine = engine
            result = engine.submit(task, limits=limits)
            with self._lock:
                self._reducer.apply_result(
                    run_id=result.run_id,
                    status=result.status,
                    stop_reason=result.stop_reason,
                    model_calls=result.model_calls,
                    tool_calls=result.tool_calls,
                    last_sequence=result.last_event_sequence,
                )
                self._status_override = None
                self._stop_reason_override = None
                self._terminal_override = None
                self._final_result = sanitize_public_message(
                    result.output,
                    secret=secret,
                    limit=200_000,
                ) or None
                if result.status == "failed" and self._error_code is None:
                    self._set_public_error_locked(
                        "runtime_error",
                        "PaperClaw runtime failed.",
                    )
                self._publish_snapshot_locked()
        except DesktopPublicError as exc:
            with self._lock:
                self._mark_synthetic_failure_locked(exc.code, exc.message)
        except Exception as exc:
            with self._lock:
                self._mark_synthetic_failure_locked(
                    "runtime_error",
                    f"Desktop runtime could not start ({type(exc).__name__}).",
                )
        finally:
            with self._lock:
                self._active = False
                self._engine = None
                self._active_secret = ""
                self._publish_snapshot_locked(secret_override=secret)

    def _handle_event(self, event_type: str, payload: dict) -> None:
        engine_to_cancel: Any | None = None
        run_to_cancel: str | None = None
        with self._lock:
            reduced = self._reducer.apply(event_type, payload)
            if not reduced.accepted:
                return
            self._status_override = None
            self._stop_reason_override = None
            self._terminal_override = None

            if event_type == "verification.completed":
                result = payload.get("result")
                result_map = result if isinstance(result, Mapping) else {}
                self._verification_status = _optional_text(result_map.get("status"), 100)
                self._verification_summary = sanitize_public_message(
                    result_map.get("summary"),
                    secret=self._active_secret,
                    limit=2_000,
                ) or None

            if event_type == "model.failed":
                provider_code = _optional_text(
                    payload.get("provider_error_code") or payload.get("error_code"),
                    100,
                )
                if provider_code:
                    self._capture_provider_error_locked(provider_code)
            elif event_type == "run.failed" and self._error_code is None:
                self._set_public_error_locked("runtime_error", "PaperClaw runtime failed.")

            row = public_event_row(event_type, payload).to_public_dict(
                secret=self._active_secret
            )
            self._queue.publish_event(row)
            self._publish_snapshot_locked()

            if (
                event_type == "run.started"
                and self._cancel_requested
                and self._engine is not None
                and reduced.snapshot.run_id is not None
            ):
                engine_to_cancel = self._engine
                run_to_cancel = reduced.snapshot.run_id

        if engine_to_cancel is not None and run_to_cancel is not None:
            self._request_stop(engine_to_cancel, run_to_cancel)

    def _request_stop(self, engine: Any, run_id: str) -> bool:
        try:
            return bool(engine.request_stop(run_id, reason="user_requested"))
        except (KeyError, RuntimeError, ValueError):
            return False

    def _capture_provider_error_locked(self, provider_code: str) -> None:
        public_code, message = _PROVIDER_ERROR_MAP.get(
            provider_code,
            ("runtime_error", "Model call failed."),
        )
        self._set_public_error_locked(public_code, message)

    def _set_public_error_locked(self, code: str, message: str) -> None:
        self._error_code = code
        self._error_message = sanitize_public_message(
            message,
            secret=self._active_secret,
            limit=500,
        )

    def _mark_synthetic_failure_locked(self, code: str, message: str) -> None:
        self._status_override = "failed"
        self._stop_reason_override = "runtime_initialization_failed"
        self._terminal_override = True
        self._set_public_error_locked(code, message)
        self._publish_snapshot_locked()

    def _reset_for_run_locked(self, *, secret: str) -> None:
        self._queue.clear()
        self._reducer.reset()
        self._engine = None
        self._cancel_requested = False
        self._active_secret = secret
        self._verification_status = None
        self._verification_summary = None
        self._final_result = None
        self._error_code = None
        self._error_message = None
        self._status_override = None
        self._stop_reason_override = None
        self._terminal_override = None

    def _snapshot_locked(self) -> DesktopRunSnapshot:
        reduced = self._reducer.snapshot
        return DesktopRunSnapshot(
            run_id=reduced.run_id,
            status=self._status_override or reduced.status,
            stop_reason=self._stop_reason_override or reduced.stop_reason,
            model_calls=reduced.model_calls,
            tool_calls=reduced.tool_calls,
            last_sequence=reduced.last_sequence,
            terminal=(
                self._terminal_override
                if self._terminal_override is not None
                else reduced.terminal
            ),
            verification_status=self._verification_status,
            verification_summary=self._verification_summary,
            final_result=self._final_result,
            error_code=self._error_code,
            error_message=self._error_message,
        )

    def _publish_snapshot_locked(self, *, secret_override: str | None = None) -> None:
        secret = self._active_secret if secret_override is None else secret_override
        self._queue.publish_snapshot(self._snapshot_locked().to_public_dict(secret=secret))


def _optional_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None
