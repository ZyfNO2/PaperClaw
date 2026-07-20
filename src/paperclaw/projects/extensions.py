"""Project-scoped Skill and Connector registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time
from typing import Any, Literal, Mapping, Sequence

from paperclaw.projects.manifest import ProjectManifestStore
from paperclaw.storage_safety import atomic_write_bytes, resolve_confined_path

ExtensionKind = Literal["skill", "connector"]
TrustSource = Literal["builtin", "verified", "project", "untrusted"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$"
)
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_REFERENCE = re.compile(r"^secret://[A-Za-z0-9][A-Za-z0-9_.:/-]{0,299}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = Path(".paperclaw")
_REGISTRY = _CONTROL / "extensions.json"
_AUDIT = _CONTROL / "extensions-audit.sqlite3"
_PRIVATE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "authorization",
        "cookie",
        "client_secret",
        "private_key",
    }
)


@dataclass(frozen=True)
class ExtensionPermissions:
    tools: tuple[str, ...] = ()
    read_paths: tuple[str, ...] = ()
    write_paths: tuple[str, ...] = ()
    network_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", _identifiers(self.tools, "tools"))
        object.__setattr__(self, "read_paths", _paths(self.read_paths, "read_paths"))
        object.__setattr__(self, "write_paths", _paths(self.write_paths, "write_paths"))
        hosts = tuple(
            sorted(dict.fromkeys(str(item).casefold() for item in self.network_hosts))
        )
        if any(_HOST.fullmatch(item) is None or item.startswith(".") for item in hosts):
            raise ValueError("network_hosts contains an invalid hostname")
        object.__setattr__(self, "network_hosts", hosts)

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | None
    ) -> "ExtensionPermissions":
        value = value or {}
        if not isinstance(value, Mapping):
            raise ValueError("permissions must be an object")
        allowed = {"tools", "read_paths", "write_paths", "network_hosts"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown permission fields: {sorted(unknown)}")
        return cls(
            tools=_string_array(value.get("tools", ()), "tools"),
            read_paths=_string_array(value.get("read_paths", ()), "read_paths"),
            write_paths=_string_array(value.get("write_paths", ()), "write_paths"),
            network_hosts=_string_array(
                value.get("network_hosts", ()), "network_hosts"
            ),
        )

    def intersect(self, ceiling: "ExtensionPermissions") -> "ExtensionPermissions":
        return ExtensionPermissions(
            tools=tuple(sorted(set(self.tools) & set(ceiling.tools))),
            read_paths=tuple(sorted(set(self.read_paths) & set(ceiling.read_paths))),
            write_paths=tuple(
                sorted(set(self.write_paths) & set(ceiling.write_paths))
            ),
            network_hosts=tuple(
                sorted(set(self.network_hosts) & set(ceiling.network_hosts))
            ),
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {name: list(value) for name, value in asdict(self).items()}


@dataclass(frozen=True)
class ProjectExtensionDescriptor:
    extension_id: str
    kind: ExtensionKind
    version: str
    entrypoint: str
    enabled: bool = False
    trust_source: TrustSource = "project"
    permissions: ExtensionPermissions = field(default_factory=ExtensionPermissions)
    auth_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _ID.fullmatch(self.extension_id) is None:
            raise ValueError("invalid extension_id")
        if self.kind not in {"skill", "connector"}:
            raise ValueError("kind must be skill or connector")
        if _VERSION.fullmatch(self.version) is None:
            raise ValueError("version must use semantic version syntax")
        if self.trust_source not in {"builtin", "verified", "project", "untrusted"}:
            raise ValueError("invalid trust_source")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        entrypoint = self.entrypoint.strip()
        if self.kind == "skill":
            entrypoint = _relative_path(entrypoint, "entrypoint")
            if entrypoint == ".paperclaw" or entrypoint.startswith(".paperclaw/"):
                raise ValueError("Skill entrypoint must not use the control directory")
            if self.auth_ref is not None:
                raise ValueError("Skill descriptors cannot declare auth_ref")
        else:
            if not entrypoint.startswith("mcp:") or _ID.fullmatch(entrypoint[4:]) is None:
                raise ValueError(
                    "Connector entrypoint must be a registered mcp:<factory_id>"
                )
            if self.auth_ref is not None and _REFERENCE.fullmatch(self.auth_ref) is None:
                raise ValueError("auth_ref must use secret:// reference syntax")
        object.__setattr__(self, "entrypoint", entrypoint)
        object.__setattr__(self, "metadata", _public_object(self.metadata, "metadata"))

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "ProjectExtensionDescriptor":
        if not isinstance(value, Mapping):
            raise ValueError("extension descriptor must be an object")
        allowed = {
            "extension_id",
            "kind",
            "version",
            "entrypoint",
            "enabled",
            "trust_source",
            "permissions",
            "auth_ref",
            "metadata",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown extension fields: {sorted(unknown)}")
        _reject_private_fields(value, "extension")
        return cls(
            extension_id=str(value["extension_id"]),
            kind=str(value["kind"]),  # type: ignore[arg-type]
            version=str(value["version"]),
            entrypoint=str(value["entrypoint"]),
            enabled=value.get("enabled", False),
            trust_source=str(value.get("trust_source", "project")),  # type: ignore[arg-type]
            permissions=ExtensionPermissions.from_mapping(value.get("permissions")),
            auth_ref=(
                str(value["auth_ref"])
                if value.get("auth_ref") is not None
                else None
            ),
            metadata=value.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "extension_id": self.extension_id,
            "kind": self.kind,
            "version": self.version,
            "entrypoint": self.entrypoint,
            "enabled": self.enabled,
            "trust_source": self.trust_source,
            "permissions": self.permissions.to_dict(),
            "auth_ref": self.auth_ref,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExtensionRegistrySnapshot:
    schema_version: int
    extensions: tuple[ProjectExtensionDescriptor, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "extensions": [item.to_dict() for item in self.extensions],
        }


class ProjectExtensionRegistry:
    def __init__(
        self,
        workspace: str | Path,
        *,
        max_bytes: int = 524_288,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("workspace must be a directory")
        if isinstance(max_bytes, bool) or max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self.path = self.workspace / _REGISTRY
        self.audit_path = self.workspace / _AUDIT
        self._assert_control_files_safe()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_audit()

    def snapshot(self) -> ExtensionRegistrySnapshot:
        if not self.path.exists():
            return ExtensionRegistrySnapshot(1, ())
        self._assert_control_files_safe()
        raw = self.path.read_bytes()
        if len(raw) > self.max_bytes:
            raise ValueError("extension registry exceeds configured byte limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("extension registry is not valid UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("extension registry must be an object")
        if set(payload) != {"schema_version", "extensions"}:
            raise ValueError("invalid extension registry shape")
        if payload["schema_version"] != 1 or not isinstance(payload["extensions"], list):
            raise ValueError("unsupported extension registry schema")
        rows = tuple(
            ProjectExtensionDescriptor.from_mapping(item)
            for item in payload["extensions"]
        )
        ids = [item.extension_id for item in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("extension registry contains duplicate ids")
        return ExtensionRegistrySnapshot(
            1, tuple(sorted(rows, key=lambda item: item.extension_id))
        )

    def list(
        self,
        *,
        kind: ExtensionKind | None = None,
        enabled: bool | None = None,
    ) -> tuple[ProjectExtensionDescriptor, ...]:
        return tuple(
            item
            for item in self.snapshot().extensions
            if (kind is None or item.kind == kind)
            and (enabled is None or item.enabled is enabled)
        )

    def register(
        self,
        descriptor: ProjectExtensionDescriptor,
        *,
        replace_existing: bool = False,
    ) -> ProjectExtensionDescriptor:
        rows = {item.extension_id: item for item in self.snapshot().extensions}
        existing = rows.get(descriptor.extension_id)
        if existing == descriptor:
            return descriptor
        if existing is not None and not replace_existing:
            raise ValueError("extension_id is already registered")
        rows[descriptor.extension_id] = descriptor
        self._save(tuple(rows.values()))
        self._audit(
            "register" if existing is None else "replace",
            descriptor.extension_id,
            descriptor.kind,
        )
        return descriptor

    def set_enabled(
        self, extension_id: str, enabled: bool
    ) -> ProjectExtensionDescriptor:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        rows = {item.extension_id: item for item in self.snapshot().extensions}
        if extension_id not in rows:
            raise KeyError(extension_id)
        updated = replace(rows[extension_id], enabled=enabled)
        rows[extension_id] = updated
        self._save(tuple(rows.values()))
        self._audit(
            "enable" if enabled else "disable", updated.extension_id, updated.kind
        )
        return updated

    def remove(self, extension_id: str) -> ProjectExtensionDescriptor:
        rows = {item.extension_id: item for item in self.snapshot().extensions}
        if extension_id not in rows:
            raise KeyError(extension_id)
        removed = rows.pop(extension_id)
        self._save(tuple(rows.values()))
        self._audit("remove", removed.extension_id, removed.kind)
        return removed

    def validate(self) -> tuple[dict[str, str], ...]:
        issues: list[dict[str, str]] = []
        for item in self.snapshot().extensions:
            if item.kind != "skill":
                continue
            try:
                path = self._skill_path(item.entrypoint)
            except ValueError as exc:
                issues.append(
                    {
                        "extension_id": item.extension_id,
                        "code": "skill_path_invalid",
                        "message": str(exc),
                    }
                )
                continue
            if not path.exists():
                issues.append(
                    {
                        "extension_id": item.extension_id,
                        "code": "skill_missing",
                        "message": "Skill entrypoint does not exist",
                    }
                )
            elif not path.is_file():
                issues.append(
                    {
                        "extension_id": item.extension_id,
                        "code": "skill_not_file",
                        "message": "Skill entrypoint is not a regular file",
                    }
                )
        return tuple(issues)

    def audit_events(self, *, limit: int = 200) -> tuple[dict[str, Any], ...]:
        if not 1 <= limit <= 5_000:
            raise ValueError("limit must be in [1, 5000]")
        self._assert_control_files_safe()
        with sqlite3.connect(self.audit_path) as connection:
            rows = connection.execute(
                "SELECT event_id, action, extension_id, kind, created_at "
                "FROM extension_audit ORDER BY event_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(
            {
                "event_id": int(row[0]),
                "action": str(row[1]),
                "extension_id": str(row[2]),
                "kind": str(row[3]),
                "created_at": float(row[4]),
            }
            for row in rows
        )

    def record_invocation(
        self,
        *,
        invocation_id: str,
        extension_id: str,
        tool_name: str,
        status: str,
        error_code: str | None,
        duration_ms: int,
        argument_bytes: int,
        result_bytes: int,
        schema_hash: str,
    ) -> None:
        """Persist a content-free Connector invocation audit record."""

        if _ID.fullmatch(invocation_id) is None:
            raise ValueError("invalid invocation_id")
        if _ID.fullmatch(extension_id) is None:
            raise ValueError("invalid extension_id")
        if _ID.fullmatch(tool_name) is None:
            raise ValueError("invalid tool_name")
        if status not in {"success", "error", "timeout", "cancelled", "denied"}:
            raise ValueError("invalid invocation status")
        if error_code is not None and _ID.fullmatch(error_code) is None:
            raise ValueError("invalid invocation error_code")
        for name, value in (
            ("duration_ms", duration_ms),
            ("argument_bytes", argument_bytes),
            ("result_bytes", result_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if _SHA256.fullmatch(schema_hash) is None:
            raise ValueError("schema_hash must be a lowercase SHA-256 digest")
        self._assert_control_files_safe()
        with sqlite3.connect(self.audit_path) as connection:
            connection.execute(
                "INSERT INTO extension_invocation_audit("
                "invocation_id, extension_id, tool_name, status, error_code, "
                "duration_ms, argument_bytes, result_bytes, schema_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    invocation_id,
                    extension_id,
                    tool_name,
                    status,
                    error_code,
                    duration_ms,
                    argument_bytes,
                    result_bytes,
                    schema_hash,
                    time.time(),
                ),
            )

    def invocation_events(
        self,
        *,
        limit: int = 200,
        extension_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return bounded, content-free Connector invocation evidence."""

        if not 1 <= limit <= 5_000:
            raise ValueError("limit must be in [1, 5000]")
        if extension_id is not None and _ID.fullmatch(extension_id) is None:
            raise ValueError("invalid extension_id")
        self._assert_control_files_safe()
        query = (
            "SELECT event_id, invocation_id, extension_id, tool_name, status, "
            "error_code, duration_ms, argument_bytes, result_bytes, schema_hash, "
            "created_at FROM extension_invocation_audit"
        )
        parameters: tuple[object, ...]
        if extension_id is None:
            query += " ORDER BY event_id DESC LIMIT ?"
            parameters = (limit,)
        else:
            query += " WHERE extension_id = ? ORDER BY event_id DESC LIMIT ?"
            parameters = (extension_id, limit)
        with sqlite3.connect(self.audit_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            {
                "event_id": int(row[0]),
                "invocation_id": str(row[1]),
                "extension_id": str(row[2]),
                "tool_name": str(row[3]),
                "status": str(row[4]),
                "error_code": None if row[5] is None else str(row[5]),
                "duration_ms": int(row[6]),
                "argument_bytes": int(row[7]),
                "result_bytes": int(row[8]),
                "schema_hash": str(row[9]),
                "created_at": float(row[10]),
            }
            for row in rows
        )

    def _save(self, rows: Sequence[ProjectExtensionDescriptor]) -> None:
        payload = ExtensionRegistrySnapshot(
            1, tuple(sorted(rows, key=lambda item: item.extension_id))
        ).to_dict()
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise ValueError("extension registry exceeds configured byte limit")
        self._assert_control_files_safe()
        atomic_write_bytes(
            self.path,
            encoded,
            overwrite=True,
            confinement_root=self.workspace,
        )
        self._sync_manifest(tuple(rows))

    def _sync_manifest(self, rows: Sequence[ProjectExtensionDescriptor]) -> None:
        store = ProjectManifestStore(self.workspace)
        if not store.exists:
            return
        manifest = store.load()
        store.save(
            replace(
                manifest,
                enabled_skills=tuple(
                    sorted(
                        item.extension_id
                        for item in rows
                        if item.kind == "skill" and item.enabled
                    )
                ),
                enabled_connectors=tuple(
                    sorted(
                        item.extension_id
                        for item in rows
                        if item.kind == "connector" and item.enabled
                    )
                ),
            )
        )

    def _skill_path(self, relative: str) -> Path:
        unresolved = self.workspace / relative
        if unresolved.is_symlink():
            raise ValueError("Skill entrypoint must not be a symbolic link")
        resolved = unresolved.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Skill entrypoint escapes workspace") from exc
        return resolved

    def _assert_control_files_safe(self) -> None:
        control = self.workspace / _CONTROL
        if control.is_symlink():
            raise ValueError("project control directory must not be a symbolic link")
        resolve_confined_path(
            self.workspace,
            control,
            strict=False,
            label="project control directory",
        )
        if self.path.is_symlink():
            raise ValueError("extension registry must not be a symbolic link")
        if self.audit_path.is_symlink():
            raise ValueError("extension audit database must not be a symbolic link")

    def _initialize_audit(self) -> None:
        self._assert_control_files_safe()
        with sqlite3.connect(self.audit_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS extension_audit("
                "event_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "action TEXT NOT NULL, extension_id TEXT NOT NULL,"
                "kind TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS extension_invocation_audit("
                "event_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "invocation_id TEXT NOT NULL UNIQUE,"
                "extension_id TEXT NOT NULL, tool_name TEXT NOT NULL,"
                "status TEXT NOT NULL, error_code TEXT, duration_ms INTEGER NOT NULL,"
                "argument_bytes INTEGER NOT NULL, result_bytes INTEGER NOT NULL,"
                "schema_hash TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS extension_invocation_lookup "
                "ON extension_invocation_audit(extension_id, event_id DESC)"
            )

    def _audit(self, action: str, extension_id: str, kind: str) -> None:
        self._assert_control_files_safe()
        with sqlite3.connect(self.audit_path) as connection:
            connection.execute(
                "INSERT INTO extension_audit(action, extension_id, kind, created_at) "
                "VALUES (?, ?, ?, ?)",
                (action, extension_id, kind, time.time()),
            )


def _string_array(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError(f"{name} must be an array of strings")
    return tuple(value)


def _identifiers(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an array")
    result = tuple(sorted(dict.fromkeys(values)))
    if any(_ID.fullmatch(item) is None for item in result):
        raise ValueError(f"{name} contains an invalid identifier")
    return result


def _paths(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an array")
    return tuple(sorted(dict.fromkeys(_relative_path(item, name) for item in values)))


def _relative_path(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"{name} must be a bounded relative path")
    path = PurePosixPath(value.strip().replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must stay inside the workspace")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ValueError(f"{name} must be a bounded relative path")
    return normalized


def _public_object(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    _reject_private_fields(value, name)
    try:
        decoded = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{name} must serialize to an object")
    return decoded


def _reject_private_fields(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            if key in _PRIVATE_KEYS:
                raise ValueError(f"private field is forbidden: {path}.{raw_key}")
            _reject_private_fields(child, f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_private_fields(child, f"{path}[{index}]")


__all__ = [
    "ExtensionKind",
    "ExtensionPermissions",
    "ExtensionRegistrySnapshot",
    "ProjectExtensionDescriptor",
    "ProjectExtensionRegistry",
    "TrustSource",
]
