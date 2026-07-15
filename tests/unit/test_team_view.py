from __future__ import annotations

from typing import Any

from paperclaw.multiagent.contracts import (
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.coordinator import CoordinatorResult
from paperclaw.multiagent.team_view import (
    LiveTeamView,
    TeamViewReducer,
    project_coordinator_result,
)


def test_team_view_projects_worker_review_and_terminal_state() -> None:
    reducer = TeamViewReducer()

    assert reducer.apply(
        "team.started",
        _event(1, "team.started", task_count=2, user_goal="private goal"),
    ).accepted
    reducer.apply(
        "task.assigned",
        _event(
            2,
            "task.assigned",
            task_id="api",
            agent_id="worker-0",
            title="Implement API",
            objective="secret objective that must not be stored",
        ),
    )
    reducer.apply(
        "task.assigned",
        _event(
            3,
            "task.assigned",
            task_id="client",
            agent_id="worker-1",
            title="Implement client",
        ),
    )
    reducer.apply(
        "task.completed",
        _event(
            4,
            "task.completed",
            task_id="api",
            agent_id="worker-0",
            changed_files=["src/api.py", "tests/test_api.py"],
        ),
    )
    reducer.apply(
        "task.failed",
        _event(
            5,
            "task.failed",
            task_id="client",
            agent_id="worker-1",
            stop_reason="verification_failed",
            changed_files=["src/client.py"],
        ),
    )
    reducer.apply(
        "team.fix_round_started",
        _event(6, "team.fix_round_started", fix_round=1),
    )
    reducer.apply(
        "review.completed",
        _event(7, "review.completed", task_id="review", verdict="request_changes"),
    )
    terminal = reducer.apply(
        "team.stopped",
        _event(
            8,
            "team.stopped",
            stop_reason="TeamStopReason.BLOCKED",
            summary="raw summary is not projected",
        ),
    )

    snapshot = terminal.snapshot
    assert snapshot.run_id == "team-run"
    assert snapshot.status == "blocked"
    assert snapshot.stop_reason == "blocked"
    assert snapshot.task_count == 2
    assert snapshot.completed_count == 1
    assert snapshot.failed_count == 1
    assert snapshot.running_count == 0
    assert snapshot.fix_round == 1
    assert snapshot.review_verdict == "request_changes"
    assert snapshot.terminal is True
    assert snapshot.workers[0].task_id == "api"
    assert snapshot.workers[0].changed_file_count == 2
    assert snapshot.workers[1].reason == "verification_failed"
    assert not hasattr(snapshot, "user_goal")
    assert not hasattr(snapshot.workers[0], "changed_files")


def test_team_view_rejects_cross_run_stale_and_post_terminal_events() -> None:
    reducer = TeamViewReducer()
    reducer.apply("team.started", _event(1, "team.started"))

    stale = reducer.apply("task.progress", _event(1, "task.progress", task_id="a"))
    assert stale.accepted is False
    assert stale.rejection_reason == "stale or duplicate sequence"

    cross_run = reducer.apply(
        "task.progress",
        _event(2, "task.progress", run_id="other-run", task_id="a"),
    )
    assert cross_run.accepted is False
    assert cross_run.rejection_reason == "event belongs to another team run"

    reducer.apply(
        "team.stopped",
        _event(2, "team.stopped", stop_reason="all_tasks_completed"),
    )
    post_terminal = reducer.apply(
        "task.completed",
        _event(3, "task.completed", task_id="a"),
    )
    assert post_terminal.accepted is False
    assert post_terminal.rejection_reason == "event arrived after terminal state"


def test_global_verification_event_may_adjust_terminal_projection_once() -> None:
    reducer = TeamViewReducer()
    reducer.apply("team.started", _event(1, "team.started", task_count=1))
    reducer.apply(
        "team.stopped",
        _event(2, "team.stopped", stop_reason="all_tasks_completed"),
    )

    update = reducer.apply(
        "global_verification.completed",
        _event(
            3,
            "global_verification.completed",
            task_id="global-verify",
            agent_id="global-verifier",
            status="failed",
            effective_stop_reason="blocked",
        ),
    )

    assert update.accepted is True
    assert update.snapshot.status == "blocked"
    assert update.snapshot.stop_reason == "blocked"
    assert update.snapshot.global_verification_status == "failed"
    assert update.snapshot.last_sequence == 3

    duplicate = reducer.apply(
        "global_verification.completed",
        _event(
            4,
            "global_verification.completed",
            status="failed",
            effective_stop_reason="blocked",
        ),
    )
    assert duplicate.accepted is False
    assert duplicate.rejection_reason == "duplicate global verification event"


def test_unknown_event_advances_sequence_without_projecting_payload() -> None:
    reducer = TeamViewReducer()
    reducer.apply("team.started", _event(1, "team.started"))
    update = reducer.apply(
        "future.private_event",
        _event(
            2,
            "future.private_event",
            prompt="do not retain",
            reasoning="do not retain",
        ),
    )

    assert update.accepted is True
    assert update.known_event is False
    assert update.snapshot.last_sequence == 2
    assert not hasattr(update.snapshot, "prompt")
    assert not hasattr(update.snapshot, "reasoning")


def test_live_team_view_is_a_direct_coordinator_event_handler() -> None:
    view = LiveTeamView()
    view.handle_event("team.started", _event(1, "team.started", task_count=1))
    view.handle_event(
        "task.assigned",
        _event(
            2,
            "task.assigned",
            task_id="task-a",
            agent_id="worker-0",
            title="x" * 300,
        ),
    )

    snapshot = view.snapshot
    assert snapshot.status == "running"
    assert snapshot.running_count == 1
    assert len(snapshot.workers[0].title) == 120


def test_project_coordinator_result_reconciles_missing_terminal_event() -> None:
    result = CoordinatorResult(
        stop_reason=TeamStopReason.BUDGET_EXHAUSTED,
        task_results={
            "done": WorkerResult(
                task_id="done",
                status=WorkerStatus.COMPLETED,
                summary="done",
                changed_files=["a.py"],
            ),
            "cancelled": WorkerResult(
                task_id="cancelled",
                status=WorkerStatus.CANCELLED,
                summary="cancelled",
            ),
        },
        summary="budget exhausted",
        trace_events=[_event(1, "team.started", task_count=2)],
    )

    snapshot = project_coordinator_result(result)

    assert snapshot.status == "stopped"
    assert snapshot.stop_reason == "budget_exhausted"
    assert snapshot.completed_count == 1
    assert snapshot.cancelled_count == 1
    assert snapshot.terminal is True


def _event(
    sequence: int,
    event_type: str,
    *,
    run_id: str = "team-run",
    agent_id: str = "coordinator",
    task_id: str = "root",
    **payload: Any,
) -> dict[str, Any]:
    return {
        "event_id": f"evt-{sequence}",
        "event_type": event_type,
        "schema_version": "v1",
        "run_id": run_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "sequence": sequence,
        "payload": payload,
        "timestamp": "2026-07-16T00:00:00+00:00",
    }
