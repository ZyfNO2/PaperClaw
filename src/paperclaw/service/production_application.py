"""Race-hardened durable service used by the production entry point."""

from __future__ import annotations

from .durable_application import (
    DurableRunApplicationService as _BaseDurableRunApplicationService,
)


class DurableRunApplicationService(_BaseDurableRunApplicationService):
    """Reconcile persisted cancellation when the runtime id appears late."""

    def _handle_runtime_event(
        self,
        service_run_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        super()._handle_runtime_event(service_run_id, event_type, payload)
        if event_type != "run.started":
            return
        runtime_run_id = payload.get("run_id")
        if not isinstance(runtime_run_id, str):
            return
        try:
            durable_run = self._store.get_run(service_run_id)
        except Exception:
            return
        if durable_run.state != "cancelling":
            return
        with self._lock:
            active = self._active.get(service_run_id)
            if active is None:
                return
            active.cancel_requested = True
            active.runtime_run_id = runtime_run_id
            engine = active.engine
        if engine is None:
            return
        reason = durable_run.metadata.get("stop_reason") or "user_requested"
        try:
            engine.request_stop(runtime_run_id, reason=str(reason))
        except KeyError:
            return
