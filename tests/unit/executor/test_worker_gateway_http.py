from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from paperclaw.executor import (
    ExecutionRequest,
    GatewayExecutionSnapshot,
    HttpWorkerGatewayTransport,
    SubprocessWorkerExecutor,
    WorkerGatewayService,
    create_worker_gateway_app,
)


TOKEN = "test-gateway-token"


def _request(workspace: Path, *, value: int = 1) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id="http-exec-1",
        task_id="task-http",
        entrypoint="executor.echo.v1",
        payload={"value": value},
        workspace=str(workspace),
        timeout_seconds=5,
    )


def _client(tmp_path: Path) -> tuple[TestClient, WorkerGatewayService]:
    service = WorkerGatewayService(
        SubprocessWorkerExecutor(allowed_entrypoints={"executor.echo.v1"}),
        allowed_workspace_roots=[tmp_path],
    )
    return TestClient(create_worker_gateway_app(service, bearer_token=TOKEN)), service


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_is_public_but_execution_endpoints_require_auth(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    try:
        assert client.get("/health").status_code == 200
        response = client.post("/v1/executions", json=_request(tmp_path).to_dict())
        assert response.status_code == 401
        response = client.post(
            "/v1/executions",
            json=_request(tmp_path).to_dict(),
            headers={"Authorization": "Bearer wrong"},
        )
        assert response.status_code == 401
    finally:
        service.close()


def test_http_submit_is_idempotent_and_conflict_is_409(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    try:
        request = _request(tmp_path)
        first = client.post("/v1/executions", json=request.to_dict(), headers=_auth())
        assert first.status_code == 202
        assert first.json()["created"] is True

        second = client.post("/v1/executions", json=request.to_dict(), headers=_auth())
        assert second.status_code == 202
        assert second.json()["created"] is False

        conflicting = _request(tmp_path, value=2)
        response = client.post(
            "/v1/executions", json=conflicting.to_dict(), headers=_auth()
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "execution_conflict"
    finally:
        service.close()


def test_http_workspace_policy_is_enforced_on_worker_host(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    service = WorkerGatewayService(
        SubprocessWorkerExecutor(allowed_entrypoints={"executor.echo.v1"}),
        allowed_workspace_roots=[allowed],
    )
    client = TestClient(create_worker_gateway_app(service, bearer_token=TOKEN))
    try:
        response = client.post(
            "/v1/executions", json=_request(outside).to_dict(), headers=_auth()
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "gateway_policy_denied"
    finally:
        service.close()


def test_http_get_returns_terminal_execution(tmp_path: Path) -> None:
    client, service = _client(tmp_path)
    try:
        request = _request(tmp_path)
        response = client.post(
            "/v1/executions", json=request.to_dict(), headers=_auth()
        )
        assert response.status_code == 202
        for _ in range(100):
            response = client.get(
                f"/v1/executions/{request.execution_id}", headers=_auth()
            )
            assert response.status_code == 200
            if response.json()["state"] == "terminal":
                break
        payload = response.json()
        assert payload["state"] == "terminal"
        assert payload["result"]["status"] == "succeeded"
    finally:
        service.close()


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload


def test_stdlib_http_transport_keeps_bearer_token_out_of_request_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    snapshot = GatewayExecutionSnapshot(
        execution_id=request.execution_id,
        task_id=request.task_id,
        request_digest="a" * 64,
        state="running",
        pid=123,
        created_at=1.0,
        updated_at=1.0,
    )
    observed: dict[str, Any] = {}

    def fake_urlopen(http_request, timeout):
        observed["authorization"] = http_request.get_header("Authorization")
        observed["body"] = http_request.data
        observed["timeout"] = timeout
        return _FakeResponse({"created": True, "execution": snapshot.to_dict()})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    transport = HttpWorkerGatewayTransport(
        "https://worker.example.test", bearer_token=TOKEN, timeout_seconds=3
    )

    returned = transport.submit(request)

    assert returned == snapshot
    assert observed["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN.encode() not in observed["body"]
    assert observed["timeout"] == 3
