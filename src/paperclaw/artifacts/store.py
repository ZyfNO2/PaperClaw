"""Append-only Artifact metadata with content-addressed local blobs."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import time
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from .contracts import (
    ArtifactBundle,
    ArtifactCapacityError,
    ArtifactConflictError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactRecord,
    ArtifactRevision,
    ArtifactSourceLinks,
    normalize_metadata,
)


class ArtifactStore(Protocol):
    def create_artifact(self, **kwargs) -> tuple[ArtifactRecord, ArtifactRevision, bool]: ...
    def add_revision(self, artifact_id: str, **kwargs) -> tuple[ArtifactRevision, bool]: ...
    def get_artifact(self, artifact_id: str) -> ArtifactRecord: ...
    def get_bundle(self, artifact_id: str) -> ArtifactBundle: ...
    def read_revision(self, artifact_id: str, revision_number: int | None = None) -> bytes: ...


class FileArtifactStore:
    def __init__(
        self,
        root: str | Path,
        *,
        max_content_bytes: int = 16_777_216,
        max_metadata_bytes: int = 65_536,
        busy_timeout_ms: int = 10_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_content_bytes < 1 or max_metadata_bytes < 1 or busy_timeout_ms < 1:
            raise ValueError("artifact store bounds must be positive")
        candidate = Path(root).expanduser()
        if candidate.exists() and candidate.is_symlink():
            raise ValueError("artifact root must not be a symbolic link")
        self.root = candidate.resolve(strict=False)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "artifacts.sqlite3"
        self.blob_root = self.root / "blobs" / "sha256"
        self.max_content_bytes = max_content_bytes
        self.max_metadata_bytes = max_metadata_bytes
        self._busy_timeout_ms = busy_timeout_ms
        self._clock = clock
        self._initialize()

    def create_artifact(
        self,
        *,
        idempotency_key: str,
        artifact_type: str,
        title: str,
        media_type: str,
        content: bytes,
        source: ArtifactSourceLinks | None = None,
        metadata: Mapping[str, Any] | None = None,
        revision_message: str | None = "initial revision",
    ) -> tuple[ArtifactRecord, ArtifactRevision, bool]:
        key = _bounded_idempotency_key(idempotency_key)
        normalized_content = self._content(content)
        normalized_metadata = normalize_metadata(
            metadata or {}, max_bytes=self.max_metadata_bytes
        )
        normalized_source = source or ArtifactSourceLinks()
        content_hash = hashlib.sha256(normalized_content).hexdigest()
        digest = _digest(
            {
                "artifact_type": artifact_type,
                "title": title,
                "media_type": media_type,
                "content_hash": content_hash,
                "source": normalized_source.to_dict(),
                "metadata": normalized_metadata,
                "revision_message": revision_message,
            }
        )
        scope_key = f"create:{key}"
        self._ensure_blob(content_hash, normalized_content)
        now = self._clock()
        with self._transaction() as connection:
            existing = self._idempotency_locked(connection, scope_key)
            if existing is not None:
                self._assert_digest(existing, digest)
                artifact = self._artifact_locked(connection, existing["result_id"])
                revision = self._revision_locked(
                    connection, artifact.artifact_id, 1
                )
                return artifact, revision, False

            artifact_id = f"artifact-{uuid4().hex}"
            revision_id = f"revision-{uuid4().hex}"
            # Construct contracts before writing so type/media/title validation
            # fails before durable metadata mutation.
            artifact = ArtifactRecord(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                title=title,
                created_at=now,
                updated_at=now,
                latest_revision_number=1,
                source=normalized_source,
                metadata=normalized_metadata,
            )
            revision = ArtifactRevision(
                revision_id=revision_id,
                artifact_id=artifact_id,
                revision_number=1,
                content_hash=content_hash,
                byte_length=len(normalized_content),
                media_type=media_type,
                created_at=now,
                message=revision_message,
                metadata={},
            )
            connection.execute(
                """
                INSERT INTO product_artifacts(
                    artifact_id, artifact_type, title, created_at, updated_at,
                    latest_revision_number, source_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.artifact_type,
                    artifact.title,
                    artifact.created_at,
                    artifact.updated_at,
                    artifact.latest_revision_number,
                    _json_dump(artifact.source.to_dict()),
                    _json_dump(artifact.to_dict()["metadata"]),
                ),
            )
            self._insert_revision(connection, revision)
            self._insert_idempotency(
                connection, scope_key, digest, "artifact", artifact_id, now
            )
            return artifact, revision, True

    def add_revision(
        self,
        artifact_id: str,
        *,
        idempotency_key: str,
        media_type: str,
        content: bytes,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ArtifactRevision, bool]:
        artifact_key = _bounded_identifier(artifact_id, "artifact_id")
        key = _bounded_idempotency_key(idempotency_key)
        normalized_content = self._content(content)
        normalized_metadata = normalize_metadata(
            metadata or {}, max_bytes=self.max_metadata_bytes
        )
        content_hash = hashlib.sha256(normalized_content).hexdigest()
        digest = _digest(
            {
                "artifact_id": artifact_key,
                "media_type": media_type,
                "content_hash": content_hash,
                "message": message,
                "metadata": normalized_metadata,
            }
        )
        scope_key = f"revise:{artifact_key}:{key}"
        self._ensure_blob(content_hash, normalized_content)
        now = self._clock()
        with self._transaction() as connection:
            existing = self._idempotency_locked(connection, scope_key)
            if existing is not None:
                self._assert_digest(existing, digest)
                revision = self._revision_by_id_locked(
                    connection, existing["result_id"]
                )
                return revision, False

            artifact = self._artifact_locked(connection, artifact_key)
            revision_number = artifact.latest_revision_number + 1
            revision = ArtifactRevision(
                revision_id=f"revision-{uuid4().hex}",
                artifact_id=artifact_key,
                revision_number=revision_number,
                content_hash=content_hash,
                byte_length=len(normalized_content),
                media_type=media_type,
                created_at=now,
                message=message,
                metadata=normalized_metadata,
            )
            self._insert_revision(connection, revision)
            cursor = connection.execute(
                """
                UPDATE product_artifacts
                SET latest_revision_number = ?, updated_at = ?
                WHERE artifact_id = ? AND latest_revision_number = ?
                """,
                (
                    revision_number,
                    now,
                    artifact_key,
                    artifact.latest_revision_number,
                ),
            )
            if cursor.rowcount != 1:
                raise ArtifactConflictError(
                    "artifact revision changed during append"
                )
            self._insert_idempotency(
                connection,
                scope_key,
                digest,
                "revision",
                revision.revision_id,
                now,
            )
            return revision, True

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        with self._connection() as connection:
            return self._artifact_locked(
                connection, _bounded_identifier(artifact_id, "artifact_id")
            )

    def get_revision(
        self,
        artifact_id: str,
        revision_number: int | None = None,
    ) -> ArtifactRevision:
        artifact_key = _bounded_identifier(artifact_id, "artifact_id")
        with self._connection() as connection:
            artifact = self._artifact_locked(connection, artifact_key)
            number = revision_number or artifact.latest_revision_number
            return self._revision_locked(connection, artifact_key, number)

    def get_bundle(self, artifact_id: str) -> ArtifactBundle:
        artifact_key = _bounded_identifier(artifact_id, "artifact_id")
        with self._connection() as connection:
            artifact = self._artifact_locked(connection, artifact_key)
            rows = connection.execute(
                """
                SELECT * FROM product_artifact_revisions
                WHERE artifact_id = ? ORDER BY revision_number ASC
                """,
                (artifact_key,),
            ).fetchall()
            revisions = tuple(self._revision_from_row(row) for row in rows)
            return ArtifactBundle(artifact, revisions)

    def list_artifacts(
        self,
        *,
        artifact_type: str | None = None,
        project_id: str | None = None,
        limit: int = 200,
    ) -> tuple[ArtifactRecord, ...]:
        if not 1 <= limit <= 5_000:
            raise ValueError("limit must be in [1, 5000]")
        query = "SELECT * FROM product_artifacts WHERE 1 = 1"
        params: list[object] = []
        if artifact_type is not None:
            query += " AND artifact_type = ?"
            params.append(artifact_type)
        if project_id is not None:
            _bounded_identifier(project_id, "project_id")
            query += " AND json_extract(source_json, '$.project_id') = ?"
            params.append(project_id)
        query += " ORDER BY updated_at DESC, artifact_id ASC LIMIT ?"
        params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
            return tuple(self._artifact_from_row(row) for row in rows)

    def read_revision(
        self,
        artifact_id: str,
        revision_number: int | None = None,
    ) -> bytes:
        revision = self.get_revision(artifact_id, revision_number)
        path = self._blob_path(revision.content_hash)
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactIntegrityError("artifact blob is missing") from exc
        if len(content) != revision.byte_length:
            raise ArtifactIntegrityError("artifact blob byte length mismatch")
        if hashlib.sha256(content).hexdigest() != revision.content_hash:
            raise ArtifactIntegrityError("artifact blob hash mismatch")
        return content

    def export_revision(
        self,
        artifact_id: str,
        destination_root: str | Path,
        relative_path: str,
        *,
        revision_number: int | None = None,
        overwrite: bool = False,
    ) -> Path:
        root = Path(destination_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("destination_root must be a directory")
        normalized = _relative_path(relative_path)
        target = (root / Path(normalized)).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("artifact export path escapes destination root") from exc
        if target.is_symlink():
            raise ValueError("artifact export target must not be a symbolic link")
        if target.exists() and not overwrite:
            raise FileExistsError(f"artifact export target exists: {target}")
        content = self.read_revision(artifact_id, revision_number)
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = target.parent.resolve(strict=True)
        try:
            resolved_parent.relative_to(root)
        except ValueError as exc:
            raise ValueError("artifact export parent escapes destination root") from exc
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(content)
            if target.exists() and not overwrite:
                raise FileExistsError(f"artifact export target exists: {target}")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def _content(self, content: bytes) -> bytes:
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")
        if len(content) > self.max_content_bytes:
            raise ArtifactCapacityError("artifact content exceeds byte limit")
        return content

    def _ensure_blob(self, content_hash: str, content: bytes) -> None:
        path = self._blob_path(content_hash)
        if path.exists():
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != content_hash:
                raise ArtifactIntegrityError("existing artifact blob is corrupt")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            except OSError:
                if not path.exists():
                    os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        if hashlib.sha256(path.read_bytes()).hexdigest() != content_hash:
            raise ArtifactIntegrityError("persisted artifact blob hash mismatch")

    def _blob_path(self, content_hash: str) -> Path:
        return self.blob_root / content_hash[:2] / content_hash

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS product_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    latest_revision_number INTEGER NOT NULL CHECK(latest_revision_number >= 1),
                    source_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_artifact_revisions (
                    revision_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL REFERENCES product_artifacts(artifact_id),
                    revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
                    content_hash TEXT NOT NULL,
                    byte_length INTEGER NOT NULL CHECK(byte_length >= 0),
                    media_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    message TEXT,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(artifact_id, revision_number)
                );

                CREATE INDEX IF NOT EXISTS idx_product_artifacts_updated
                ON product_artifacts(updated_at DESC, artifact_id);

                CREATE INDEX IF NOT EXISTS idx_product_revisions_artifact
                ON product_artifact_revisions(artifact_id, revision_number);

                CREATE TABLE IF NOT EXISTS product_artifact_idempotency (
                    scope_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    result_kind TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(
            self.database,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _artifact_locked(
        self, connection: sqlite3.Connection, artifact_id: str
    ) -> ArtifactRecord:
        row = connection.execute(
            "SELECT * FROM product_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(f"artifact not found: {artifact_id}")
        return self._artifact_from_row(row)

    def _revision_locked(
        self,
        connection: sqlite3.Connection,
        artifact_id: str,
        revision_number: int,
    ) -> ArtifactRevision:
        if isinstance(revision_number, bool) or revision_number < 1:
            raise ValueError("revision_number must be positive")
        row = connection.execute(
            """
            SELECT * FROM product_artifact_revisions
            WHERE artifact_id = ? AND revision_number = ?
            """,
            (artifact_id, revision_number),
        ).fetchone()
        if row is None:
            raise ArtifactNotFoundError(
                f"artifact revision not found: {artifact_id}@{revision_number}"
            )
        return self._revision_from_row(row)

    def _revision_by_id_locked(
        self, connection: sqlite3.Connection, revision_id: str
    ) -> ArtifactRevision:
        row = connection.execute(
            "SELECT * FROM product_artifact_revisions WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ArtifactIntegrityError("idempotency revision result is missing")
        return self._revision_from_row(row)

    def _artifact_from_row(self, row: sqlite3.Row) -> ArtifactRecord:
        source = json.loads(row["source_json"])
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            artifact_type=row["artifact_type"],
            title=row["title"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            latest_revision_number=int(row["latest_revision_number"]),
            source=ArtifactSourceLinks(**source),
            metadata=json.loads(row["metadata_json"]),
        )

    def _revision_from_row(self, row: sqlite3.Row) -> ArtifactRevision:
        return ArtifactRevision(
            revision_id=row["revision_id"],
            artifact_id=row["artifact_id"],
            revision_number=int(row["revision_number"]),
            content_hash=row["content_hash"],
            byte_length=int(row["byte_length"]),
            media_type=row["media_type"],
            created_at=float(row["created_at"]),
            message=row["message"],
            metadata=json.loads(row["metadata_json"]),
        )

    def _insert_revision(
        self, connection: sqlite3.Connection, revision: ArtifactRevision
    ) -> None:
        connection.execute(
            """
            INSERT INTO product_artifact_revisions(
                revision_id, artifact_id, revision_number, content_hash,
                byte_length, media_type, created_at, message, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.revision_id,
                revision.artifact_id,
                revision.revision_number,
                revision.content_hash,
                revision.byte_length,
                revision.media_type,
                revision.created_at,
                revision.message,
                _json_dump(revision.to_dict()["metadata"]),
            ),
        )

    @staticmethod
    def _idempotency_locked(
        connection: sqlite3.Connection, scope_key: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM product_artifact_idempotency WHERE scope_key = ?",
            (scope_key,),
        ).fetchone()

    @staticmethod
    def _insert_idempotency(
        connection: sqlite3.Connection,
        scope_key: str,
        digest: str,
        result_kind: str,
        result_id: str,
        created_at: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO product_artifact_idempotency(
                scope_key, request_digest, result_kind, result_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (scope_key, digest, result_kind, result_id, created_at),
        )

    @staticmethod
    def _assert_digest(row: sqlite3.Row, digest: str) -> None:
        if row["request_digest"] != digest:
            raise ArtifactConflictError(
                "artifact idempotency key is bound to different content"
            )


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_dump(value).encode("utf-8")).hexdigest()


def _json_dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _bounded_identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError(f"{name} must be a bounded identifier")
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
    if any(char not in allowed for char in value):
        raise ValueError(f"{name} contains unsupported characters")
    return value


def _bounded_idempotency_key(value: str) -> str:
    return _bounded_identifier(value, "idempotency_key")


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("relative_path must be bounded and non-empty")
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or normalized == ".":
        raise ValueError("relative_path must stay within destination root")
    return path.as_posix()


__all__ = ["ArtifactStore", "FileArtifactStore"]
