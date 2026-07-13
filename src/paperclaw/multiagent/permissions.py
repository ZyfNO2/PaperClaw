"""PermissionGuard Lite for v0.03.

v0.03 only supports allow/deny decisions. Dangerous operations are denied at the
tool boundary, not by hoping the model prompt is perfect. Full HITL and sandbox
isolation are deliberately out of scope until v0.05.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperclaw.multiagent.contracts import PermissionDecision


# Tools that can modify files or run arbitrary code are gated.
_MUTATING_TOOLS = {"file_write", "file_edit", "bash"}

# Bash commands that are always denied, regardless of scope.
_BASH_DENIED = re.compile(
    r"(?i)"
    r"(pip|uv|poetry|npm|pnpm|yarn|conda|mamba)\s+(install|add|remove|uninstall)|"
    r"remove-item\s+.*-recurse|format-volume|clear-disk|shutdown|restart-computer|"
    r"start-process\s+.*-verb\s+runas|"
    r"\b(rm|del|rmdir)\b.*(/s|-r|-rf)|"
    r"[>&|]\s*$"
)


@dataclass
class PermissionCheck:
    """Result of evaluating one tool call against a task's scope."""

    decision: PermissionDecision
    reason: str
    tool_name: str
    arguments: dict[str, Any]


class PermissionGuardLite:
    """Lightweight scope guard for Worker tool calls.

    Each task carries allowed_paths, writable_paths, and allowed_tools. The guard
    checks every tool call before execution and records a deny decision with a
    stable reason string. Denied calls surface as ToolResult errors so the Worker
    can react, not crash.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve(strict=True)

    def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        allowed_paths: list[str],
        writable_paths: list[str],
        allowed_tools: list[str],
    ) -> PermissionCheck:
        """Evaluate a single tool call.

        Rules:
        - The tool must be in allowed_tools.
        - For mutating tools, the target path must be inside writable_paths.
        - For read tools, the target path must be inside allowed_paths.
        - Absolute paths or path escapes are denied.
        - Bash commands matching the deny pattern are denied.
        """

        if allowed_tools and tool_name not in allowed_tools:
            return PermissionCheck(
                PermissionDecision.DENY,
                f"tool {tool_name} not in task allowed_tools",
                tool_name,
                arguments,
            )

        if tool_name in {"file_read", "file_write", "file_edit", "grep"}:
            path = arguments.get("path")
            if not isinstance(path, str):
                return PermissionCheck(
                    PermissionDecision.DENY,
                    f"{tool_name} requires a string path",
                    tool_name,
                    arguments,
                )
            resolved = self._resolve_path(path)
            if resolved is None:
                return PermissionCheck(
                    PermissionDecision.DENY,
                    f"path escapes workspace or is invalid: {path}",
                    tool_name,
                    arguments,
                )
            if tool_name in _MUTATING_TOOLS:
                if not self._path_under_any(resolved, writable_paths):
                    return PermissionCheck(
                        PermissionDecision.DENY,
                        f"{tool_name} target not in writable_paths: {path}",
                        tool_name,
                        arguments,
                    )
            else:
                if not self._path_under_any(resolved, allowed_paths):
                    return PermissionCheck(
                        PermissionDecision.DENY,
                        f"{tool_name} target not in allowed_paths: {path}",
                        tool_name,
                        arguments,
                    )

        if tool_name == "bash":
            command = arguments.get("command", "")
            if not isinstance(command, str):
                return PermissionCheck(
                    PermissionDecision.DENY,
                    "bash command must be a string",
                    tool_name,
                    arguments,
                )
            if _BASH_DENIED.search(command):
                return PermissionCheck(
                    PermissionDecision.DENY,
                    "bash command denied by v0.03 safety policy",
                    tool_name,
                    arguments,
                )

        return PermissionCheck(
            PermissionDecision.ALLOW,
            "allowed",
            tool_name,
            arguments,
        )

    def _resolve_path(self, raw_path: str) -> Path | None:
        """Resolve a path relative to workspace and ensure it stays inside."""

        candidate = Path(raw_path)
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
        else:
            resolved = (self.workspace / candidate).resolve(strict=False)
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            return None
        return resolved

    def _path_under_any(self, resolved: Path, scopes: list[str]) -> bool:
        """Check whether resolved is under any of the scope prefixes.

        An empty scope list means no writes are allowed. A scope of '.' means the
        whole workspace.
        """

        if not scopes:
            return False
        for scope in scopes:
            scope_path = (self.workspace / scope).resolve(strict=False)
            try:
                resolved.relative_to(scope_path)
                return True
            except ValueError:
                continue
        return False
