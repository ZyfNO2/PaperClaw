from __future__ import annotations


def emit_event(shared: dict, event: str, **payload) -> None:
    handler = shared.get("event_handler")
    if handler is not None:
        handler(event, payload)
