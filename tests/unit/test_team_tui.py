import asyncio
import threading

from paperclaw.multiagent.contracts import (
    AgentTask,
    TeamStopReason,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.coordinator import CoordinatorResult
from paperclaw.tui.team_app import TeamApp
from paperclaw.tui.team_widgets import TeamReview, TeamStatus, TeamTimeline, TeamWorkers


def _tasks() -> list[AgentTask]:
    return [
        AgentTask(
            task_id="task-a",
            title="Implement alpha",
            objective="secret objective alpha",
            acceptance_criteria=["alpha passes"],
        ),
        AgentTask(
            task_id="task-b",
            title="Implement beta",
            objective="secret objective beta",
            acceptance_criteria=["beta passes"],
        ),
    ]


class FakeCoordinator:
    def __init__(self, handler) -> None:
        self.handler = handler

    def run(self, goal, tasks):
        events = [
            (
                "team.started",
                {
                    "event_type": "team.started",
                    "run_id": "team-test",
                    "agent_id": "coordinator",
                    "task_id": "root",
                    "sequence": 1,
                    "payload": {"task_count": 2, "user_goal": "do not render goal"},
                },
            ),
            (
                "task.assigned",
                {
                    "event_type": "task.assigned",
                    "run_id": "team-test",
                    "agent_id": "worker-1",
                    "task_id": "task-a",
                    "sequence": 2,
                    "payload": {"title": "Implement alpha", "objective": "do not render"},
                },
            ),
            (
                "task.completed",
                {
                    "event_type": "task.completed",
                    "run_id": "team-test",
                    "agent_id": "worker-1",
                    "task_id": "task-a",
                    "sequence": 3,
                    "payload": {
                        "changed_files": ["src/private_name.py"],
                        "tool_output": "do not render output",
                    },
                },
            ),
            (
                "task.assigned",
                {
                    "event_type": "task.assigned",
                    "run_id": "team-test",
                    "agent_id": "worker-2",
                    "task_id": "task-b",
                    "sequence": 4,
                    "payload": {"title": "Implement beta"},
                },
            ),
            (
                "task.failed",
                {
                    "event_type": "task.failed",
                    "run_id": "team-test",
                    "agent_id": "worker-2",
                    "task_id": "task-b",
                    "sequence": 5,
                    "payload": {"reason": "verification_failed"},
                },
            ),
            (
                "review.completed",
                {
                    "event_type": "review.completed",
                    "run_id": "team-test",
                    "agent_id": "reviewer",
                    "task_id": "review",
                    "sequence": 6,
                    "payload": {"verdict": "request_changes", "reasoning": "hidden"},
                },
            ),
            (
                "team.stopped",
                {
                    "event_type": "team.stopped",
                    "run_id": "team-test",
                    "agent_id": "coordinator",
                    "task_id": "root",
                    "sequence": 7,
                    "payload": {"stop_reason": "blocked"},
                },
            ),
        ]
        for event_type, envelope in events:
            self.handler(event_type, envelope)
        return CoordinatorResult(
            stop_reason=TeamStopReason.BLOCKED,
            task_results={
                "task-a": WorkerResult("task-a", WorkerStatus.COMPLETED, "ok"),
                "task-b": WorkerResult("task-b", WorkerStatus.FAILED, "failed"),
            },
            trace_events=[envelope for _, envelope in events],
        )


class BlockingCoordinator:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.started = threading.Event()
        self.release = threading.Event()
        self.run_calls = 0

    def run(self, goal, tasks):
        self.run_calls += 1
        self.handler(
            "team.started",
            {
                "event_type": "team.started",
                "run_id": "team-blocking",
                "agent_id": "coordinator",
                "task_id": "root",
                "sequence": 1,
                "payload": {"task_count": len(tasks)},
            },
        )
        self.started.set()
        self.release.wait(timeout=2)
        self.handler(
            "team.stopped",
            {
                "event_type": "team.stopped",
                "run_id": "team-blocking",
                "agent_id": "coordinator",
                "task_id": "root",
                "sequence": 2,
                "payload": {"stop_reason": "cancelled"},
            },
        )
        return CoordinatorResult(stop_reason=TeamStopReason.CANCELLED)


def test_headless_team_dashboard_projects_sanitized_state() -> None:
    async def scenario() -> None:
        app = TeamApp(
            coordinator_factory=lambda handler: FakeCoordinator(handler),
            goal="sensitive project goal",
            tasks=_tasks(),
        )
        async with app.run_test(size=(70, 24)) as pilot:
            assert app.query_one(TeamStatus)
            assert app.query_one(TeamWorkers)
            assert app.query_one(TeamReview)
            assert app.query_one(TeamTimeline)
            assert app.query_one("#team-main").has_class("narrow")

            for _ in range(80):
                await pilot.pause()
                if app.snapshot.terminal and not app._run_in_flight:
                    break

            snapshot = app.snapshot
            assert snapshot.terminal is True
            assert snapshot.status == "blocked"
            assert snapshot.completed_count == 1
            assert snapshot.failed_count == 1
            assert snapshot.review_verdict == "request_changes"
            assert app.query_one(TeamWorkers).snapshot == snapshot

            timeline = "\n".join(app.query_one(TeamTimeline).entries)
            assert "src/private_name.py" not in timeline
            assert "do not render" not in timeline
            assert "sensitive project goal" not in timeline
            assert "hidden" not in timeline

    asyncio.run(scenario())


def test_duplicate_start_and_quit_are_rejected_while_active() -> None:
    async def scenario() -> None:
        coordinators = []

        def factory(handler):
            coordinator = BlockingCoordinator(handler)
            coordinators.append(coordinator)
            return coordinator

        app = TeamApp(coordinator_factory=factory, goal="goal", tasks=_tasks())
        async with app.run_test(size=(110, 28)) as pilot:
            for _ in range(30):
                await pilot.pause()
                if coordinators and coordinators[0].started.is_set():
                    break

            await pilot.press("r")
            await pilot.press("q")
            await pilot.pause()
            assert len(coordinators) == 1
            assert coordinators[0].run_calls == 1
            assert app._run_in_flight is True
            assert any(
                "duplicate start ignored" in entry
                for entry in app.query_one(TeamTimeline).entries
            )
            assert any(
                "Cannot quit while" in entry
                for entry in app.query_one(TeamTimeline).entries
            )

            coordinators[0].release.set()
            for _ in range(40):
                await pilot.pause()
                if not app._run_in_flight:
                    break
            assert app.snapshot.stop_reason == "cancelled"

    asyncio.run(scenario())
