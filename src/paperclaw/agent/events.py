from __future__ import annotations

from datetime import datetime, timezone


EVENT_TYPE_ALIASES = {
    "done_proposed": "done.proposed",
    "verification_planned": "verification.planned",
    "verification_started": "verification.started",
    "verification_check_completed": "verification.check.completed",
    "verification_completed": "verification.completed",
    "reflection_started": "reflection.started",
    "reflection_completed": "reflection.completed",
    "done": "run.completed",
    "stop": "run.blocked",
}


def emit_event(shared: dict, event: str, **payload) -> None:
    """Record an observational runtime event.

    v0.02 keeps trace events in memory so Verify / Reflection behavior can be audited and exported without coupling the
    loop to a database or event bus yet. The handler remains optional; the shared trace list is the authoritative
    capture for later artifacts.
    """

    shared["event_sequence"] += 1
    trace_event = {
        "run_id": shared["run_id"],
        "sequence": shared["event_sequence"],
        "step": payload.get("step", shared.get("step_count", 0)),
        "event_type": EVENT_TYPE_ALIASES.get(event, event),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    shared["trace_events"].append(trace_event)
    handler = shared.get("event_handler")
    if handler is not None:
        handler(event, payload)
