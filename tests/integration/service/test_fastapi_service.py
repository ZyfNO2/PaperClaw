from __future__ import annotations

import time

from fastapi.testclient import TestClient

from paperclaw.harness import ExecutionReport, QueryEngine
from paperclaw.service import RunApplicationService
from paperclaw.service.fastapi_app import create_app


class ImmediateExecutor:
    def execute(self, request, *, emit, stop_token):
        emit("verification.completed", {"status": "passed"})
        return ExecutionReport(
            status="completed",
            output="api-ok",
            stop_reason="completed",
            model_calls=1,
            tool_calls=0,
        )


def build_service():
    executor = ImmediateExecutor()

    def factory(request, event_handler):
        return QueryEngine(
            executor,
            conversation_id=request.conversation_id or "api-test",
            event_handler=event_handler,
        )

    return RunApplicationService(factory)


def wait_api_terminal(client, run_id):
    for _ in range(100):
        payload = client.get(f"/v1/runs/{run_id}").json()
        if payload["terminal"]:
            return payload
        time.sleep(0.01)
    raise AssertionError("API run did not become terminal")


def test_fastapi_routes_idempotency_and_sse(tmp_path):
    service = build_service()
    client = TestClient(create_app(service))
    try:
        assert client.get("/health").json() == {"status": "ok"}
        body = {"task": "run", "workspace": str(tmp_path)}
        first = client.post(
            "/v1/runs", json=body, headers={"Idempotency-Key": "api-key-1"}
        )
        assert first.status_code == 202
        first_payload = first.json()
        assert first_payload["created"] is True
        run_id = first_payload["run"]["service_run_id"]

        duplicate = client.post(
            "/v1/runs", json=body, headers={"Idempotency-Key": "api-key-1"}
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["created"] is False
        assert duplicate.json()["run"]["service_run_id"] == run_id

        conflict = client.post(
            "/v1/runs",
            json={"task": "different", "workspace": str(tmp_path)},
            headers={"Idempotency-Key": "api-key-1"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "idempotency_conflict"

        terminal = wait_api_terminal(client, run_id)
        assert terminal["status"] == "completed"
        response = client.get(f"/v1/runs/{run_id}/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "event: run.completed" in response.text
        assert "id: " in response.text
    finally:
        service.shutdown()
