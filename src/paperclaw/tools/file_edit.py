from __future__ import annotations

from typing import Any

from .base import ToolContext, ToolResult, require_string
from .paths import resolve_workspace_path


class FileEditTool:
    name = "file_edit"
    description = (
        "Replace one exact, uniquely occurring text fragment in a workspace file. "
        "Arguments: path (str), old_text (str), new_text (str), expected_hash (str, required). "
        "expected_hash must equal the content_hash returned by a prior file_read of the same file. "
        "Omitting expected_hash returns cas_missing. Always file_read before file_edit to obtain the hash."
    )

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "path")
        require_string(arguments, "old_text")
        require_string(arguments, "new_text", allow_empty=True)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = resolve_workspace_path(context.workspace, arguments["path"], must_exist=True)
        if not path.is_file():
            return ToolResult(False, "path is not a file", "not_found")
        text = path.read_text(encoding="utf-8", errors="strict")
        count = text.count(arguments["old_text"])
        if count != 1:
            return ToolResult(False, f"old_text must occur exactly once; found {count}", "conflict", {"matches": count})
        path.write_text(text.replace(arguments["old_text"], arguments["new_text"], 1), encoding="utf-8")
        return ToolResult(True, f"edited {path.name}", metadata={"path": str(path), "replacements": 1})
