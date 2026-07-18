from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from paperclaw.executor import (
    ExecutionRequest,
    HttpWorkerGatewayTransport,
    SubprocessWorkerExecutor,
    WorkerGatewayService,
    create_worker_gateway_app,
)


def test_http_gateway_rejects_path_ambiguous_execution_id(tmp_path: Path) -> None:
    service = WorkerGatewayService(
        SubprocessWorkerExecutor(allowed_entrypoints={"executor.echo.v1"}),
        allowed_workspace_roots=[tmp_path],
    )
    client = TestClient(create_worker_gateway_app(service, bearer_token="token"))
    try:
        request = ExecutionRequest(
            execution_id="bad/id?segment",
            task_id="task",
            entrypoint="executor.echo.v1",
            payload={},
            workspace=str(tmp_path),
            timeout_seconds=5,
        )
        response = client.post(
            "/v1/executions",
            json=request.to_dict(),
            headers={"Authorization": "Bearer token"},
        )
        assert response.status_code == 422
    finally:
        service.close()


def test_http_client_rejects_path_ambiguous_execution_id_before_network(
    tmp_path: Path,
) -> None:
    transport = HttpWorkerGatewayTransport(
        "https://worker.example.test", bearer_token="token"
    )
    request = ExecutionRequest(
        execution_id="bad/id",
        task_id="task",
        entrypoint="executor.echo.v1",
        payload={},
        workspace=str(tmp_path),
        timeout_seconds=5,
    )
    with pytest.raises(ValueError, match="HTTP execution_id"):
        transport.submit(request)
