"""Workspace-scoped language server configuration and lifecycle manager."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence

from .client import LSPClient, LSPError


@dataclass(frozen=True)
class LanguageServerConfig:
    name: str
    command: tuple[str, ...]
    language_id: str
    extensions: tuple[str, ...]
    request_timeout: float = 10.0
    initialize_timeout: float = 20.0

    @classmethod
    def from_mapping(cls, name: str, value: Mapping[str, Any]) -> "LanguageServerConfig":
        command = value.get("command")
        extensions = value.get("extensions")
        if not isinstance(command, list) or not command or not all(
            isinstance(item, str) and item for item in command
        ):
            raise ValueError(f"LSP config {name} command must be a non-empty string list")
        if not isinstance(extensions, list) or not extensions or not all(
            isinstance(item, str) and item.startswith(".") for item in extensions
        ):
            raise ValueError(f"LSP config {name} extensions must contain suffixes")
        language_id = value.get("language_id")
        if not isinstance(language_id, str) or not language_id.strip():
            raise ValueError(f"LSP config {name} language_id is required")
        request_timeout = float(value.get("request_timeout", 10.0))
        initialize_timeout = float(value.get("initialize_timeout", 20.0))
        if request_timeout <= 0 or initialize_timeout <= 0:
            raise ValueError("LSP timeouts must be positive")
        return cls(
            name=name,
            command=tuple(command),
            language_id=language_id.strip(),
            extensions=tuple(extension.lower() for extension in extensions),
            request_timeout=request_timeout,
            initialize_timeout=initialize_timeout,
        )


class LSPConfigurationError(LSPError):
    pass


class LSPManager:
    """Lazily start configured servers and enforce workspace path boundaries."""

    def __init__(
        self,
        workspace: str | Path,
        configs: Sequence[LanguageServerConfig] = (),
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        self._configs = tuple(configs)
        self._clients: dict[str, LSPClient] = {}
        self._lock = RLock()

    @classmethod
    def from_env(cls, workspace: str | Path) -> "LSPManager":
        raw = os.getenv("PAPERCLAW_LSP_CONFIG", "").strip()
        if not raw:
            return cls(workspace, ())
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LSPConfigurationError("PAPERCLAW_LSP_CONFIG must be valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise LSPConfigurationError("PAPERCLAW_LSP_CONFIG must be an object")
        configs = [
            LanguageServerConfig.from_mapping(str(name), value)
            for name, value in payload.items()
            if isinstance(value, Mapping)
        ]
        return cls(workspace, configs)

    @property
    def configured_servers(self) -> tuple[str, ...]:
        return tuple(config.name for config in self._configs)

    def resolve(self, path: str | Path) -> tuple[Path, LSPClient]:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("LSP path must reference a file")
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise PermissionError("LSP path escapes workspace") from exc
        config = next(
            (
                item
                for item in self._configs
                if resolved.suffix.lower() in item.extensions
            ),
            None,
        )
        if config is None:
            raise LSPConfigurationError(
                f"no language server configured for extension {resolved.suffix or '<none>'}"
            )
        return resolved, self._client(config)

    def symbols(self, *, query: str, path: str | Path | None = None) -> Any:
        if path is not None:
            resolved, client = self.resolve(path)
            return client.document_symbols(resolved)
        if not self._configs:
            raise LSPConfigurationError("no language servers are configured")
        results: list[dict[str, Any]] = []
        for config in self._configs:
            client = self._client(config)
            value = client.workspace_symbols(query)
            results.append({"server": config.name, "symbols": value})
        return results

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()

    def _client(self, config: LanguageServerConfig) -> LSPClient:
        with self._lock:
            existing = self._clients.get(config.name)
            if existing is not None and existing.returncode is None:
                return existing
            if existing is not None:
                existing.close()
                self._clients.pop(config.name, None)
            client = LSPClient(
                config.command,
                workspace=self.workspace,
                language_id=config.language_id,
                request_timeout=config.request_timeout,
                initialize_timeout=config.initialize_timeout,
            )
            self._clients[config.name] = client
            return client


__all__ = [
    "LSPConfigurationError",
    "LSPManager",
    "LanguageServerConfig",
]
