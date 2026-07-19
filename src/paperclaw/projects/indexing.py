"""Deterministic local project-knowledge index lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Iterable
from uuid import uuid4

from paperclaw.retrieval import IncrementalIndexer
from paperclaw.storage_safety import atomic_write_bytes

from .manifest import ProjectManifest, ProjectManifestStore

_SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
_INDEX_DATABASE = "project-knowledge.sqlite3"
_INDEX_METADATA = "project-index.json"
_INDEX_SCHEMA_VERSION = 2
_MAX_INDEX_METADATA_BYTES = 1_048_576
_MAX_INDEXED_FILES = 100_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class ProjectKnowledgeFile:
    relative_path: str
    byte_length: int
    sha256: str

    def __post_init__(self) -> None:
        normalized = _safe_relative_path(self.relative_path, "indexed file path")
        if (
            isinstance(self.byte_length, bool)
            or not isinstance(self.byte_length, int)
            or self.byte_length < 0
        ):
            raise ValueError("indexed file byte_length must be non-negative")
        _require_sha256(self.sha256, "indexed file sha256")
        object.__setattr__(self, "relative_path", normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ProjectIndexReport:
    schema_version: int
    project_id: str
    database: str
    database_sha256: str
    source_fingerprint: str
    indexed_files: tuple[ProjectKnowledgeFile, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or self.schema_version != _INDEX_SCHEMA_VERSION
        ):
            raise ValueError("unsupported project index metadata schema")
        if not isinstance(self.project_id, str) or _PROJECT_ID.fullmatch(
            self.project_id
        ) is None:
            raise ValueError("invalid project index project_id")
        database = _safe_relative_path(self.database, "project index database")
        if not database.endswith(f"/{_INDEX_DATABASE}") and database != _INDEX_DATABASE:
            raise ValueError("project index database path is unexpected")
        _require_sha256(self.database_sha256, "project index database_sha256")
        _require_sha256(self.source_fingerprint, "project index source_fingerprint")
        if not isinstance(self.indexed_files, tuple):
            raise ValueError("project index indexed_files must be an array")
        if len(self.indexed_files) > _MAX_INDEXED_FILES:
            raise ValueError("project index metadata contains too many files")
        paths = tuple(item.relative_path for item in self.indexed_files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("project index file metadata must be sorted and unique")
        if _source_fingerprint(self.indexed_files) != self.source_fingerprint:
            raise ValueError("project index source fingerprint does not match file metadata")
        object.__setattr__(self, "database", database)

    @property
    def file_count(self) -> int:
        return len(self.indexed_files)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "database": self.database,
            "database_sha256": self.database_sha256,
            "source_fingerprint": self.source_fingerprint,
            "file_count": self.file_count,
            "indexed_files": [item.to_dict() for item in self.indexed_files],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ProjectIndexReport":
        if not isinstance(value, dict):
            raise ValueError("project index metadata must be an object")
        allowed = {
            "schema_version",
            "project_id",
            "database",
            "database_sha256",
            "source_fingerprint",
            "file_count",
            "indexed_files",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown project index metadata fields: {sorted(unknown)}")
        if value.get("schema_version") != _INDEX_SCHEMA_VERSION:
            raise ValueError("unsupported project index metadata schema")
        raw_files = value.get("indexed_files")
        if not isinstance(raw_files, list):
            raise ValueError("project index metadata indexed_files must be an array")
        if len(raw_files) > _MAX_INDEXED_FILES:
            raise ValueError("project index metadata contains too many files")
        files: list[ProjectKnowledgeFile] = []
        for raw in raw_files:
            if not isinstance(raw, dict) or set(raw) != {
                "relative_path",
                "byte_length",
                "sha256",
            }:
                raise ValueError("invalid project index file metadata")
            relative_path = raw["relative_path"]
            byte_length = raw["byte_length"]
            sha256 = raw["sha256"]
            if not isinstance(relative_path, str) or not isinstance(sha256, str):
                raise ValueError("invalid project index file metadata types")
            files.append(
                ProjectKnowledgeFile(
                    relative_path=relative_path,
                    byte_length=byte_length,
                    sha256=sha256,
                )
            )
        file_count = value.get("file_count")
        if (
            isinstance(file_count, bool)
            or not isinstance(file_count, int)
            or file_count != len(files)
        ):
            raise ValueError("project index file_count is invalid")
        project_id = value.get("project_id")
        database = value.get("database")
        database_sha256 = value.get("database_sha256")
        source_fingerprint = value.get("source_fingerprint")
        if not all(
            isinstance(item, str)
            for item in (
                project_id,
                database,
                database_sha256,
                source_fingerprint,
            )
        ):
            raise ValueError("project index metadata has invalid field types")
        return cls(
            schema_version=_INDEX_SCHEMA_VERSION,
            project_id=project_id,
            database=database,
            database_sha256=database_sha256,
            source_fingerprint=source_fingerprint,
            indexed_files=tuple(files),
        )


@dataclass(frozen=True)
class ProjectIndexStatus:
    available: bool
    current: bool
    reason: str
    database: str
    expected_fingerprint: str | None = None
    indexed_fingerprint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "current": self.current,
            "reason": self.reason,
            "database": self.database,
            "expected_fingerprint": self.expected_fingerprint,
            "indexed_fingerprint": self.indexed_fingerprint,
        }


def build_project_index(
    store: ProjectManifestStore,
    manifest: ProjectManifest,
    *,
    max_file_bytes: int = 5_000_000,
) -> ProjectIndexReport:
    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")
    files = collect_project_knowledge_files(
        store,
        manifest,
        max_file_bytes=max_file_bytes,
    )
    data_directory = store.resolve(manifest.data_directory)
    data_directory.mkdir(parents=True, exist_ok=True)
    target = data_directory / _INDEX_DATABASE
    metadata = data_directory / _INDEX_METADATA
    if target.is_symlink() or metadata.is_symlink():
        raise ValueError("project index files must not be symbolic links")
    temporary = data_directory / f".{_INDEX_DATABASE}.{uuid4().hex}.tmp"
    _remove_sqlite_files(temporary)
    try:
        with IncrementalIndexer(temporary) as indexer:
            for item, content in files:
                source_path = store.resolve(item.relative_path)
                indexer.index_bytes(
                    canonical_uri=source_path.as_uri(),
                    display_name=item.relative_path,
                    media_type=(
                        "text/markdown"
                        if source_path.suffix.lower() in {".md", ".markdown"}
                        else "text/plain"
                    ),
                    content=content,
                )
        _checkpoint_sqlite(temporary)
        _remove_sqlite_sidecars(target)
        os.replace(temporary, target)
    finally:
        _remove_sqlite_files(temporary)

    indexed_files = tuple(item for item, _content in files)
    report = ProjectIndexReport(
        schema_version=_INDEX_SCHEMA_VERSION,
        project_id=manifest.project_id,
        database=target.relative_to(store.workspace).as_posix(),
        database_sha256=_sha256_file(target),
        source_fingerprint=_source_fingerprint(indexed_files),
        indexed_files=indexed_files,
    )
    _atomic_json_write(metadata, report.to_dict(), workspace=store.workspace)
    return report


def inspect_project_index(
    store: ProjectManifestStore,
    manifest: ProjectManifest,
    *,
    max_file_bytes: int = 5_000_000,
) -> ProjectIndexStatus:
    data_directory = store.resolve(manifest.data_directory)
    database = data_directory / _INDEX_DATABASE
    metadata = data_directory / _INDEX_METADATA
    relative_database = database.relative_to(store.workspace).as_posix()
    if database.is_symlink() or metadata.is_symlink():
        return ProjectIndexStatus(
            available=database.exists() or metadata.exists() or database.is_symlink() or metadata.is_symlink(),
            current=False,
            reason="index_path_symlink",
            database=relative_database,
        )
    if not database.is_file() or not metadata.is_file():
        return ProjectIndexStatus(
            available=False,
            current=False,
            reason="index_missing",
            database=relative_database,
        )
    try:
        raw_metadata = metadata.read_bytes()
        if len(raw_metadata) > _MAX_INDEX_METADATA_BYTES:
            raise ValueError("project index metadata exceeds byte limit")
        value = json.loads(raw_metadata.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object")
        report = ProjectIndexReport.from_dict(value)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        return ProjectIndexStatus(
            available=True,
            current=False,
            reason=f"index_metadata_invalid:{type(exc).__name__}",
            database=relative_database,
        )
    if report.project_id != manifest.project_id:
        return ProjectIndexStatus(
            available=True,
            current=False,
            reason="project_id_mismatch",
            database=relative_database,
            indexed_fingerprint=report.source_fingerprint,
        )
    if report.database != relative_database:
        return ProjectIndexStatus(
            available=True,
            current=False,
            reason="index_database_path_mismatch",
            database=relative_database,
            indexed_fingerprint=report.source_fingerprint,
        )
    try:
        database_sha256 = _sha256_file(database)
    except OSError as exc:
        return ProjectIndexStatus(
            available=True,
            current=False,
            reason=f"index_database_invalid:{type(exc).__name__}",
            database=relative_database,
            indexed_fingerprint=report.source_fingerprint,
        )
    if database_sha256 != report.database_sha256:
        return ProjectIndexStatus(
            available=True,
            current=False,
            reason="index_database_mismatch",
            database=relative_database,
            indexed_fingerprint=report.source_fingerprint,
        )
    try:
        files = collect_project_knowledge_files(
            store,
            manifest,
            max_file_bytes=max_file_bytes,
        )
        expected = _source_fingerprint(item for item, _content in files)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return ProjectIndexStatus(
            available=True,
            current=False,
            reason=f"index_source_invalid:{type(exc).__name__}",
            database=relative_database,
            indexed_fingerprint=report.source_fingerprint,
        )
    current = report.source_fingerprint == expected
    return ProjectIndexStatus(
        available=True,
        current=current,
        reason="current" if current else "index_stale",
        database=relative_database,
        expected_fingerprint=expected,
        indexed_fingerprint=report.source_fingerprint,
    )


def project_index_database(
    store: ProjectManifestStore,
    manifest: ProjectManifest,
) -> Path:
    database = store.resolve(manifest.data_directory) / _INDEX_DATABASE
    if database.is_symlink():
        raise ValueError("project index database must not be a symbolic link")
    return database


def collect_project_knowledge_files(
    store: ProjectManifestStore,
    manifest: ProjectManifest,
    *,
    max_file_bytes: int,
) -> tuple[tuple[ProjectKnowledgeFile, bytes], ...]:
    selected: dict[str, Path] = {}
    for declared in manifest.knowledge_paths:
        root = store.resolve(declared)
        candidates: Iterable[Path]
        if root.is_file():
            candidates = (root,)
        elif root.is_dir():
            candidates = sorted(
                (item for item in root.rglob("*") if item.is_file()),
                key=lambda item: item.as_posix(),
            )
        else:
            raise ValueError(f"knowledge path is not indexable: {declared}")
        for candidate in candidates:
            resolved = candidate.resolve(strict=True)
            try:
                relative = resolved.relative_to(store.workspace).as_posix()
            except ValueError as exc:
                raise ValueError("knowledge file escapes workspace") from exc
            if candidate.is_symlink() and resolved != candidate.absolute():
                try:
                    resolved.relative_to(store.workspace)
                except ValueError as exc:
                    raise ValueError("knowledge symlink escapes workspace") from exc
            if resolved.suffix.lower() not in _SUPPORTED_SUFFIXES:
                continue
            selected[relative] = resolved

    output: list[tuple[ProjectKnowledgeFile, bytes]] = []
    for relative, path in sorted(selected.items()):
        content = path.read_bytes()
        if len(content) > max_file_bytes:
            raise ValueError(f"knowledge file exceeds byte limit: {relative}")
        content.decode("utf-8")
        output.append(
            (
                ProjectKnowledgeFile(
                    relative_path=relative,
                    byte_length=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                ),
                content,
            )
        )
    return tuple(output)


def _source_fingerprint(files: Iterable[ProjectKnowledgeFile]) -> str:
    payload = [item.to_dict() for item in sorted(files, key=lambda item: item.relative_path)]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def _remove_sqlite_sidecars(path: Path) -> None:
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    _remove_sqlite_sidecars(path)


def _atomic_json_write(
    path: Path,
    value: dict[str, object],
    *,
    workspace: Path,
) -> None:
    encoded = (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(encoded) > _MAX_INDEX_METADATA_BYTES:
        raise ValueError("project index metadata exceeds byte limit")
    atomic_write_bytes(
        path,
        encoded,
        overwrite=True,
        confinement_root=workspace,
    )


def _safe_relative_path(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"{name} must be a bounded relative path")
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or any(
        part in {"", "."} for part in path.parts
    ):
        raise ValueError(f"{name} must stay inside the workspace")
    return path.as_posix()


def _require_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")


__all__ = [
    "ProjectIndexReport",
    "ProjectIndexStatus",
    "ProjectKnowledgeFile",
    "build_project_index",
    "collect_project_knowledge_files",
    "inspect_project_index",
    "project_index_database",
]
