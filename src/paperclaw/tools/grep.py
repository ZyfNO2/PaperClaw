from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from .base import ToolContext, ToolResult, ToolValidationError, require_string, truncate
from .paths import resolve_workspace_path


class GrepTool:
    name = "grep"
    description = "Search UTF-8 workspace files with a regular expression."
    _ignored = {".git", ".venv", "venv", "node_modules", "build", "dist", "__pycache__"}

    def validate(self, arguments: dict[str, Any]) -> None:
        pattern = require_string(arguments, "pattern")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ToolValidationError(f"invalid regex: {exc}") from exc
        if "max_results" in arguments and (not isinstance(arguments["max_results"], int) or arguments["max_results"] < 1):
            raise ToolValidationError("max_results must be a positive integer")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        base = resolve_workspace_path(context.workspace, arguments.get("path", "."), must_exist=True)
        regex = re.compile(arguments["pattern"])
        glob = arguments.get("glob", "*")
        limit = arguments.get("max_results", 100)
        files = [base] if base.is_file() else base.rglob("*")
        results: list[str] = []
        skipped = 0
        truncated_flag = False
        for path in files:
            if not path.is_file() or any(part in self._ignored for part in path.parts) or not fnmatch.fnmatch(path.name, glob):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
            except (UnicodeDecodeError, OSError):
                skipped += 1
                continue
            for number, line in enumerate(lines, 1):
                if regex.search(line):
                    rel = path.relative_to(context.workspace.resolve())
                    results.append(f"{rel}:{number}:{line}")
                    if len(results) >= limit:
                        truncated_flag = True
                        break
            if truncated_flag:
                break
        output, char_truncated = truncate("\n".join(results), context.output_limit)
        return ToolResult(True, output, metadata={"matches": len(results), "truncated": truncated_flag or char_truncated, "skipped_files": skipped})
