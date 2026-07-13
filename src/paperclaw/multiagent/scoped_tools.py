"""Tool wrappers that enforce task scope, lease ownership, and CAS safety.

Each Worker gets its own scoped registry. The wrappers sit in front of the real
v0.01/v0.02 tools so the existing AgentRuntime and Verify engine keep working
without modification.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from paperclaw.agent.verification import VerificationResult
from paperclaw.multiagent.contracts import (
    AgentTask,
    LeaseDecision,
    PermissionDecision,
    WorkerResult,
    WorkerStatus,
)
from paperclaw.multiagent.events import emit_team_event
from paperclaw.multiagent.lease import LeaseManager
from paperclaw.multiagent.permissions import PermissionGuardLite
from paperclaw.tools import BashTool, FileEditTool, FileReadTool, FileWriteTool, GrepTool
from paperclaw.tools.base import ToolContext, ToolResult
from paperclaw.tools.registry import ToolRegistry


@dataclass
class WorkerRuntimeCounters:
    """Mutable counters tracked while a Worker runs a task."""

    step_count: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0


def _content_hash(path: Path) -> str:
    """Stable sha256 of file bytes for compare-and-swap."""

    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class FileSnapshot:
    """Immutable snapshot of a file at a point in time.

    Used to support compare-and-swap and safe re-read after an external
    modification is detected. The snapshot is captured lazily: callers must
    explicitly re-read after a conflict rather than relying on a stale object.
    """

    path: str
    content_hash: str
    content: str

    @classmethod
    def read(cls, path: Path) -> "FileSnapshot":
        if not path.is_file():
            return cls(path=str(path.resolve()), content_hash="", content="")
        content = path.read_text(encoding="utf-8", errors="strict")
        return cls(path=str(path.resolve()), content_hash=_content_hash(path), content=content)


def _deny_result(reason: str, error_code: str = "scope_violation", metadata: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(False, reason, error_code, metadata or {})


def _team_state(runtime_state: dict) -> dict:
    """Return the shared team state for event emission.

    Scoped tools run inside a Worker's runtime_state, but team-level events must
    be recorded in the Coordinator-owned team_state so traces are complete across
    all Workers. The Worker injects the team reference under `_team_state`; unit
    tests that use a bare runtime_state fall back to it.
    """

    return runtime_state.get("_team_state", runtime_state)


def _idempotency_key(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Build a stable cache key from an explicit idempotency_key argument."""

    key = arguments.get("idempotency_key")
    if not isinstance(key, str) or not key:
        return None
    return f"{tool_name}:{key}"


def _idempotent_execute(
    tool_name: str,
    arguments: dict[str, Any],
    runtime_state: dict,
    executor: Callable[[], ToolResult],
) -> ToolResult:
    """Wrap a scoped tool execution with a per-Worker idempotency ledger.

    If the same tool is called again with the same idempotency_key, the cached
    result is returned without re-running side effects. The ledger is stored in
    the Worker's runtime_state so it does not leak across tasks or Agents.
    """

    cache_key = _idempotency_key(tool_name, arguments)
    if cache_key is None:
        return executor()

    ledger = runtime_state.setdefault("idempotency_ledger", {})
    record = ledger.get(cache_key)
    if record is not None:
        record["attempt"] += 1
        return ToolResult(
            record["result"].ok,
            record["result"].output,
            record["result"].error_code,
            {**record["result"].metadata, "idempotency": "hit", "attempt": record["attempt"]},
        )

    result = executor()
    ledger[cache_key] = {"result": result, "attempt": 1}
    return ToolResult(
        result.ok,
        result.output,
        result.error_code,
        {**result.metadata, "idempotency": "miss", "attempt": 1},
    )


class ScopedFileReadTool:
    name = "file_read"
    description = FileReadTool().description

    def __init__(
        self,
        task: AgentTask,
        guard: PermissionGuardLite,
        agent_id: str,
        runtime_state: dict,
        counters: WorkerRuntimeCounters,
    ) -> None:
        self._task = task
        self._guard = guard
        self._agent_id = agent_id
        self._runtime_state = runtime_state
        self._counters = counters
        self._inner = FileReadTool()

    def validate(self, arguments: dict[str, Any]) -> None:
        self._inner.validate(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return _idempotent_execute(
            self.name,
            arguments,
            self._runtime_state,
            lambda: self._execute_impl(arguments, context),
        )

    def _execute_impl(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        check = self._guard.check(
            self.name,
            arguments,
            self._task.allowed_paths,
            self._task.writable_paths,
            self._task.allowed_tools,
        )
        if check.decision == PermissionDecision.DENY:
            emit_team_event(
                _team_state(self._runtime_state),
                "tool.scope_violation",
                self._agent_id,
                self._task.task_id,
                tool=self.name,
                reason=check.reason,
            )
            return _deny_result(check.reason)
        self._counters.tool_call_count += 1
        return self._inner.execute(arguments, context)


class ScopedGrepTool:
    name = "grep"
    description = GrepTool().description

    def __init__(
        self,
        task: AgentTask,
        guard: PermissionGuardLite,
        agent_id: str,
        runtime_state: dict,
        counters: WorkerRuntimeCounters,
    ) -> None:
        self._task = task
        self._guard = guard
        self._agent_id = agent_id
        self._runtime_state = runtime_state
        self._counters = counters
        self._inner = GrepTool()

    def validate(self, arguments: dict[str, Any]) -> None:
        self._inner.validate(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return _idempotent_execute(
            self.name,
            arguments,
            self._runtime_state,
            lambda: self._execute_impl(arguments, context),
        )

    def _execute_impl(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        check = self._guard.check(
            self.name,
            arguments,
            self._task.allowed_paths,
            self._task.writable_paths,
            self._task.allowed_tools,
        )
        if check.decision == PermissionDecision.DENY:
            emit_team_event(
                _team_state(self._runtime_state),
                "tool.scope_violation",
                self._agent_id,
                self._task.task_id,
                tool=self.name,
                reason=check.reason,
            )
            return _deny_result(check.reason)
        self._counters.tool_call_count += 1
        return self._inner.execute(arguments, context)


class ScopedFileWriteTool:
    name = "file_write"
    description = FileWriteTool().description

    def __init__(
        self,
        task: AgentTask,
        guard: PermissionGuardLite,
        lease_manager: LeaseManager,
        agent_id: str,
        runtime_state: dict,
        counters: WorkerRuntimeCounters,
    ) -> None:
        self._task = task
        self._guard = guard
        self._lease_manager = lease_manager
        self._agent_id = agent_id
        self._runtime_state = runtime_state
        self._counters = counters
        self._inner = FileWriteTool()

    def validate(self, arguments: dict[str, Any]) -> None:
        self._inner.validate(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return _idempotent_execute(
            self.name,
            arguments,
            self._runtime_state,
            lambda: self._execute_impl(arguments, context),
        )

    def _execute_impl(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = arguments.get("path")
        check = self._guard.check(
            self.name,
            arguments,
            self._task.allowed_paths,
            self._task.writable_paths,
            self._task.allowed_tools,
        )
        if check.decision == PermissionDecision.DENY:
            emit_team_event(
                _team_state(self._runtime_state),
                "tool.scope_violation",
                self._agent_id,
                self._task.task_id,
                tool=self.name,
                reason=check.reason,
            )
            return _deny_result(check.reason)

        lease_result = self._lease_manager.acquire(
            path,
            self._agent_id,
            self._task.task_id,
        )
        if lease_result.decision not in {LeaseDecision.GRANTED, LeaseDecision.ALREADY_OWNS}:
            emit_team_event(
                _team_state(self._runtime_state),
                "tool.lease_conflict",
                self._agent_id,
                self._task.task_id,
                tool=self.name,
                reason=lease_result.reason,
            )
            return _deny_result(lease_result.reason, "lease_conflict")

        # TOCTOU revalidation: the symlink/junction target could have changed
        # between the permission check and the lease acquisition.
        if self._guard._resolve_path(path) is None:
            self._lease_manager.release(path, self._task.task_id)
            return _deny_result(
                f"path escapes workspace after lease acquire: {path}",
                "scope_violation",
            )

        resolved = (context.workspace / path).resolve()
        expected_hash = arguments.get("expected_hash")
        if expected_hash is not None:
            actual = _content_hash(resolved)
            if actual != expected_hash:
                snapshot = FileSnapshot.read(resolved)
                emit_team_event(
                    _team_state(self._runtime_state),
                    "tool.cas_conflict",
                    self._agent_id,
                    self._task.task_id,
                    path=path,
                    expected=expected_hash,
                    actual=actual,
                    snapshot_path=snapshot.path,
                    snapshot_hash=snapshot.content_hash,
                )
                return _deny_result(
                    f"expected_hash mismatch for {path}; file was modified externally",
                    "cas_conflict",
                    {
                        "path": str(resolved),
                        "expected": expected_hash,
                        "actual": actual,
                        "snapshot": {"path": snapshot.path, "content_hash": snapshot.content_hash},
                    },
                )

        # Atomic replace: write to a temp file in the same directory, then rename.
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=resolved.parent,
                prefix=f".{resolved.name}.",
                delete=False,
            ) as tmp:
                tmp.write(arguments["content"])
                tmp_path = Path(tmp.name)
            os.replace(str(tmp_path), str(resolved))
        except OSError as exc:
            return _deny_result(f"atomic write failed: {exc}", "internal_error")

        self._counters.tool_call_count += 1
        return ToolResult(
            True,
            f"wrote {len(arguments['content'])} characters to {resolved.name}",
            metadata={"path": str(resolved), "atomic": True},
        )


class ScopedFileEditTool:
    name = "file_edit"
    description = FileEditTool().description

    def __init__(
        self,
        task: AgentTask,
        guard: PermissionGuardLite,
        lease_manager: LeaseManager,
        agent_id: str,
        runtime_state: dict,
        counters: WorkerRuntimeCounters,
    ) -> None:
        self._task = task
        self._guard = guard
        self._lease_manager = lease_manager
        self._agent_id = agent_id
        self._runtime_state = runtime_state
        self._counters = counters
        self._inner = FileEditTool()

    def validate(self, arguments: dict[str, Any]) -> None:
        self._inner.validate(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return _idempotent_execute(
            self.name,
            arguments,
            self._runtime_state,
            lambda: self._execute_impl(arguments, context),
        )

    def _execute_impl(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = arguments.get("path")
        check = self._guard.check(
            self.name,
            arguments,
            self._task.allowed_paths,
            self._task.writable_paths,
            self._task.allowed_tools,
        )
        if check.decision == PermissionDecision.DENY:
            emit_team_event(
                _team_state(self._runtime_state),
                "tool.scope_violation",
                self._agent_id,
                self._task.task_id,
                tool=self.name,
                reason=check.reason,
            )
            return _deny_result(check.reason)

        lease_result = self._lease_manager.acquire(
            path,
            self._agent_id,
            self._task.task_id,
        )
        if lease_result.decision not in {LeaseDecision.GRANTED, LeaseDecision.ALREADY_OWNS}:
            emit_team_event(
                _team_state(self._runtime_state),
                "tool.lease_conflict",
                self._agent_id,
                self._task.task_id,
                tool=self.name,
                reason=lease_result.reason,
            )
            return _deny_result(lease_result.reason, "lease_conflict")

        # TOCTOU revalidation: the symlink/junction target could have changed
        # between the permission check and the lease acquisition.
        if self._guard._resolve_path(path) is None:
            self._lease_manager.release(path, self._task.task_id)
            return _deny_result(
                f"path escapes workspace after lease acquire: {path}",
                "scope_violation",
            )

        resolved = (context.workspace / path).resolve()
        expected_hash = arguments.get("expected_hash")
        if expected_hash is not None:
            actual = _content_hash(resolved)
            if actual != expected_hash:
                snapshot = FileSnapshot.read(resolved)
                emit_team_event(
                    _team_state(self._runtime_state),
                    "tool.cas_conflict",
                    self._agent_id,
                    self._task.task_id,
                    path=path,
                    expected=expected_hash,
                    actual=actual,
                    snapshot_path=snapshot.path,
                    snapshot_hash=snapshot.content_hash,
                )
                return _deny_result(
                    f"expected_hash mismatch for {path}; file was modified externally",
                    "cas_conflict",
                    {
                        "path": str(resolved),
                        "expected": expected_hash,
                        "actual": actual,
                        "snapshot": {"path": snapshot.path, "content_hash": snapshot.content_hash},
                    },
                )

        # Read, replace exactly once, atomic write.
        if not resolved.is_file():
            return _deny_result(f"path is not a file: {path}", "not_found")
        text = resolved.read_text(encoding="utf-8", errors="strict")
        count = text.count(arguments["old_text"])
        if count != 1:
            return _deny_result(
                f"old_text must occur exactly once; found {count}",
                "conflict",
                {"matches": count},
            )
        new_text = text.replace(arguments["old_text"], arguments["new_text"], 1)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=resolved.parent,
                prefix=f".{resolved.name}.",
                delete=False,
            ) as tmp:
                tmp.write(new_text)
                tmp_path = Path(tmp.name)
            os.replace(str(tmp_path), str(resolved))
        except OSError as exc:
            return _deny_result(f"atomic edit failed: {exc}", "internal_error")

        self._counters.tool_call_count += 1
        return ToolResult(
            True,
            f"edited {resolved.name}",
            metadata={"path": str(resolved), "replacements": 1, "atomic": True},
        )


class ScopedBashTool:
    name = "bash"
    description = BashTool().description

    def __init__(
        self,
        task: AgentTask,
        guard: PermissionGuardLite,
        agent_id: str,
        runtime_state: dict,
        counters: WorkerRuntimeCounters,
    ) -> None:
        self._task = task
        self._guard = guard
        self._agent_id = agent_id
        self._runtime_state = runtime_state
        self._counters = counters
        self._inner = BashTool()

    def validate(self, arguments: dict[str, Any]) -> None:
        self._inner.validate(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return _idempotent_execute(
            self.name,
            arguments,
            self._runtime_state,
            lambda: self._execute_impl(arguments, context),
        )

    def _execute_impl(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        check = self._guard.check(
            self.name,
            arguments,
            self._task.allowed_paths,
            self._task.writable_paths,
            self._task.allowed_tools,
        )
        if check.decision == PermissionDecision.DENY:
            emit_team_event(
                _team_state(self._runtime_state),
                "tool.scope_violation",
                self._agent_id,
                self._task.task_id,
                tool=self.name,
                reason=check.reason,
            )
            return _deny_result(check.reason)
        self._counters.tool_call_count += 1
        return self._inner.execute(arguments, context)


def build_scoped_registry(
    task: AgentTask,
    guard: PermissionGuardLite,
    lease_manager: LeaseManager,
    agent_id: str,
    runtime_state: dict,
    counters: WorkerRuntimeCounters,
) -> ToolRegistry:
    """Build a ToolRegistry whose tools respect task scope and workspace leases."""

    return ToolRegistry(
        [
            ScopedFileReadTool(task, guard, agent_id, runtime_state, counters),
            ScopedFileWriteTool(task, guard, lease_manager, agent_id, runtime_state, counters),
            ScopedFileEditTool(task, guard, lease_manager, agent_id, runtime_state, counters),
            ScopedGrepTool(task, guard, agent_id, runtime_state, counters),
            ScopedBashTool(task, guard, agent_id, runtime_state, counters),
        ]
    )
