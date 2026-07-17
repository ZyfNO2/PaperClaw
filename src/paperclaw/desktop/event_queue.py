"""Bounded, non-blocking queue for desktop-visible events and snapshots."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from threading import RLock
from typing import Any, Mapping


class DesktopEventQueue:
    """Thread-safe queue whose overflow policy never blocks runtime callbacks.

    Event rows are FIFO. Snapshots are coalesced so only the newest pending
    snapshot is retained. When capacity is exhausted, the oldest item is
    discarded; the runtime callback never waits for JavaScript polling.
    """

    def __init__(self, max_items: int = 512) -> None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 2:
            raise ValueError("max_items must be an integer greater than or equal to 2")
        self._max_items = max_items
        self._items: deque[dict[str, object]] = deque()
        self._lock = RLock()
        self._dropped = 0

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def publish_event(self, event: Mapping[str, Any]) -> None:
        self._publish({"kind": "event", "event": _copy_mapping(event)})

    def publish_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        item = {"kind": "snapshot", "snapshot": _copy_mapping(snapshot)}
        with self._lock:
            if self._items:
                retained = deque(
                    existing
                    for existing in self._items
                    if existing.get("kind") != "snapshot"
                )
                removed = len(self._items) - len(retained)
                self._items = retained
                self._dropped += removed
            self._append_with_overflow(item)

    def drain(self, limit: int = 200) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer in [1, 500]")
        result: list[dict[str, object]] = []
        with self._lock:
            while self._items and len(result) < limit:
                result.append(deepcopy(self._items.popleft()))
        return result

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def _publish(self, item: dict[str, object]) -> None:
        with self._lock:
            self._append_with_overflow(item)

    def _append_with_overflow(self, item: dict[str, object]) -> None:
        while len(self._items) >= self._max_items:
            self._items.popleft()
            self._dropped += 1
        self._items.append(item)


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, object]:
    return deepcopy({str(key): item for key, item in value.items()})
