from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from .base import ToolContext, ToolResult, ToolValidationError, require_string, truncate


class _PortableCancellationHandle:
    """Adapter for legacy PID-only cancellation registries.

    The multi-agent Worker historically assumes that every registered process can
    be cancelled by passing ``handle.pid`` to a Windows-only ``taskkill`` helper.
    Accessing ``pid`` through this adapter first performs the portable process-tree
    termination, then returns the original PID so the legacy best-effort call is
    harmless. The adapter is only stored in the cancellation registry; command
    execution continues to use the real ``Popen`` object.
    """

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self._process = process

    def poll(self) -> int | None:
        return self._process.poll()

    @property
    def pid(self) -> int:
        _terminate_process_tree(self._process)
        return self._process.pid


class BashTool:
    name = "bash"
    description = "Run one non-interactive shell command in the workspace with timeout and output limits."
    _denied = re.compile(
        r"(?i)(pip|uv|poetry|npm|pnpm|yarn)\s+(install|add)|"
        r"remove-item\s+.*-recurse|format-volume|clear-disk|shutdown|restart-computer|"
        r"start-process|\b(rm|del|rmdir)\b.*(/s|-r|-rf)|[&|]\s*$"
    )
    _env_allowlist = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "HOME",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "COMSPEC",
        "SHELL",
        "PYTHONUTF8",
    }

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Keep the legacy multi-agent wrapper on the shared process lifecycle.

        ``_CancellableBashTool`` predates the portable lifecycle and duplicated a
        Windows-only ``Popen`` implementation. Until that wrapper is removed, its
        execution method is intentionally rebound here so validation, shell
        selection, timeout handling, registration and cleanup cannot diverge.
        """

        super().__init_subclass__(**kwargs)
        if (
            cls.__module__ == "paperclaw.multiagent.scoped_tools"
            and cls.__name__ == "_CancellableBashTool"
        ):
            cls.execute = BashTool.execute  # type: ignore[method-assign]

    def validate(self, arguments: dict[str, Any]) -> None:
        command = require_string(arguments, "command")
        timeout = arguments.get("timeout_seconds", 30)
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise ToolValidationError("timeout_seconds must be in (0, 60]")
        if "\n" in command or "\r" in command:
            raise ToolValidationError("command must be a single line")
        if self._denied.search(command):
            raise ToolValidationError("command denied by v0.01 safety policy")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc)
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in self._env_allowlist
        }
        env["PYTHONUTF8"] = "1"
        process = subprocess.Popen(
            self._shell_command(arguments["command"]),
            cwd=context.workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                if os.name == "nt"
                else 0
            ),
            start_new_session=os.name != "nt",
        )
        registration = self._register_process(process)
        timeout_seconds = arguments.get("timeout_seconds", 30)
        deadline = time.monotonic() + timeout_seconds
        try:
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(process.args, timeout_seconds)
                    try:
                        process.wait(timeout=min(0.2, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        if (
                            context.stop_token is not None
                            and context.stop_token.is_cancelled
                        ):
                            self._terminate_process_tree(process)
                            try:
                                stdout, stderr = process.communicate(timeout=2)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                stdout, stderr = process.communicate(timeout=2)
                            raise RuntimeError("bash execution cancelled")
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                cleanup_failed = self._terminate_process_tree(process)
                try:
                    stdout, stderr = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate(timeout=2)
                duration = int((time.perf_counter() - started) * 1000)
                output, truncated_flag = truncate(
                    (stdout or "") + (stderr or ""), context.output_limit
                )
                return ToolResult(
                    False,
                    output or "command timed out",
                    "unknown_outcome",
                    {
                        "command": arguments["command"],
                        "command_class": _classify_command(arguments["command"]),
                        "cwd": str(context.workspace),
                        "started_at": started_at.isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "timed_out": True,
                        "duration_ms": duration,
                        "truncated": truncated_flag,
                        "cleanup_failed": cleanup_failed,
                    },
                )
            duration = int((time.perf_counter() - started) * 1000)
            combined = stdout + (f"\n[stderr]\n{stderr}" if stderr else "")
            output, truncated_flag = truncate(combined.rstrip(), context.output_limit)
            return ToolResult(
                process.returncode == 0,
                output,
                None if process.returncode == 0 else "command_failed",
                {
                    "command": arguments["command"],
                    "command_class": _classify_command(arguments["command"]),
                    "cwd": str(context.workspace),
                    "started_at": started_at.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "exit_code": process.returncode,
                    "timed_out": False,
                    "duration_ms": duration,
                    "truncated": truncated_flag,
                },
            )
        finally:
            self._unregister_process(registration)

    @staticmethod
    def _shell_command(command: str) -> list[str]:
        if os.name == "nt":
            return [
                "powershell",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ]
        return ["/bin/sh", "-c", command]

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[Any]) -> bool:
        return _terminate_process_tree(process)

    def _register_process(
        self,
        process: subprocess.Popen[Any],
    ) -> tuple[dict[str, Any], str, _PortableCancellationHandle] | None:
        runtime_state = getattr(self, "_runtime_state", None)
        task_id = getattr(self, "_task_id", None)
        if not isinstance(runtime_state, dict) or not isinstance(task_id, str):
            return None
        registry = runtime_state.get("_process_registry")
        if not isinstance(registry, dict) or "lock" not in registry:
            return None
        handle = _PortableCancellationHandle(process)
        with registry["lock"]:
            registry.setdefault("processes", {}).setdefault(task_id, []).append(handle)
        return registry, task_id, handle

    @staticmethod
    def _unregister_process(
        registration: tuple[dict[str, Any], str, _PortableCancellationHandle] | None,
    ) -> None:
        if registration is None:
            return
        registry, task_id, handle = registration
        with registry["lock"]:
            processes = registry.setdefault("processes", {}).get(task_id, [])
            if handle in processes:
                processes.remove(handle)
            if not processes:
                registry["processes"].pop(task_id, None)


def _terminate_process_tree(process: subprocess.Popen[Any]) -> bool:
    """Terminate a process tree and report whether cleanup was incomplete."""

    if process.poll() is not None:
        return False
    if os.name == "nt":
        try:
            killed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if killed.returncode in (0, 128):
                return False
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            process.kill()
        return True

    try:
        os.killpg(process.pid, signal.SIGKILL)
        return False
    except (OSError, ProcessLookupError):
        if process.poll() is None:
            process.kill()
            return True
        return False


def _classify_command(command: str) -> str:
    """Group commands coarsely so Verify can distinguish tests from ad-hoc execution without trusting free text."""

    normalized = command.lower()
    if "pytest" in normalized:
        return "pytest"
    return "shell"
