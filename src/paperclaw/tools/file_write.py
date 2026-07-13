from __future__ import annotations

from typing import Any

from .base import ToolContext, ToolResult, ToolValidationError, require_string
from .paths import resolve_workspace_path


class FileWriteTool:
    name = "file_write"
    description = (
        "Create or explicitly overwrite a UTF-8 text file inside the workspace. "
        "Arguments: path (str), content (str), expected_hash (str, required for existing files). "
        "expected_hash must equal the content_hash returned by a prior file_read of the same file; "
        "use empty string '' for new files. Omitting expected_hash on an existing file returns cas_missing."
    )

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "path")
        require_string(arguments, "content", allow_empty=True)
        if "overwrite" in arguments and not isinstance(arguments["overwrite"], bool):
            raise ToolValidationError("overwrite must be boolean")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = resolve_workspace_path(context.workspace, arguments["path"])
        if not path.parent.exists():
            return ToolResult(False, "parent directory does not exist", "not_found")
        existed = path.exists()
        if existed and not arguments.get("overwrite", False):
            return ToolResult(False, "file exists and overwrite is false", "conflict")
        path.write_text(arguments["content"], encoding="utf-8", errors="strict")
        return ToolResult(True, f"wrote {len(arguments['content'])} characters to {path.name}", metadata={"path": str(path), "created": not existed, "overwritten": existed})
