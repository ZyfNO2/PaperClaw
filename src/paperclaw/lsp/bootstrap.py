"""Composition helpers for process-scoped LSP managers."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from .manager import LSPManager
from .tools import register_lsp_tools

_CACHE: dict[str, LSPManager] = {}
_LOCK = RLock()
_CLI_MARKER = "_paperclaw_lsp_cli_extension"


def get_lsp_manager(workspace: str | Path) -> LSPManager:
    resolved = Path(workspace).expanduser().resolve(strict=True)
    key = str(resolved)
    with _LOCK:
        manager = _CACHE.get(key)
        if manager is None:
            manager = LSPManager.from_env(resolved)
            _CACHE[key] = manager
        return manager


def install_cli_lsp_extension(cli_module: Any) -> None:
    if getattr(cli_module, _CLI_MARKER, False):
        return
    original_build_memory_runtime = cli_module.build_memory_runtime

    def build_memory_runtime_with_lsp(workspace, *args: Any, **kwargs: Any):
        components = original_build_memory_runtime(workspace, *args, **kwargs)
        register_lsp_tools(components.tool_registry, get_lsp_manager(workspace))
        return components

    cli_module.build_memory_runtime = build_memory_runtime_with_lsp
    setattr(cli_module, _CLI_MARKER, True)


def shutdown_lsp_managers() -> None:
    with _LOCK:
        managers = list(_CACHE.values())
        _CACHE.clear()
    for manager in managers:
        manager.close()


__all__ = [
    "get_lsp_manager",
    "install_cli_lsp_extension",
    "shutdown_lsp_managers",
]
