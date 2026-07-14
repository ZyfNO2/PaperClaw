"""Event envelope and emission helpers for the MultiAgent team.

Events carry enough identity (run, agent, task, sequence) that any trace can be
replayed and debugged without relying on free-form logs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any
from uuid import uuid4


@dataclass
class EventEnvelope:
    """Stable envelope for every team event.

    schema_version is pinned to v1 for v0.03. Future versions must keep forward
    compatibility: readers must tolerate unknown payload keys and older envelopes
    without sequence/run_id should be rejected rather than guessed.
    """

    event_id: str
    event_type: str
    schema_version: str
    run_id: str
    agent_id: str
    task_id: str
    sequence: int
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


def emit_team_event(
    team_state: dict,
    event_type: str,
    agent_id: str,
    task_id: str,
    **payload: Any,
) -> EventEnvelope:
    """Record a team event into the shared team state and optional handler.

    The team_state is authoritative: it holds run_id, event_sequence, and the
    trace_events list. Handlers are observational only. A lock protects sequence
    increment and list append because multiple Workers may emit concurrently.
    """

    lock = team_state.setdefault("_event_lock", threading.Lock())
    with lock:
        team_state.setdefault("event_sequence", 0)
        team_state["event_sequence"] += 1
        team_state.setdefault("trace_events", [])
        team_state.setdefault("run_id", f"unknown-{uuid4().hex[:8]}")
        envelope = EventEnvelope(
            event_id=f"evt-{uuid4().hex[:12]}",
            event_type=event_type,
            schema_version="v1",
            run_id=team_state["run_id"],
            agent_id=agent_id,
            task_id=task_id,
            sequence=team_state["event_sequence"],
            payload=payload,
        )
        team_state["trace_events"].append(envelope.to_dict())
    handler = team_state.get("event_handler")
    if handler is not None:
        handler(event_type, envelope.to_dict())
    return envelope
