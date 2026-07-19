from __future__ import annotations

import socket
import threading
from pathlib import Path
from time import monotonic, sleep

import pytest

from paperclaw.executor import (
    ExecutionRequest,
    ExecutorStatus,
    GatewayPolicyError,
    HttpWorkerGatewayTransport,
    RemoteWorkerExecutor,
    SubprocessWorkerExecutor,
    WorkerGatewayService,
    create_worker_gateway_app,
)


@pytest.mark.process_acceptance
def test_real_http_remote_worker_roundtrip(tmp_path: Path) -> None:
    uvicorn = pytest.importorskip("uvicorn")
    port = _free_port()
    token = "real-http-test-token"
    gateway = WorkerGatewayService(
        SubprocessWorkerExecutor(allowed_entrypoints={"executor.echo.v1"}),
        allowed_workspace_roots=[tmp_path],
    )
    app = create_worker_gateway_app(gateway, bearer_token=token)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_for_server(server)
        transport = HttpWorkerGatewayTransport(
            f"http://127.0.0.1:{port}", bearer_token=token, timeout_seconds=5
        )
        executor = RemoteWorkerExecutor(transport, poll_seconds=0.02)
        request = ExecutionRequest(
            execution_id="real-http-exec",
            task_id="real-http-task",
            entrypoint="executor.echo.v1",
            payload={"message": "hello-remote"},
            workspace=str(tmp_path),
            timeout_seconds=10,
        )

        handle = executor.start(request)
        result = handle.wait(timeout=15)

        assert result is not None
        assert result.status is ExecutorStatus.SUCCEEDED
        assert result.output == {"echo": {"message": "hello-remote"}}

        # Exact same request reconciles to the same server-side execution.
        second = executor.start(request).wait(timeout=1)
        assert second == result

        wrong = HttpWorkerGatewayTransport(
            f"http://127.0.0.1:{port}", bearer_token="wrong-token"
        )
        with pytest.raises(GatewayPolicyError):
            RemoteWorkerExecutor(wrong).start(
                ExecutionRequest(
                    execution_id="unauthorized-exec",
                    task_id="unauthorized-task",
                    entrypoint="executor.echo.v1",
                    payload={},
                    workspace=str(tmp_path),
                    timeout_seconds=5,
                )
            )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        gateway.close()
        assert not thread.is_alive()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(server) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if server.started:
            return
        sleep(0.02)
    raise AssertionError("uvicorn worker gateway did not start")
