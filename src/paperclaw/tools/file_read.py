from __future__ import annotations

from typing import Any

from .base import ToolContext, ToolResult, ToolValidationError, require_string, truncate
from .paths import resolve_workspace_path


class FileReadTool:
    name = "file_read"
    description = "Read a UTF-8 text file inside the workspace, optionally by line range."

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "path")
        for key in ("start_line", "end_line"):
            if key in arguments and (not isinstance(arguments[key], int) or arguments[key] < 1):
                raise ToolValidationError(f"{key} must be a positive integer")
        if arguments.get("end_line", 1) < arguments.get("start_line", 1):
            raise ToolValidationError("end_line must be >= start_line")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = resolve_workspace_path(context.workspace, arguments["path"], must_exist=True)
        if not path.is_file():
            return ToolResult(False, "path is not a file", "not_found")
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except UnicodeDecodeError as exc:
            return ToolResult(False, str(exc), "decode_error")
        start = arguments.get("start_line", 1)
        end = min(arguments.get("end_line", start + 499), len(lines))
        rendered = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
        rendered, truncated = truncate(rendered, context.output_limit)
        return ToolResult(True, rendered, metadata={"path": str(path), "lines": len(lines), "truncated": truncated})
