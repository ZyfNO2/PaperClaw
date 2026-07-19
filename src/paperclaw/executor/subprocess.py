"""Local subprocess executor with bounded process-tree termination semantics."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from time import monotonic, sleep, time
from typing import Iterable

from .base import ExecutionHandle
from .contracts import ExecutionRequest, ExecutionResult, ExecutorStatus


DEFAULT_ALLOWED_ENTRYPOINTS = frozenset({"tasks.subagent.env.v1"})


class SubprocessWorkerExecutor:
    """Launch one allowlisted execution in a fresh Python process.

    The transport is intentionally JSON-file based rather than pickle based. The
    same request/result contracts can later be carried by a Remote Worker Gateway.
    """

    def __init__(
        self,
        *,
        allowed_entrypoints: Iterable[str] = DEFAULT_ALLOWED_ENTRYPOINTS,
        terminate_grace_seconds: float = 1.0,
        kill_grace_seconds: float = 2.0,
    ) -> None:
        allowed = frozenset(item.strip() for item in allowed_entrypoints if item.strip())
        if not allowed:
            raise ValueError("allowed_entrypoints must not be empty")
        if terminate_grace_seconds < 0 or kill_grace_seconds <= 0:
            raise ValueError("termination grace values must be non-negative")
        self.allowed_entrypoints = allowed
        self.terminate_grace_seconds = terminate_grace_seconds
        self.kill_grace_seconds = kill_grace_seconds

    def start(self, request: ExecutionRequest) -> "SubprocessExecutionHandle":
        if request.entrypoint not in self.allowed_entrypoints:
            raise ValueError(f"entrypoint is not allowlisted: {request.entrypoint}")

        temp_dir = Path(tempfile.mkdtemp(prefix="paperclaw-exec-"))
        request_path = temp_dir / "request.json"
        result_path = temp_dir / "result.json"
        request_path.write_text(
            json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-m",
            "paperclaw.executor.child_host",
            str(request_path),
            str(result_path),
        ]
        kwargs: dict[str, object] = {
            "cwd": request.workspace,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": os.environ.copy(),
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        return SubprocessExecutionHandle(
            request,
            process,
            temp_dir=temp_dir,
            result_path=result_path,
            terminate_grace_seconds=self.terminate_grace_seconds,
            kill_grace_seconds=self.kill_grace_seconds,
        )


class SubprocessExecutionHandle(ExecutionHandle):
    def __init__(
        self,
        request: ExecutionRequest,
        process: subprocess.Popen[bytes],
        *,
        temp_dir: Path,
        result_path: Path,
        terminate_grace_seconds: float,
        kill_grace_seconds: float,
    ) -> None:
        self.request = request
        self._process = process
        self._temp_dir = temp_dir
        self._result_path = result_path
        self._terminate_grace_seconds = terminate_grace_seconds
        self._kill_grace_seconds = kill_grace_seconds
        self._started_monotonic = monotonic()
        self._started_at = time()
        self._result: ExecutionResult | None = None
        self._lock = threading.RLock()
        self._closed = False

    @property
    def execution_id(self) -> str:
        return self.request.execution_id

    @property
    def pid(self) -> int | None:
        return self._process.pid

    def poll(self) -> ExecutionResult | None:
        with self._lock:
            if self._result is not None:
                return self._result
            if self._closed:
                return None

            if (
                self._process.poll() is None
                and monotonic() - self._started_monotonic >= self.request.timeout_seconds
            ):
                return self._terminate(
                    ExecutorStatus.TIMED_OUT,
                    error_code="execution_timeout",
                )

            exit_code = self._process.poll()
            if exit_code is None:
                return None
            self._result = self._read_terminal_result(exit_code)
            return self._result

    def wait(self, timeout: float | None = None) -> ExecutionResult | None:
        deadline = None if timeout is None else monotonic() + max(0.0, timeout)
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and monotonic() >= deadline:
                return None
            sleep(0.02)

    def cancel(self, reason: str = "cancel_requested") -> ExecutionResult:
        with self._lock:
            existing = self.poll()
            if existing is not None:
                return existing
            return self._terminate(
                ExecutorStatus.CANCELLED,
                error_code=_bounded_code(reason, "cancel_requested"),
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._process.poll() is None:
                self._terminate(
                    ExecutorStatus.CANCELLED,
                    error_code="handle_closed",
                )
            self._closed = True
            try:
                self._process.stdout and self._process.stdout.close()
                self._process.stderr and self._process.stderr.close()
                self._process.stdin and self._process.stdin.close()
            except Exception:
                pass
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _read_terminal_result(self, exit_code: int) -> ExecutionResult:
        if not self._result_path.exists():
            return ExecutionResult(
                execution_id=self.request.execution_id,
                task_id=self.request.task_id,
                status=ExecutorStatus.CRASHED,
                error_code="child_exited_without_result",
                error_type="ChildProcessExit",
                exit_code=exit_code,
                pid=self._process.pid,
                started_at=self._started_at,
                finished_at=time(),
            )
        try:
            raw = json.loads(self._result_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("child result is not an object")
            result = ExecutionResult.from_dict(raw)
            if (
                result.execution_id != self.request.execution_id
                or result.task_id != self.request.task_id
            ):
                raise ValueError("child result identity mismatch")
            if result.status is ExecutorStatus.SUCCEEDED and exit_code != 0:
                raise ValueError("successful child result had non-zero exit")
            return replace(
                result,
                exit_code=exit_code,
                pid=self._process.pid,
                started_at=result.started_at or self._started_at,
                finished_at=result.finished_at or time(),
            )
        except Exception as exc:
            return ExecutionResult(
                execution_id=self.request.execution_id,
                task_id=self.request.task_id,
                status=ExecutorStatus.CRASHED,
                error_code="invalid_child_result",
                error_type=type(exc).__name__[:200],
                exit_code=exit_code,
                pid=self._process.pid,
                started_at=self._started_at,
                finished_at=time(),
            )

    def _terminate(
        self,
        requested_status: ExecutorStatus,
        *,
        error_code: str,
    ) -> ExecutionResult:
        if self._result is not None:
            return self._result

        termination_method = "already_exited"
        if self._process.poll() is None:
            termination_method = "terminate"
            self._signal_tree(force=False)
            self._wait_for_exit(self._terminate_grace_seconds)
        if self._process.poll() is None:
            termination_method = "kill"
            self._signal_tree(force=True)
            self._wait_for_exit(self._kill_grace_seconds)

        exit_code = self._process.poll()
        status = requested_status
        if exit_code is None:
            status = ExecutorStatus.UNKNOWN_OUTCOME
            termination_method = "kill_failed"

        self._result = ExecutionResult(
            execution_id=self.request.execution_id,
            task_id=self.request.task_id,
            status=status,
            error_code=error_code,
            error_type=None,
            exit_code=exit_code,
            pid=self._process.pid,
            started_at=self._started_at,
            finished_at=time(),
            termination_method=termination_method,
        )
        return self._result

    def _wait_for_exit(self, timeout: float) -> None:
        if timeout <= 0:
            return
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass

    def _signal_tree(self, *, force: bool) -> None:
        pid = self._process.pid
        if self._process.poll() is not None:
            return
        if os.name == "nt":
            command = ["taskkill", "/PID", str(pid), "/T"]
            if force:
                command.append("/F")
            try:
                subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(1.0, self._kill_grace_seconds),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                return
            except Exception:
                pass
        else:
            try:
                os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            self._process.kill() if force else self._process.terminate()
        except (ProcessLookupError, OSError):
            pass


def _bounded_code(value: str, default: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in {"_", "-", "."} else "_"
        for char in value.strip()
    )[:120]
    return normalized or default


__all__ = [
    "DEFAULT_ALLOWED_ENTRYPOINTS",
    "SubprocessExecutionHandle",
    "SubprocessWorkerExecutor",
]
