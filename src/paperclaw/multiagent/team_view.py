"""Read-only projection of MultiAgent events into a safe team view.

The projector is independent from Textual and can be passed directly as the
existing Coordinator ``event_handler``. It stores aggregate lifecycle facts only:
worker status, counts, review verdicts and stop reasons. Objectives, prompts,
changed-file names, tool output and hidden reasoning are intentionally excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Mapping

from paperclaw.multiagent.contracts import TeamStopReason, WorkerResult, WorkerStatus
from paperclaw.multiagent.coordinator import CoordinatorResult


@dataclass(frozen=True)
class WorkerView:
    """Sanitized visible state for one task/Worker pair."""

    task_id: str
    agent_id: str = ""
    title: str = ""
    status: str = "pending"
    changed_file_count: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class TeamViewSnapshot:
    """Immutable aggregate state suitable for CLI, TUI or tests."""

    run_id: str | None = None
    status: str = "idle"
    stop_reason: str | None = None
    task_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    cancelled_count: int = 0
    running_count: int = 0
    fix_round: int = 0
    review_verdict: str | None = None
    global_verification_status: str | None = None
    last_sequence: int = 0
    terminal: bool = False
    workers: tuple[WorkerView, ...] = ()


@dataclass(frozen=True)
class TeamViewUpdate:
    """Outcome of reducing one team event."""

    accepted: bool
    snapshot: TeamViewSnapshot
    rejection_reason: str | None = None
    known_event: bool = True


KNOWN_TEAM_EVENTS = frozenset(
    {
        "team.started",
        "team.single_agent_path",
        "team.dag_invalid",
        "team.budget_exhausted",
        "team.fix_round_started",
        "task.assigned",
        "task.accepted",
        "task.progress",
        "task.completed",
        "task.failed",
        "task.blocked",
        "review.requested",
        "review.completed",
        "global_verification.completed",
        "team.stopped",
    }
)


class TeamViewReducer:
    """Reduce one monotonic EventEnvelope v1 stream into aggregate UI state."""

    def __init__(self) -> None:
        self._run_id: str | None = None
        self._status = "idle"
        self._stop_reason: str | None = None
        self._task_count = 0
        self._fix_round = 0
        self._review_verdict: str | None = None
        self._global_verification_status: str | None = None
        self._last_sequence = 0
        self._terminal = False
        self._global_event_seen = False
        self._workers: dict[str, WorkerView] = {}

    @property
    def snapshot(self) -> TeamViewSnapshot:
        return self._snapshot()

    def reset(self) -> TeamViewSnapshot:
        self.__init__()
        return self.snapshot

    def apply(
        self,
        event_type: str,
        envelope: Mapping[str, Any],
    ) -> TeamViewUpdate:
        run_id = _required_text(envelope.get("run_id"))
        sequence = envelope.get("sequence")
        if run_id is None:
            return self._reject("missing run_id")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            return self._reject("invalid sequence")
        if self._run_id is not None and run_id != self._run_id:
            return self._reject("event belongs to another team run")
        if sequence <= self._last_sequence:
            return self._reject("stale or duplicate sequence")
        if self._terminal and event_type != "global_verification.completed":
            return self._reject("event arrived after terminal state")
        if event_type == "global_verification.completed" and self._global_event_seen:
            return self._reject("duplicate global verification event")

        if self._run_id is None:
            self._run_id = run_id
        self._last_sequence = sequence
        payload = envelope.get("payload")
        payload_map = payload if isinstance(payload, Mapping) else {}
        agent_id = _required_text(envelope.get("agent_id")) or ""
        task_id = _required_text(envelope.get("task_id")) or ""

        if event_type == "team.started":
            self._status = "running"
            self._task_count = _non_negative_int(payload_map.get("task_count"))
        elif event_type == "team.dag_invalid":
            self._status = "blocked"
            self._stop_reason = "dag_invalid"
        elif event_type == "team.budget_exhausted":
            self._status = "stopping"
            self._stop_reason = "budget_exhausted"
        elif event_type == "team.fix_round_started":
            self._fix_round = max(
                self._fix_round,
                _non_negative_int(payload_map.get("fix_round")),
            )
        elif event_type == "review.completed":
            self._review_verdict = _safe_text(payload_map.get("verdict"), limit=40)
        elif event_type == "task.assigned":
            self._set_worker(
                task_id,
                agent_id=agent_id,
                title=_safe_text(payload_map.get("title"), limit=120) or "",
                status="running",
            )
        elif event_type == "task.accepted":
            self._set_worker(task_id, agent_id=agent_id, status="running")
        elif event_type == "task.progress":
            self._set_worker(task_id, agent_id=agent_id, status="running")
        elif event_type == "task.completed":
            self._set_worker(
                task_id,
                agent_id=agent_id,
                status="completed",
                changed_file_count=_safe_list_length(
                    payload_map.get("changed_files")
                ),
            )
        elif event_type == "task.failed":
            self._set_worker(
                task_id,
                agent_id=agent_id,
                status="failed",
                changed_file_count=_safe_list_length(
                    payload_map.get("changed_files")
                ),
                reason=_safe_text(
                    payload_map.get("stop_reason") or payload_map.get("reason"),
                    limit=80,
                ),
            )
        elif event_type == "task.blocked":
            reason = _safe_text(payload_map.get("reason"), limit=80)
            status = "cancelled" if reason == "cancelled" else "blocked"
            self._set_worker(
                task_id,
                agent_id=agent_id,
                status=status,
                reason=reason,
            )
        elif event_type == "team.stopped":
            self._terminal = True
            self._stop_reason = _normalize_stop_reason(
                payload_map.get("stop_reason")
            )
            self._status = _team_status(self._stop_reason)
        elif event_type == "global_verification.completed":
            self._global_event_seen = True
            self._global_verification_status = _safe_text(
                payload_map.get("status"), limit=40
            )
            effective = _normalize_stop_reason(
                payload_map.get("effective_stop_reason")
            )
            if effective:
                self._stop_reason = effective
                self._status = _team_status(effective)
            self._terminal = True

        known = event_type in KNOWN_TEAM_EVENTS
        return TeamViewUpdate(
            accepted=True,
            snapshot=self.snapshot,
            known_event=known,
        )

    def apply_result(self, result: CoordinatorResult) -> TeamViewSnapshot:
        """Reconcile a final CoordinatorResult when an event was not observed."""

        if not self._terminal:
            for task_id, worker_result in result.task_results.items():
                self._set_worker_from_result(task_id, worker_result)
            self._stop_reason = _normalize_stop_reason(result.stop_reason)
            self._status = _team_status(self._stop_reason)
            self._terminal = True
        return self.snapshot

    def _set_worker_from_result(
        self,
        task_id: str,
        result: WorkerResult,
    ) -> None:
        raw_status = (
            result.status.value
            if isinstance(result.status, WorkerStatus)
            else str(result.status)
        )
        self._set_worker(
            task_id,
            status=raw_status,
            changed_file_count=len(result.changed_files),
        )

    def _set_worker(
        self,
        task_id: str,
        *,
        agent_id: str | None = None,
        title: str | None = None,
        status: str | None = None,
        changed_file_count: int | None = None,
        reason: str | None = None,
    ) -> None:
        if not task_id or task_id in {"root", "review", "global-verify"}:
            return
        current = self._workers.get(task_id, WorkerView(task_id=task_id))
        self._workers[task_id] = WorkerView(
            task_id=task_id,
            agent_id=current.agent_id if agent_id is None else agent_id,
            title=current.title if title is None else title,
            status=current.status if status is None else status,
            changed_file_count=(
                current.changed_file_count
                if changed_file_count is None
                else max(0, changed_file_count)
            ),
            reason=current.reason if reason is None else reason,
        )
        self._task_count = max(self._task_count, len(self._workers))

    def _snapshot(self) -> TeamViewSnapshot:
        workers = tuple(sorted(self._workers.values(), key=lambda item: item.task_id))
        statuses = [worker.status for worker in workers]
        return TeamViewSnapshot(
            run_id=self._run_id,
            status=self._status,
            stop_reason=self._stop_reason,
            task_count=max(self._task_count, len(workers)),
            completed_count=statuses.count("completed"),
            failed_count=statuses.count("failed"),
            blocked_count=statuses.count("blocked"),
            cancelled_count=statuses.count("cancelled"),
            running_count=statuses.count("running"),
            fix_round=self._fix_round,
            review_verdict=self._review_verdict,
            global_verification_status=self._global_verification_status,
            last_sequence=self._last_sequence,
            terminal=self._terminal,
            workers=workers,
        )

    def _reject(self, reason: str) -> TeamViewUpdate:
        return TeamViewUpdate(
            accepted=False,
            snapshot=self.snapshot,
            rejection_reason=reason,
        )


class LiveTeamView:
    """Thread-safe event consumer for the existing Coordinator callback."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._reducer = TeamViewReducer()

    def handle_event(self, event_type: str, envelope: dict[str, Any]) -> None:
        with self._lock:
            self._reducer.apply(event_type, envelope)

    @property
    def snapshot(self) -> TeamViewSnapshot:
        with self._lock:
            return self._reducer.snapshot

    def reset(self) -> TeamViewSnapshot:
        with self._lock:
            return self._reducer.reset()


def project_coordinator_result(result: CoordinatorResult) -> TeamViewSnapshot:
    """Build a deterministic final snapshot from an existing CoordinatorResult."""

    reducer = TeamViewReducer()
    events = sorted(
        (event for event in result.trace_events if isinstance(event, Mapping)),
        key=lambda event: _non_negative_int(event.get("sequence")),
    )
    for event in events:
        event_type = _required_text(event.get("event_type"))
        if event_type is not None:
            reducer.apply(event_type, event)
    return reducer.apply_result(result)


def _team_status(stop_reason: str | None) -> str:
    if stop_reason in {
        TeamStopReason.COMPLETED.value,
        TeamStopReason.ALL_TASKS_COMPLETED.value,
    }:
        return "completed"
    if stop_reason in {
        TeamStopReason.BLOCKED.value,
        TeamStopReason.REFLECTION_LIMIT.value,
    }:
        return "blocked"
    if stop_reason in {
        TeamStopReason.BUDGET_EXHAUSTED.value,
        TeamStopReason.TIMEOUT.value,
        TeamStopReason.CANCELLED.value,
    }:
        return "stopped"
    if stop_reason in {
        TeamStopReason.UNKNOWN_OUTCOME.value,
        TeamStopReason.INTERNAL_ERROR.value,
    }:
        return "failed"
    return "stopped" if stop_reason else "idle"


def _normalize_stop_reason(value: Any) -> str | None:
    text = _safe_text(value, limit=80)
    if text is None:
        return None
    prefix = "TeamStopReason."
    if text.startswith(prefix):
        return text.removeprefix(prefix).lower()
    return text


def _required_text(value: Any) -> str | None:
    text = _safe_text(value, limit=200)
    return text if text else None


def _safe_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] if text else None


def _safe_list_length(value: Any) -> int:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return 0
    return len(value)


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


__all__ = [
    "KNOWN_TEAM_EVENTS",
    "LiveTeamView",
    "TeamViewReducer",
    "TeamViewSnapshot",
    "TeamViewUpdate",
    "WorkerView",
    "project_coordinator_result",
]
