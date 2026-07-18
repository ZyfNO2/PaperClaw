from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from paperclaw.service.fastapi_app import create_app
from paperclaw.tasks import (
    BackgroundTaskSupervisor,
    SQLiteDurableTaskStore,
    TaskApplicationService,
    TaskExecutionResult,
    TaskStatus,
)


class RunServiceStub:
    def __init__(self, task_service) -> None:
        self.task_service = task_service



def test_task_api_create_get_list_output_cancel_and_event_replay(tmp_path: Path) -> None:
    store = SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")

    def executor(task, should_cancel):
        return TaskExecutionResult(
            TaskStatus.SUCCEEDED,
            output={"summary": f"completed {task.task_id}"},
            model_calls=1,
            tool_calls=1,
        )

    supervisor = BackgroundTaskSupervisor(
        store,
        executor,
        max_concurrency=2,
        provider_concurrency=1,
        heartbeat_seconds=0.2,
        lease_seconds=2,
        poll_seconds=0.01,
    )
    task_service = TaskApplicationService(store, supervisor)
    client = TestClient(create_app(RunServiceStub(task_service)))
    try:
        response = client.post(
            "/v1/tasks",
            headers={"Idempotency-Key": "api-task-1"},
            json={
                "task_id": "api-task",
                "parent_run_id": "parent-run",
                "objective": "analyze API",
                "workspace": str(tmp_path),
                "allowed_paths": ["."],
                "allowed_tools": ["file_read"],
            },
        )
        assert response.status_code == 202
        assert response.json()["created"] is True
        terminal = supervisor.wait_for_terminal("api-task", timeout=5)
        assert terminal.status is TaskStatus.SUCCEEDED

        replay = client.post(
            "/v1/tasks",
            headers={"Idempotency-Key": "api-task-1"},
            json={
                "task_id": "api-task",
                "parent_run_id": "parent-run",
                "objective": "analyze API",
                "workspace": str(tmp_path),
                "allowed_paths": ["."],
                "allowed_tools": ["file_read"],
            },
        )
        assert replay.status_code == 202
        assert replay.json()["created"] is False

        assert client.get("/v1/tasks/api-task").json()["status"] == "succeeded"
        listed = client.get("/v1/runs/parent-run/tasks").json()
        assert [task["task_id"] for task in listed["tasks"]] == ["api-task"]
        output = client.get("/v1/tasks/api-task/output").json()
        assert output["output"]["summary"] == "completed api-task"

        events = task_service.events("api-task", after_sequence=1)
        assert events
        assert all(event.sequence > 1 for event in events)
        assert [event.sequence for event in events] == sorted(
            event.sequence for event in events
        )
    finally:
        task_service.shutdown()


def test_cancel_endpoint_changes_queued_task_without_running_it(tmp_path: Path) -> None:
    store = SQLiteDurableTaskStore(tmp_path / "tasks.sqlite3")
    supervisor = BackgroundTaskSupervisor(
        store,
        lambda task, should_cancel: TaskExecutionResult(TaskStatus.SUCCEEDED),
        max_concurrency=1,
        provider_concurrency=1,
        heartbeat_seconds=0.2,
        lease_seconds=2,
        poll_seconds=0.05,
    )
    task_service = TaskApplicationService(store, supervisor)
    client = TestClient(create_app(RunServiceStub(task_service)))
    try:
        store.create_task(
            __import__("paperclaw.tasks", fromlist=["TaskSpec"]).TaskSpec(
                task_id="queued",
                objective="queued",
                workspace=str(tmp_path),
            )
        )
        response = client.post("/v1/tasks/queued/cancel?reason=test")
        assert response.status_code == 202
        assert response.json()["status"] == "cancelled"
    finally:
        task_service.shutdown()
