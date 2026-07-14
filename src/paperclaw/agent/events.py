from __future__ import annotations


def emit_event(shared: dict, event: str, **payload) -> None:
    # Runtime nodes emit through one tiny hook so CLI/TUI/test observers can evolve without changing node logic.
    handler = shared.get("event_handler")
    if handler is not None:
        handler(event, payload)
