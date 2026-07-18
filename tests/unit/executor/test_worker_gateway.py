from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.executor import (
    DirectWorkerGatewayTransport,
    ExecutionRequest,
    ExecutorStatus,
    GatewayCapacityError,
    GatewayConflictError,
    GatewayPayloadTooLargeError,
    GatewayPolicyError,
    GatewayTransportError,
    RemoteWorkerExecutor,
    SubprocessWorkerExecutor,
    WorkerGatewayService,
)


DIAGNOSTICS = {
    "executor.echo.v1",
    "executor.sleep.v1",
    "executor.crash.v1",
}


def _request(
    workspace: Path,
    *,
    execution_id: str = "exec-1",
    entrypoint: str = "executor.echo.v1",
    payload: dict | None = None,
    timeout: float = 5.0,
) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=execution_id,
        task_id="task-1",
        entrypoint=entrypoint,
        payload=payload or {},
        workspace=str(workspace),
        timeout_seconds=timeout,
    )


def _service(root: Path, **kwargs) -> WorkerGatewayService:
    return WorkerGatewayService(
        SubprocessWorkerExecutor(
            allowed_entrypoints=DIAGNOSTICS,
            terminate_grace_seconds=0.2,
            kill_grace_seconds=1.5,
        ),
        allowed_workspace_roots=[root],
        **kwargs,
    )


def test_same_execution_id_same_request_is_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        request = _request(tmp_path, payload={"value": 7})
        first, created = service.submit(request)
        second, created_again = service.submit(request)

        assert created is True
        assert created_again is False
        assert second.execution_id == first.execution_id
        assert second.request_digest == first.request_digest

        result = RemoteWorkerExecutor(DirectWorkerGatewayTransport(service)).start(request).wait(10)
        assert result is not None
        assert result.status is ExecutorStatus.SUCCEEDED
        assert result.output == {"echo": {"value": 7}}
    finally:
        service.close()


def test_same_execution_id_different_request_conflicts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        service.submit(_request(tmp_path, payload={"value": 1}))
        with pytest.raises(GatewayConflictError):
            service.submit(_request(tmp_path, payload={"value": 2}))
    finally:
        service.close()


def test_capacity_rejects_new_ids_without_forgetting_used_id(tmp_path: Path) -> None:
    service = _service(tmp_path, max_execution_records=1)
    try:
        request = _request(tmp_path, execution_id="stable-id", payload={"value": 1})
        handle = RemoteWorkerExecutor(DirectWorkerGatewayTransport(service)).start(request)
        result = handle.wait(10)
        assert result is not None
        assert result.status is ExecutorStatus.SUCCEEDED

        snapshot, created = service.submit(request)
        assert created is False
        assert snapshot.state == "terminal"
        assert snapshot.result == result

        with pytest.raises(GatewayCapacityError):
            service.submit(
                _request(tmp_path, execution_id="new-id", payload={"value": 2})
            )

        # Capacity pressure must not turn an old execution ID back into a fresh run.
        again, created_again = service.submit(request)
        assert created_again is False
        assert again.result == result
    finally:
        service.close()


def test_workspace_must_be_inside_configured_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    service = _service(allowed)
    try:
        with pytest.raises(GatewayPolicyError):
            service.submit(_request(outside))
    finally:
        service.close()


def test_request_size_is_bounded_before_execution(tmp_path: Path) -> None:
    service = _service(tmp_path, max_request_bytes=200)
    try:
        with pytest.raises(GatewayPayloadTooLargeError):
            service.submit(_request(tmp_path, payload={"blob": "x" * 500}))
    finally:
        service.close()


def test_oversize_terminal_result_fails_closed(tmp_path: Path) -> None:
    service = _service(tmp_path, max_request_bytes=10_000, max_result_bytes=220)
    try:
        request = _request(tmp_path, payload={"blob": "x" * 1_000})
        handle = RemoteWorkerExecutor(DirectWorkerGatewayTransport(service)).start(request)
        result = handle.wait(10)
        assert result is not None
        assert result.status is ExecutorStatus.FAILED
        assert result.error_code == "gateway_result_too_large"
        assert result.output is None
    finally:
        service.close()


def test_remote_cancel_proves_terminal_through_gateway(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        request = _request(
            tmp_path,
            entrypoint="executor.sleep.v1",
            payload={"seconds": 10},
            timeout=30,
        )
        handle = RemoteWorkerExecutor(DirectWorkerGatewayTransport(service)).start(request)
        result = handle.cancel("test_cancel")
        assert result.status in {ExecutorStatus.CANCELLED, ExecutorStatus.UNKNOWN_OUTCOME}
        snapshot = service.get(request.execution_id)
        assert snapshot.state == "terminal"
        assert snapshot.result == result
    finally:
        service.close()


class _CancelUncertainTransport:
    def submit(self, request: ExecutionRequest):
        from paperclaw.executor.gateway import GatewayExecutionSnapshot

        return GatewayExecutionSnapshot(
            execution_id=request.execution_id,
            task_id=request.task_id,
            request_digest="0" * 64,
            state="running",
            pid=123,
            created_at=1.0,
            updated_at=1.0,
        )

    def get(self, execution_id: str):
        del execution_id
        raise GatewayTransportError("network unavailable")

    def cancel(self, execution_id: str, reason: str):
        del execution_id, reason
        raise GatewayTransportError("cancel response lost")


def test_remote_cancel_transport_uncertainty_never_claims_cancelled(tmp_path: Path) -> None:
    request = _request(tmp_path)
    handle = RemoteWorkerExecutor(_CancelUncertainTransport()).start(request)  # type: ignore[arg-type]

    result = handle.cancel("user_requested")

    assert result.status is ExecutorStatus.UNKNOWN_OUTCOME
    assert result.error_code == "remote_cancel_uncertain"
    assert result.metadata["reconciliation_required"] is True


def test_remote_poll_transport_error_is_not_business_failure(tmp_path: Path) -> None:
    request = _request(tmp_path)
    handle = RemoteWorkerExecutor(_CancelUncertainTransport()).start(request)  # type: ignore[arg-type]

    with pytest.raises(GatewayTransportError):
        handle.poll()
