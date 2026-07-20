"""Controlled activation for project-scoped Skills and Connectors."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping, Protocol, Sequence

from .extensions import (
    ExtensionPermissions,
    ProjectExtensionDescriptor,
    ProjectExtensionRegistry,
)


class ConnectorRuntime(Protocol):
    def discover_tools(self) -> Sequence[Mapping[str, Any]]: ...
    def close(self) -> None: ...


ConnectorFactory = Callable[
    [ProjectExtensionDescriptor, ExtensionPermissions], ConnectorRuntime
]


@dataclass(frozen=True)
class ActivatedSkill:
    extension_id: str
    version: str
    trust_source: str
    path: str
    content: str
    permissions: ExtensionPermissions

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "version": self.version,
            "trust_source": self.trust_source,
            "path": self.path,
            "content": self.content,
            "permissions": self.permissions.to_dict(),
        }


@dataclass(frozen=True)
class ActivatedConnector:
    extension_id: str
    version: str
    trust_source: str
    factory_id: str
    permissions: ExtensionPermissions
    tools: tuple[Mapping[str, Any], ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "version": self.version,
            "trust_source": self.trust_source,
            "factory_id": self.factory_id,
            "permissions": self.permissions.to_dict(),
            "tools": [dict(item) for item in self.tools],
        }


@dataclass(frozen=True)
class ProjectExtensionActivation:
    skills: tuple[ActivatedSkill, ...]
    connectors: tuple[ActivatedConnector, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "skills": [item.to_public_dict() for item in self.skills],
            "connectors": [item.to_public_dict() for item in self.connectors],
        }


class ProjectExtensionActivator:
    """Activate descriptors through host-controlled factories and ceilings."""

    def __init__(
        self,
        registry: ProjectExtensionRegistry,
        *,
        permission_ceiling: ExtensionPermissions,
        allowed_trust_sources: Sequence[str] = ("builtin", "verified", "project"),
        connector_factories: Mapping[str, ConnectorFactory] | None = None,
        max_skill_bytes: int = 262_144,
    ) -> None:
        if isinstance(max_skill_bytes, bool) or max_skill_bytes < 1:
            raise ValueError("max_skill_bytes must be positive")
        self.registry = registry
        self.permission_ceiling = permission_ceiling
        self.allowed_trust_sources = frozenset(allowed_trust_sources)
        self.connector_factories = dict(connector_factories or {})
        self.max_skill_bytes = max_skill_bytes
        self._sessions: list[ConnectorRuntime] = []

    def activate(self) -> ProjectExtensionActivation:
        skills: list[ActivatedSkill] = []
        connectors: list[ActivatedConnector] = []
        try:
            for descriptor in self.registry.list(enabled=True):
                if descriptor.trust_source not in self.allowed_trust_sources:
                    raise PermissionError(
                        f"extension trust source is not allowed: {descriptor.extension_id}"
                    )
                effective = descriptor.permissions.intersect(self.permission_ceiling)
                if descriptor.kind == "skill":
                    skills.append(self._activate_skill(descriptor, effective))
                else:
                    connectors.append(self._activate_connector(descriptor, effective))
        except BaseException:
            self.close()
            raise
        return ProjectExtensionActivation(tuple(skills), tuple(connectors))

    def close(self) -> None:
        while self._sessions:
            runtime = self._sessions.pop()
            try:
                runtime.close()
            except Exception:
                pass

    def _activate_skill(
        self,
        descriptor: ProjectExtensionDescriptor,
        permissions: ExtensionPermissions,
    ) -> ActivatedSkill:
        unresolved = self.registry.workspace / descriptor.entrypoint
        if unresolved.is_symlink():
            raise ValueError("Skill entrypoint must not be a symbolic link")
        path = unresolved.resolve(strict=True)
        try:
            relative = path.relative_to(self.registry.workspace)
        except ValueError as exc:
            raise ValueError("Skill entrypoint escapes workspace") from exc
        if relative.parts and relative.parts[0] == ".paperclaw":
            raise ValueError("Skill entrypoint must not use the control directory")
        if not path.is_file():
            raise ValueError("Skill entrypoint must be a regular file")
        raw = path.read_bytes()
        if len(raw) > self.max_skill_bytes:
            raise ValueError("Skill file exceeds configured byte limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Skill file must be UTF-8 text") from exc
        return ActivatedSkill(
            extension_id=descriptor.extension_id,
            version=descriptor.version,
            trust_source=descriptor.trust_source,
            path=relative.as_posix(),
            content=content,
            permissions=permissions,
        )

    def _activate_connector(
        self,
        descriptor: ProjectExtensionDescriptor,
        permissions: ExtensionPermissions,
    ) -> ActivatedConnector:
        factory_id = descriptor.entrypoint.removeprefix("mcp:")
        try:
            factory = self.connector_factories[factory_id]
        except KeyError:
            raise PermissionError(
                f"connector factory is not registered by the host: {factory_id}"
            ) from None
        runtime = factory(descriptor, permissions)
        self._sessions.append(runtime)
        tools = _public_tools(runtime.discover_tools(), permissions)
        return ActivatedConnector(
            extension_id=descriptor.extension_id,
            version=descriptor.version,
            trust_source=descriptor.trust_source,
            factory_id=factory_id,
            permissions=permissions,
            tools=tools,
        )

    def __enter__(self) -> "ProjectExtensionActivator":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _public_tools(
    rows: Sequence[Mapping[str, Any]],
    permissions: ExtensionPermissions,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError("connector discovery must return a sequence")
    allowed = set(permissions.tools)
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("connector tool descriptor must be an object")
        name = str(row.get("name", ""))
        if not name or name in seen:
            raise ValueError("connector tool names must be unique and non-empty")
        seen.add(name)
        if name not in allowed:
            continue
        result.append(
            {
                "name": name,
                "description": str(row.get("description", ""))[:4_000],
                "input_schema": _public_json(row.get("input_schema", {})),
            }
        )
    return tuple(sorted(result, key=lambda item: str(item["name"])))


def _public_json(value: Any) -> Any:
    blocked = {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "authorization",
        "cookie",
        "client_secret",
        "private_key",
    }

    def inspect(node: Any) -> None:
        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = str(raw_key).strip().lower().replace("-", "_")
                if key in blocked:
                    raise ValueError("connector discovery contains a private field")
                inspect(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                inspect(child)

    inspect(value)
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("connector discovery must be public JSON") from exc


__all__ = [
    "ActivatedConnector",
    "ActivatedSkill",
    "ConnectorFactory",
    "ConnectorRuntime",
    "ProjectExtensionActivation",
    "ProjectExtensionActivator",
]
