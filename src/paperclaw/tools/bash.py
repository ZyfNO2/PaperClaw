from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from .base import ToolContext, ToolResult, ToolValidationError, require_string, truncate


class BashTool:
    name = "bash"
    description = "Run one non-interactive PowerShell command in the workspace with timeout and output limits."
    _denied = re.compile(
        r"(?i)(pip|uv|poetry|npm|pnpm|yarn)\s+(install|add)|"
        r"remove-item\s+.*-recurse|format-volume|clear-disk|shutdown|restart-computer|"
        r"start-process|\b(rm|del|rmdir)\b.*(/s|-r|-rf)|[&|]\s*$"
    )
    _env_allowlist = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PYTHONUTF8"}

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
        env = {key: value for key, value in os.environ.items() if key.upper() in self._env_allowlist}
        env["PYTHONUTF8"] = "1"
        process = subprocess.Popen(
                ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", arguments["command"]],
                cwd=context.workspace,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        try:
            stdout, stderr = process.communicate(timeout=arguments.get("timeout_seconds", 30))
        except subprocess.TimeoutExpired as exc:
            cleanup_failed = False
            try:
                killed = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                cleanup_failed = killed.returncode not in (0, 128)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_failed = True
            if cleanup_failed and process.poll() is None:
                process.kill()
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=2)
            duration = int((time.perf_counter() - started) * 1000)
            output, truncated_flag = truncate((stdout or "") + (stderr or ""), context.output_limit)
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


def _classify_command(command: str) -> str:
    """Group commands coarsely so Verify can distinguish tests from ad-hoc execution without trusting free text."""

    normalized = command.lower()
    if "pytest" in normalized:
        return "pytest"
    return "shell"
