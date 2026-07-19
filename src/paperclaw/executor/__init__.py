"""Executor isolation boundary for local subprocess and remote workers."""

from .base import ExecutionHandle, WorkerExecutor
from .contracts import (
    ExecutionRequest,
    ExecutionResult,
    ExecutorStatus,
    TERMINAL_EXECUTOR_STATUSES,
)
from .gateway import (
    DirectWorkerGatewayTransport,
    GatewayCapacityError,
    GatewayConflictError,
    GatewayError,
    GatewayExecutionSnapshot,
    GatewayNotFoundError,
    GatewayPayloadTooLargeError,
    GatewayPolicyError,
    GatewayTransportError,
    RemoteExecutionHandle,
    RemoteWorkerExecutor,
    WorkerGatewayService,
    WorkerGatewayTransport,
)
from .http_gateway import HttpWorkerGatewayTransport, create_worker_gateway_app
from .subprocess import (
    DEFAULT_ALLOWED_ENTRYPOINTS,
    SubprocessExecutionHandle,
    SubprocessWorkerExecutor,
)

__all__ = [
    "DEFAULT_ALLOWED_ENTRYPOINTS",
    "DirectWorkerGatewayTransport",
    "ExecutionHandle",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutorStatus",
    "GatewayCapacityError",
    "GatewayConflictError",
    "GatewayError",
    "GatewayExecutionSnapshot",
    "GatewayNotFoundError",
    "GatewayPayloadTooLargeError",
    "GatewayPolicyError",
    "GatewayTransportError",
    "HttpWorkerGatewayTransport",
    "RemoteExecutionHandle",
    "RemoteWorkerExecutor",
    "SubprocessExecutionHandle",
    "SubprocessWorkerExecutor",
    "TERMINAL_EXECUTOR_STATUSES",
    "WorkerExecutor",
    "WorkerGatewayService",
    "WorkerGatewayTransport",
    "create_worker_gateway_app",
]
