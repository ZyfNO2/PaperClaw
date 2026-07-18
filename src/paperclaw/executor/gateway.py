"""Transport-neutral Remote Worker Gateway over v0.23 executor contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading
from time import monotonic, sleep, time
from typing import Any, Mapping, Protocol

from .base import ExecutionHandle, WorkerExecutor
from .contracts import ExecutionRequest, ExecutionResult, ExecutorStatus


class GatewayError(RuntimeError):
    code = "gateway_error"


class GatewayNotFoundError(GatewayError):
    code = "execution_not_found"


class GatewayConflictError(GatewayError):
    code = "execution_conflict"


class GatewayPolicyError(GatewayError):
    code = "gateway_policy_denied"


class GatewayPayloadTooLargeError(GatewayError):
    code = "gateway_payload_too_large"


class GatewayCapacityError(GatewayError):
    code = "gateway_capacity_exhausted"


class GatewayTransportError(GatewayError):
    code = "gateway_transport_error"

    def __init__(self, message: str, *, uncertain: bool = True) -> None:
        super().__init__(message)
        self.uncertain = uncertain


@dataclass(frozen=True)
class GatewayExecutionSnapshot:
    execution_id: str
    task_id: str
    request_digest: str
    state: str
    pid: int | None
    created_at: float
    updated_at: float
    result: ExecutionResult | None = None

    def __post_init__(self) -> None:
        if self.state not in {"running", "terminal"}:
            raise ValueError("gateway state must be running or terminal")
        if self.state == "running" and self.result is not None:
            raise ValueError("running gateway snapshot must not contain result")
        if self.state == "terminal" and self.result is None:
            raise ValueError("terminal gateway snapshot requires result")
        if (
            len(self.request_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.request_digest.lower())
        ):
            raise ValueError("request_digest must be sha256 hex")

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "request_digest": self.request_digest,
            "state": self.state,
            "pid": self.pid,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result.to_dict() if self.result is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GatewayExecutionSnapshot":
        raw_result = value.get("result")
        return cls(
            execution_id=str(value.get("execution_id") or ""),
            task_id=str(value.get("task_id") or ""),
            request_digest=str(value.get("request_digest") or ""),
            state=str(value.get("state") or ""),
            pid=value.get("pid") if isinstance(value.get("pid"), int) else None,
            created_at=float(value.get("created_at") or 0.0),
            updated_at=float(value.get("updated_at") or 0.0),
            result=(
                ExecutionResult.from_dict(raw_result)
                if isinstance(raw_result, Mapping)
                else None
            ),
        )


@dataclass
class _GatewayExecution:
    request_digest: str
    task_id: str
    handle: ExecutionHandle | None
    created_at: float
    updated_at: float
    result: ExecutionResult | None = None


class WorkerGatewayService:
    """Own active execution handles and expose idempotent submit/poll/cancel.

    Idempotency is guaranteed for the lifetime of this service process. Used
    execution IDs are never evicted and therefore can never be restarted within
    the same process. When capacity is exhausted, new IDs are rejected rather
    than deleting old idempotency tombstones. Durable idempotency across gateway
    restarts belongs to the external ownership/store layer introduced later.
    """

    def __init__(
        self,
        executor: WorkerExecutor,
        *,
        allowed_workspace_roots: list[str | Path] | tuple[str | Path, ...],
        max_request_bytes: int = 1_048_576,
        max_result_bytes: int = 4_194_304,
        max_execution_records: int = 10_000,
    ) -> None:
        roots = tuple(
            Path(root).expanduser().resolve(strict=True)
            for root in allowed_workspace_roots
        )
        if not roots or any(not root.is_dir() for root in roots):
            raise ValueError("allowed_workspace_roots must contain existing directories")
        if max_request_bytes < 1 or max_result_bytes < 1 or max_execution_records < 1:
            raise ValueError("gateway bounds must be positive")
        self._executor = executor
        self._roots = roots
        self._max_request_bytes = max_request_bytes
        self._max_result_bytes = max_result_bytes
        self._max_execution_records = max_execution_records
        self._executions: dict[str, _GatewayExecution] = {}
        self._lock = threading.RLock()

    def submit(self, request: ExecutionRequest) -> tuple[GatewayExecutionSnapshot, bool]:
        encoded = _canonical_request_bytes(request)
        if len(encoded) > self._max_request_bytes:
            raise GatewayPayloadTooLargeError("execution request exceeds gateway limit")
        self._validate_workspace(request.workspace)
        digest = hashlib.sha256(encoded).hexdigest()
        now = time()
        with self._lock:
            existing = self._executions.get(request.execution_id)
            if existing is not None:
                if existing.request_digest != digest:
                    raise GatewayConflictError(
                        "execution_id is already bound to another request"
                    )
                return self._snapshot_locked(request.execution_id, existing), False

            if len(self._executions) >= self._max_execution_records:
                raise GatewayCapacityError(
                    "gateway execution record capacity is exhausted"
                )

            handle = self._executor.start(request)
            record = _GatewayExecution(
                request_digest=digest,
                task_id=request.task_id,
                handle=handle,
                created_at=now,
                updated_at=now,
            )
            self._executions[request.execution_id] = record
            return self._snapshot_locked(request.execution_id, record), True

    def get(self, execution_id: str) -> GatewayExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._lock:
            record = self._executions.get(normalized)
            if record is None:
                raise GatewayNotFoundError("execution not found")
            return self._snapshot_locked(normalized, record)

    def cancel(
        self,
        execution_id: str,
        *,
        reason: str = "remote_cancel_requested",
    ) -> GatewayExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._lock:
            record = self._executions.get(normalized)
            if record is None:
                raise GatewayNotFoundError("execution not found")
            snapshot = self._snapshot_locked(normalized, record)
            if snapshot.state == "terminal":
                return snapshot
            assert record.handle is not None
            result = record.handle.cancel(reason)
            self._store_terminal_locked(record, result)
            return self._snapshot_locked(normalized, record)

    def close(self) -> None:
        with self._lock:
            for record in self._executions.values():
                if record.handle is not None:
                    record.handle.close()
                    record.handle = None

    def _snapshot_locked(
        self,
        execution_id: str,
        record: _GatewayExecution,
    ) -> GatewayExecutionSnapshot:
        if record.result is None and record.handle is not None:
            result = record.handle.poll()
            if result is not None:
                self._store_terminal_locked(record, result)
        state = "terminal" if record.result is not None else "running"
        pid = (
            record.result.pid
            if record.result is not None
            else (record.handle.pid if record.handle is not None else None)
        )
        return GatewayExecutionSnapshot(
            execution_id=execution_id,
            task_id=record.task_id,
            request_digest=record.request_digest,
            state=state,
            pid=pid,
            created_at=record.created_at,
            updated_at=record.updated_at,
            result=record.result,
        )

    def _store_terminal_locked(
        self,
        record: _GatewayExecution,
        result: ExecutionResult,
    ) -> None:
        bounded = self._bound_result(result)
        record.result = bounded
        record.updated_at = time()
        if record.handle is not None:
            record.handle.close()
            record.handle = None

    def _bound_result(self, result: ExecutionResult) -> ExecutionResult:
        encoded = json.dumps(
            result.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode("utf-8")
        if len(encoded) <= self._max_result_bytes:
            return result
        return ExecutionResult(
            execution_id=result.execution_id,
            task_id=result.task_id,
            status=ExecutorStatus.FAILED,
            error_code="gateway_result_too_large",
            error_type="ResultLimitExceeded",
            exit_code=result.exit_code,
            pid=result.pid,
            started_at=result.started_at,
            finished_at=result.finished_at or time(),
            termination_method=result.termination_method,
            metadata={"gateway_result_limit_bytes": self._max_result_bytes},
        )

    def _validate_workspace(self, workspace: str) -> None:
        path = Path(workspace).resolve(strict=True)
        if not any(path == root or path.is_relative_to(root) for root in self._roots):
            raise GatewayPolicyError("workspace is outside configured worker roots")


class WorkerGatewayTransport(Protocol):
    def submit(self, request: ExecutionRequest) -> GatewayExecutionSnapshot: ...

    def get(self, execution_id: str) -> GatewayExecutionSnapshot: ...

    def cancel(self, execution_id: str, reason: str) -> GatewayExecutionSnapshot: ...


class DirectWorkerGatewayTransport:
    """Test/local transport proving the gateway contract without HTTP coupling."""

    def __init__(self, service: WorkerGatewayService) -> None:
        self._service = service

    def submit(self, request: ExecutionRequest) -> GatewayExecutionSnapshot:
        return self._service.submit(request)[0]

    def get(self, execution_id: str) -> GatewayExecutionSnapshot:
        return self._service.get(execution_id)

    def cancel(self, execution_id: str, reason: str) -> GatewayExecutionSnapshot:
        return self._service.cancel(execution_id, reason=reason)


class RemoteWorkerExecutor:
    """WorkerExecutor implementation backed by a remote gateway transport."""

    def __init__(
        self,
        transport: WorkerGatewayTransport,
        *,
        poll_seconds: float = 0.05,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self._transport = transport
        self._poll_seconds = poll_seconds

    def start(self, request: ExecutionRequest) -> "RemoteExecutionHandle":
        try:
            snapshot = self._transport.submit(request)
        except GatewayTransportError:
            # The caller may safely retry the exact same ExecutionRequest because
            # execution_id submit is idempotent. We must not synthesize failure.
            raise
        return RemoteExecutionHandle(
            request, self._transport, snapshot, self._poll_seconds
        )


class RemoteExecutionHandle:
    def __init__(
        self,
        request: ExecutionRequest,
        transport: WorkerGatewayTransport,
        initial: GatewayExecutionSnapshot,
        poll_seconds: float,
    ) -> None:
        if (
            initial.execution_id != request.execution_id
            or initial.task_id != request.task_id
        ):
            raise GatewayTransportError(
                "gateway returned mismatched execution identity"
            )
        self.request = request
        self._transport = transport
        self._snapshot = initial
        self._poll_seconds = poll_seconds
        self._closed = False

    @property
    def execution_id(self) -> str:
        return self.request.execution_id

    @property
    def pid(self) -> int | None:
        return self._snapshot.pid

    def poll(self) -> ExecutionResult | None:
        if self._snapshot.state == "terminal":
            return self._snapshot.result
        self._snapshot = self._transport.get(self.execution_id)
        return self._snapshot.result if self._snapshot.state == "terminal" else None

    def wait(self, timeout: float | None = None) -> ExecutionResult | None:
        deadline = None if timeout is None else monotonic() + max(0.0, timeout)
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and monotonic() >= deadline:
                return None
            sleep(self._poll_seconds)

    def cancel(self, reason: str = "cancel_requested") -> ExecutionResult:
        if self._snapshot.state == "terminal":
            assert self._snapshot.result is not None
            return self._snapshot.result
        try:
            self._snapshot = self._transport.cancel(self.execution_id, reason)
        except GatewayTransportError:
            return ExecutionResult(
                execution_id=self.request.execution_id,
                task_id=self.request.task_id,
                status=ExecutorStatus.UNKNOWN_OUTCOME,
                error_code="remote_cancel_uncertain",
                error_type="GatewayTransportError",
                finished_at=time(),
                metadata={"reconciliation_required": True},
            )
        if self._snapshot.state != "terminal" or self._snapshot.result is None:
            return ExecutionResult(
                execution_id=self.request.execution_id,
                task_id=self.request.task_id,
                status=ExecutorStatus.UNKNOWN_OUTCOME,
                error_code="remote_cancel_unconfirmed",
                error_type="GatewayProtocolError",
                finished_at=time(),
                metadata={"reconciliation_required": True},
            )
        return self._snapshot.result

    def close(self) -> None:
        # Closing a client handle is not remote cancellation.
        self._closed = True


def _canonical_request_bytes(request: ExecutionRequest) -> bytes:
    return json.dumps(
        request.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _execution_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("execution_id must be a bounded non-empty string")
    return value.strip()


__all__ = [
    "DirectWorkerGatewayTransport",
    "GatewayCapacityError",
    "GatewayConflictError",
    "GatewayError",
    "GatewayExecutionSnapshot",
    "GatewayNotFoundError",
    "GatewayPayloadTooLargeError",
    "GatewayPolicyError",
    "GatewayTransportError",
    "RemoteExecutionHandle",
    "RemoteWorkerExecutor",
    "WorkerGatewayService",
    "WorkerGatewayTransport",
]
