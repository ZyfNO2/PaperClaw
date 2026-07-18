"""Read-only LSP tools with bounded structural output."""

from __future__ import annotations

import json
from typing import Any

from paperclaw.tools.base import ToolContext, ToolResult, ToolValidationError, require_string, truncate
from paperclaw.tools.registry import ToolRegistry

from .manager import LSPManager


class _PositionTool:
    method_name = ""

    def __init__(self, manager: LSPManager) -> None:
        self.manager = manager

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "path")
        _position(arguments, "line")
        _position(arguments, "character")

    def _resolved(self, arguments: dict[str, Any]):
        return self.manager.resolve(require_string(arguments, "path"))


class LSPDefinitionTool(_PositionTool):
    name = "lsp_definition"
    description = (
        "Return semantic definition locations for a workspace file position. "
        "Arguments: path, zero-based line, zero-based character. Read-only."
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path, client = self._resolved(arguments)
        return _result(
            client.definition(
                path,
                _position(arguments, "line"),
                _position(arguments, "character"),
            ),
            context,
            operation=self.name,
        )


class LSPReferencesTool(_PositionTool):
    name = "lsp_references"
    description = (
        "Return semantic references for a workspace file position. Arguments: "
        "path, zero-based line, zero-based character, optional include_declaration."
    )

    def validate(self, arguments: dict[str, Any]) -> None:
        super().validate(arguments)
        if not isinstance(arguments.get("include_declaration", False), bool):
            raise ToolValidationError("include_declaration must be a boolean")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path, client = self._resolved(arguments)
        return _result(
            client.references(
                path,
                _position(arguments, "line"),
                _position(arguments, "character"),
                include_declaration=bool(arguments.get("include_declaration", False)),
            ),
            context,
            operation=self.name,
        )


class LSPHoverTool(_PositionTool):
    name = "lsp_hover"
    description = (
        "Return hover/type information for a workspace file position. Arguments: "
        "path, zero-based line, zero-based character. Read-only."
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path, client = self._resolved(arguments)
        return _result(
            client.hover(
                path,
                _position(arguments, "line"),
                _position(arguments, "character"),
            ),
            context,
            operation=self.name,
        )


class LSPDiagnosticsTool:
    name = "lsp_diagnostics"
    description = (
        "Return current language-server diagnostics for a workspace file. "
        "Arguments: path and optional wait_seconds up to 5. Read-only."
    )

    def __init__(self, manager: LSPManager) -> None:
        self.manager = manager

    def validate(self, arguments: dict[str, Any]) -> None:
        require_string(arguments, "path")
        wait = arguments.get("wait_seconds", 1.0)
        if isinstance(wait, bool) or not isinstance(wait, (int, float)):
            raise ToolValidationError("wait_seconds must be numeric")
        if not 0 <= float(wait) <= 5:
            raise ToolValidationError("wait_seconds must be within [0, 5]")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path, client = self.manager.resolve(require_string(arguments, "path"))
        return _result(
            client.diagnostics(
                path,
                wait_seconds=float(arguments.get("wait_seconds", 1.0)),
            ),
            context,
            operation=self.name,
        )


class LSPSymbolsTool:
    name = "lsp_symbols"
    description = (
        "Return semantic document symbols for path, or workspace symbols when only "
        "query is provided. Arguments: optional path, optional query. Read-only."
    )

    def __init__(self, manager: LSPManager) -> None:
        self.manager = manager

    def validate(self, arguments: dict[str, Any]) -> None:
        path = arguments.get("path")
        query = arguments.get("query", "")
        if path is not None and (not isinstance(path, str) or not path.strip()):
            raise ToolValidationError("path must be non-empty text")
        if not isinstance(query, str):
            raise ToolValidationError("query must be text")
        if path is None and not query.strip():
            raise ToolValidationError("provide path or a non-empty workspace query")

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        return _result(
            self.manager.symbols(
                query=str(arguments.get("query", "")),
                path=arguments.get("path"),
            ),
            context,
            operation=self.name,
        )


def register_lsp_tools(registry: ToolRegistry, manager: LSPManager) -> None:
    for tool in (
        LSPDiagnosticsTool(manager),
        LSPDefinitionTool(manager),
        LSPReferencesTool(manager),
        LSPSymbolsTool(manager),
        LSPHoverTool(manager),
    ):
        if tool.name not in registry.names:
            registry.register(tool)


def _position(arguments: dict[str, Any], name: str) -> int:
    value = arguments.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ToolValidationError(f"{name} must be a non-negative integer")
    return value


def _result(value: Any, context: ToolContext, *, operation: str) -> ToolResult:
    safe_value = _bounded_value(value, depth=0)
    rendered, was_truncated = truncate(
        json.dumps(
            {"operation": operation, "result": safe_value},
            ensure_ascii=False,
            sort_keys=True,
        ),
        context.output_limit,
    )
    return ToolResult(
        True,
        rendered,
        metadata={
            "read_only": True,
            "result_truncated": was_truncated,
            "configured_servers": list(getattr(context, "configured_servers", [])),
        },
    )


def _bounded_value(value: Any, *, depth: int) -> Any:
    if depth >= 12:
        return "[depth-limited]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:20_000]
    if isinstance(value, list):
        return [_bounded_value(item, depth=depth + 1) for item in value[:500]]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 500:
                break
            output[str(key)[:200]] = _bounded_value(item, depth=depth + 1)
        return output
    return str(value)[:2_000]


__all__ = [
    "LSPDefinitionTool",
    "LSPDiagnosticsTool",
    "LSPHoverTool",
    "LSPReferencesTool",
    "LSPSymbolsTool",
    "register_lsp_tools",
]
