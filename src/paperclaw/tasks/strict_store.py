"""Strict production durable store that forbids unfenced ownership mutation."""

from __future__ import annotations

from .contracts import TaskLeaseError
from .distributed_store import FencedSQLiteDurableTaskStore


class StrictFencedSQLiteDurableTaskStore(FencedSQLiteDurableTaskStore):
    """Production SQLite store requiring generation-fenced owner operations.

    Legacy owner APIs remain on the historical SQLite base for compatibility
    tests and migrations, but production composition must not expose an unfenced
    path that can bypass lease generation checks.
    """

    def claim_next(self, *args, **kwargs):
        del args, kwargs
        raise TaskLeaseError("unfenced claim_next is disabled; use claim_next_lease")

    def start_task(self, *args, **kwargs):
        del args, kwargs
        raise TaskLeaseError("unfenced start_task is disabled; use start_task_fenced")

    def heartbeat(self, *args, **kwargs):
        del args, kwargs
        raise TaskLeaseError("unfenced heartbeat is disabled; use heartbeat_fenced")

    def mark_side_effect_state(self, *args, **kwargs):
        del args, kwargs
        raise TaskLeaseError(
            "unfenced mark_side_effect_state is disabled; use mark_side_effect_state_fenced"
        )

    def complete_task(self, *args, **kwargs):
        del args, kwargs
        raise TaskLeaseError("unfenced complete_task is disabled; use complete_task_fenced")

    def requeue_task(self, *args, **kwargs):
        del args, kwargs
        raise TaskLeaseError("unfenced requeue_task is disabled; use requeue_task_fenced")


__all__ = ["StrictFencedSQLiteDurableTaskStore"]
