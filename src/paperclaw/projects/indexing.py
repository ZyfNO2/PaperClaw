"""Deterministic local project-knowledge index lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable
from uuid import uuid4

from paperclaw.retrieval import IncrementalIndexer

from .manifest import ProjectManifest, ProjectManifestStore

_SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
_INDEX_DATABASE = "project-knowledge.sqlite3"
_INDEX_METADATA = "project-index.json"


@dataclass(frozen=True)
class ProjectKnowledgeFile:
    relative_path: str
    byte_length: int
    sha256: str

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
    source_fingerprint: str
    indexed_files: tuple[ProjectKnowledgeFile, ...]

    @property
    def file_count(self) -> int:
        return len(self.indexed_files)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "database": self.database,
            "source_fingerprint": self.source_fingerprint,
            "file_count": self.file_count,
            "indexed_files": [item.to_dict() for item in self.indexed_files],
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ProjectIndexReport":
        if value.get("schema_version") != 1:
            raise ValueError("unsupported project index metadata schema")
        raw_files = value.get("indexed_files")
        if not isinstance(raw_files, list):
            raise ValueError("project index metadata indexed_files must be an array")
        files: list[ProjectKnowledgeFile] = []
        for raw in raw_files:
            if not isinstance(raw, dict):
                raise ValueError("invalid project index file metadata")
            files.append(
                ProjectKnowledgeFile(
                    relative_path=str(raw.get("relative_path") or ""),
                    byte_length=int(raw.get("byte_length") or 0),
                    sha256=str(raw.get("sha256") or ""),
                )
            )
        return cls(
            schema_version=1,
            project_id=str(value.get("project_id") or ""),
            database=str(value.get("database") or ""),
            source_fingerprint=str(value.get("source_fingerprint") or ""),
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

    fingerprint = _source_fingerprint(item for item, _content in files)
    report = ProjectIndexReport(
        schema_version=1,
        project_id=manifest.project_id,
        database=target.relative_to(store.workspace).as_posix(),
        source_fingerprint=fingerprint,
        indexed_files=tuple(item for item, _content in files),
    )
    metadata = data_directory / _INDEX_METADATA
    _atomic_json_write(metadata, report.to_dict())
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
    if not database.is_file() or not metadata.is_file():
        return ProjectIndexStatus(
            available=False,
            current=False,
            reason="index_missing",
            database=relative_database,
        )
    try:
        value = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object")
        report = ProjectIndexReport.from_dict(value)
        files = collect_project_knowledge_files(
            store,
            manifest,
            max_file_bytes=max_file_bytes,
        )
        expected = _source_fingerprint(item for item, _content in files)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
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
            expected_fingerprint=expected,
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
    return store.resolve(manifest.data_directory) / _INDEX_DATABASE


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
        # Validate UTF-8 before handing bytes to the existing parser.
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


def _atomic_json_write(path: Path, value: dict[str, object]) -> None:
    encoded = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "ProjectIndexReport",
    "ProjectIndexStatus",
    "ProjectKnowledgeFile",
    "build_project_index",
    "collect_project_knowledge_files",
    "inspect_project_index",
    "project_index_database",
]
