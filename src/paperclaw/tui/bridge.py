"""Merge QueryEngine and selected legacy runtime events for the TUI.

QueryEngine owns run lifecycle sequencing, while the existing AgentRuntime still
reports verification through its legacy observer callback. The bridge assigns a
single UI-local monotonic sequence to both sources without changing either
runtime contract. Only explicitly safe, structured legacy events are admitted.
"""

from __future__ import annotations

from threading import RLock
from typing import Callable

EventHandler = Callable[[str, dict], None]

LEGACY_EVENT_MAP = {
    "verification_completed": "verification.completed",
}


class TUIEventBridge:
    """Produce one ordered UI stream from existing runtime observer callbacks."""

    def __init__(self, handler: EventHandler) -> None:
        self._handler = handler
        self._run_id: str | None = None
        self._sequence = 0
        self._lock = RLock()

    def handle_query_event(self, event_type: str, payload: dict) -> None:
        run_id = payload.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return
        with self._lock:
            if event_type == "run.started":
                self._run_id = run_id
                self._sequence = 0
            elif self._run_id != run_id:
                return
            envelope = self._next_envelope(payload, run_id=run_id)
        self._handler(event_type, envelope)

    def handle_legacy_event(self, event_type: str, payload: dict) -> None:
        mapped = LEGACY_EVENT_MAP.get(event_type)
        if mapped is None:
            return
        with self._lock:
            if self._run_id is None:
                return
            envelope = self._next_envelope(payload, run_id=self._run_id)
        self._handler(mapped, envelope)

    def _next_envelope(self, payload: dict, *, run_id: str) -> dict:
        self._sequence += 1
        envelope = dict(payload)
        query_sequence = envelope.get("sequence")
        if query_sequence is not None:
            envelope["query_sequence"] = query_sequence
        envelope["run_id"] = run_id
        envelope["sequence"] = self._sequence
        return envelope
