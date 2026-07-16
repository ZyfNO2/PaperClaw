"""Sanitized widgets for the MultiAgent team dashboard."""

from __future__ import annotations

from typing import Any, Mapping

from rich.markup import escape
from textual.widgets import RichLog, Static

from paperclaw.multiagent.team_view import TeamViewSnapshot


class TeamStatus(Static):
    """Compact aggregate status for one Coordinator run."""

    def show_snapshot(self, snapshot: TeamViewSnapshot) -> None:
        self.update(
            escape(
                " | ".join(
                    (
                        f"team={snapshot.run_id or '-'}",
                        f"status={snapshot.status}",
                        f"reason={snapshot.stop_reason or '-'}",
                        f"tasks={snapshot.task_count}",
                        f"running={snapshot.running_count}",
                        f"done={snapshot.completed_count}",
                        f"failed={snapshot.failed_count}",
                        f"blocked={snapshot.blocked_count}",
                        f"seq={snapshot.last_sequence}",
                    )
                )
            )
        )


class TeamWorkers(Static):
    """Read-only worker/task panel backed only by ``TeamViewSnapshot``."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._snapshot = TeamViewSnapshot()

    @property
    def snapshot(self) -> TeamViewSnapshot:
        return self._snapshot

    def show_snapshot(self, snapshot: TeamViewSnapshot) -> None:
        self._snapshot = snapshot
        lines = ["Workers", "task | agent | status | files | title / reason"]
        if not snapshot.workers:
            lines.append("(waiting for task assignment)")
        for worker in snapshot.workers:
            detail = worker.reason or worker.title or "-"
            lines.append(
                f"{worker.task_id} | {worker.agent_id or '-'} | {worker.status} | "
                f"{worker.changed_file_count} | {detail}"
            )
        self.update(escape("\n".join(lines)))


class TeamReview(Static):
    """Reviewer, fix-round and Global Verify aggregate panel."""

    def show_snapshot(self, snapshot: TeamViewSnapshot) -> None:
        self.update(
            escape(
                "Review / Global Verify\n"
                f"review={snapshot.review_verdict or '-'} | "
                f"fix_round={snapshot.fix_round}\n"
                f"global_verify={snapshot.global_verification_status or '-'}"
            )
        )


class TeamTimeline(RichLog):
    """Whitelisted team lifecycle timeline with no arbitrary event payload."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._entries: list[str] = []

    @property
    def entries(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def reset(self) -> None:
        self._entries.clear()
        self.clear()

    def add_event(
        self,
        event_type: str,
        envelope: Mapping[str, Any],
        *,
        known: bool,
    ) -> None:
        sequence = envelope.get("sequence")
        sequence_text = str(sequence) if isinstance(sequence, int) else "-"
        agent = _safe_identifier(envelope.get("agent_id")) or "-"
        task = _safe_identifier(envelope.get("task_id")) or "-"
        marker = "" if known else "[unknown] "
        text = f"{marker}{sequence_text} {event_type} agent={agent} task={task}"
        self._entries.append(text)
        self.write(escape(text))

    def add_system(self, text: str) -> None:
        safe = " ".join(str(text).split())[:300]
        self._entries.append(safe)
        self.write(escape(safe))


def _safe_identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:120] if text else None


__all__ = ["TeamReview", "TeamStatus", "TeamTimeline", "TeamWorkers"]
