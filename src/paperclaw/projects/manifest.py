"""Safe workspace-local PaperClaw project manifest."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

_MANIFEST_RELATIVE_PATH = Path(".paperclaw") / "project.json"
_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_CAPABILITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_ALLOWED_FIELDS = frozenset(
    {
        "schema_version",
        "project_id",
        "name",
        "instruction_files",
        "knowledge_paths",
        "enabled_skills",
        "enabled_connectors",
        "data_directory",
    }
)
_SENSITIVE_FIELDS = frozenset(
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
_DEFAULT_INSTRUCTIONS = ("PAPERCLAW.md", "CLAUDE.md", "AGENTS.md")


@dataclass(frozen=True)
class ProjectValidationIssue:
    code: str
    message: str
    path: str | None = None
    severity: str = "error"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class ProjectValidationReport:
    workspace: str
    manifest_path: str
    issues: tuple[ProjectValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "workspace": self.workspace,
            "manifest_path": self.manifest_path,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class ProjectManifest:
    schema_version: int
    project_id: str
    name: str
    instruction_files: tuple[str, ...] = _DEFAULT_INSTRUCTIONS
    knowledge_paths: tuple[str, ...] = ()
    enabled_skills: tuple[str, ...] = ()
    enabled_connectors: tuple[str, ...] = ()
    data_directory: str = ".paperclaw/data"

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise ValueError("unsupported project manifest schema_version")
        if not isinstance(self.project_id, str) or _PROJECT_ID.fullmatch(
            self.project_id
        ) is None:
            raise ValueError("invalid project_id")
        if (
            not isinstance(self.name, str)
            or not self.name.strip()
            or len(self.name) > 200
        ):
            raise ValueError("project name must be 1-200 characters")
        instructions = _normalize_paths(self.instruction_files, "instruction_files")
        knowledge = _normalize_paths(self.knowledge_paths, "knowledge_paths")
        skills = _normalize_ids(self.enabled_skills, "enabled_skills")
        connectors = _normalize_ids(self.enabled_connectors, "enabled_connectors")
        data_directory = _normalize_relative_path(
            self.data_directory, "data_directory"
        )
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "instruction_files", instructions)
        object.__setattr__(self, "knowledge_paths", knowledge)
        object.__setattr__(self, "enabled_skills", skills)
        object.__setattr__(self, "enabled_connectors", connectors)
        object.__setattr__(self, "data_directory", data_directory)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "instruction_files": list(self.instruction_files),
            "knowledge_paths": list(self.knowledge_paths),
            "enabled_skills": list(self.enabled_skills),
            "enabled_connectors": list(self.enabled_connectors),
            "data_directory": self.data_directory,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectManifest":
        if not isinstance(value, Mapping):
            raise ValueError("project manifest must be a JSON object")
        unknown = set(value) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"unknown project manifest fields: {sorted(unknown)}")
        _reject_sensitive_fields(value, "project")
        required = {"schema_version", "project_id", "name"}
        missing = required - set(value)
        if missing:
            raise ValueError(f"missing project manifest fields: {sorted(missing)}")
        return cls(
            schema_version=value["schema_version"],
            project_id=value["project_id"],
            name=value["name"],
            instruction_files=_array(
                value.get("instruction_files", _DEFAULT_INSTRUCTIONS),
                "instruction_files",
            ),
            knowledge_paths=_array(
                value.get("knowledge_paths", ()), "knowledge_paths"
            ),
            enabled_skills=_array(
                value.get("enabled_skills", ()), "enabled_skills"
            ),
            enabled_connectors=_array(
                value.get("enabled_connectors", ()), "enabled_connectors"
            ),
            data_directory=value.get("data_directory", ".paperclaw/data"),
        )


class ProjectManifestStore:
    def __init__(
        self,
        workspace: str | Path,
        *,
        max_manifest_bytes: int = 262_144,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("workspace must be a directory")
        if max_manifest_bytes < 1:
            raise ValueError("max_manifest_bytes must be positive")
        self.max_manifest_bytes = max_manifest_bytes
        self.path = self.workspace / _MANIFEST_RELATIVE_PATH

    @property
    def exists(self) -> bool:
        return self.path.is_file() and not self.path.is_symlink()

    def initialize(self, name: str, *, force: bool = False) -> ProjectManifest:
        project_id = _slug(name)
        manifest = ProjectManifest(
            schema_version=1,
            project_id=project_id,
            name=name,
        )
        self.save(manifest, overwrite=force)
        return manifest

    def save(self, manifest: ProjectManifest, *, overwrite: bool = True) -> None:
        self._assert_manifest_path_safe()
        if self.path.exists() and not overwrite:
            raise FileExistsError(f"project manifest already exists: {self.path}")
        encoded = (
            json.dumps(
                manifest.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if len(encoded) > self.max_manifest_bytes:
            raise ValueError("project manifest exceeds configured byte limit")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(encoded)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self) -> ProjectManifest:
        self._assert_manifest_path_safe()
        raw = self.path.read_bytes()
        if len(raw) > self.max_manifest_bytes:
            raise ValueError("project manifest exceeds configured byte limit")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("project manifest is not valid UTF-8 JSON") from exc
        return ProjectManifest.from_dict(value)

    def validate(self, manifest: ProjectManifest | None = None) -> ProjectValidationReport:
        resolved = manifest or self.load()
        issues: list[ProjectValidationIssue] = []
        for relative in resolved.instruction_files:
            path = self.resolve(relative)
            if not path.exists():
                issues.append(
                    ProjectValidationIssue(
                        "instruction_missing",
                        "declared instruction file does not exist",
                        relative,
                        "warning",
                    )
                )
            elif not path.is_file():
                issues.append(
                    ProjectValidationIssue(
                        "instruction_not_file",
                        "declared instruction path is not a file",
                        relative,
                    )
                )
        for relative in resolved.knowledge_paths:
            path = self.resolve(relative)
            if not path.exists():
                issues.append(
                    ProjectValidationIssue(
                        "knowledge_missing",
                        "declared knowledge path does not exist",
                        relative,
                    )
                )
            elif not (path.is_file() or path.is_dir()):
                issues.append(
                    ProjectValidationIssue(
                        "knowledge_unsupported",
                        "knowledge path must be a regular file or directory",
                        relative,
                    )
                )
        try:
            data_directory = self.resolve(resolved.data_directory)
            if data_directory.exists() and not data_directory.is_dir():
                issues.append(
                    ProjectValidationIssue(
                        "data_directory_not_directory",
                        "project data_directory is not a directory",
                        resolved.data_directory,
                    )
                )
        except ValueError as exc:
            issues.append(
                ProjectValidationIssue(
                    "data_directory_outside_workspace",
                    str(exc),
                    resolved.data_directory,
                )
            )
        return ProjectValidationReport(
            workspace=str(self.workspace),
            manifest_path=str(self.path),
            issues=tuple(issues),
        )

    def resolve(self, relative: str) -> Path:
        normalized = _normalize_relative_path(relative, "declared path")
        unresolved = self.workspace / Path(normalized)
        resolved = unresolved.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("declared path escapes workspace") from exc
        if unresolved.is_symlink():
            try:
                unresolved.resolve(strict=True).relative_to(self.workspace)
            except (FileNotFoundError, ValueError) as exc:
                raise ValueError(
                    "declared symlink escapes workspace or is broken"
                ) from exc
        return resolved

    def _assert_manifest_path_safe(self) -> None:
        if self.path.is_symlink():
            raise ValueError("project manifest must not be a symbolic link")
        parent = self.path.parent.resolve(strict=False)
        try:
            parent.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("project manifest path escapes workspace") from exc


def discover_project_manifest(workspace: str | Path) -> ProjectManifest | None:
    store = ProjectManifestStore(workspace)
    return store.load() if store.exists else None


def _array(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    if any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must contain strings")
    return tuple(value)


def _normalize_paths(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an array")
    return tuple(
        dict.fromkeys(_normalize_relative_path(value, name) for value in values)
    )


def _normalize_ids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an array")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or _CAPABILITY_ID.fullmatch(value) is None:
            raise ValueError(f"invalid value in {name}")
        normalized.append(value)
    return tuple(sorted(dict.fromkeys(normalized)))


def _normalize_relative_path(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"{name} must contain bounded non-empty relative paths")
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or "." == normalized:
        raise ValueError(f"{name} must stay inside the workspace")
    if any(part in {"", "."} for part in path.parts):
        raise ValueError(f"{name} contains an invalid path segment")
    return path.as_posix()


def _slug(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("project name must not be empty")
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        slug = "paperclaw-project"
    return slug[:128]


def _reject_sensitive_fields(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            if key in _SENSITIVE_FIELDS:
                raise ValueError(
                    f"project manifest contains secret field: {path}.{raw_key}"
                )
            _reject_sensitive_fields(child, f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, f"{path}[{index}]")


__all__ = [
    "ProjectManifest",
    "ProjectManifestStore",
    "ProjectValidationIssue",
    "ProjectValidationReport",
    "discover_project_manifest",
]
