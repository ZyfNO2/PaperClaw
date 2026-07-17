"""SQLite document registry and FTS5 write-side foundation for v0.09.1."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from paperclaw.retrieval.contracts import (
    Chunk,
    ChunkLocator,
    DocumentIdentity,
    DocumentVersion,
    IndexManifest,
    RegistryMutationResult,
    SourceArtifact,
    canonical_json,
    sha256_text,
    utc_now_iso,
)


SCHEMA_VERSION = 1

SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS rag_schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL,
        description TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY,
        canonical_uri TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        source_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_artifacts (
        artifact_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        source_uri TEXT NOT NULL,
        media_type TEXT NOT NULL,
        byte_length INTEGER NOT NULL,
        source_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (document_id) REFERENCES documents(document_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_versions (
        version_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        source_artifact_id TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        parser_name TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
        deactivated_at TEXT,
        UNIQUE (document_id, source_hash, parser_name, parser_version),
        FOREIGN KEY (document_id) REFERENCES documents(document_id),
        FOREIGN KEY (source_artifact_id) REFERENCES source_artifacts(artifact_id)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_document_versions_one_active
        ON document_versions(document_id) WHERE is_active = 1
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        text TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        chunk_config_hash TEXT NOT NULL,
        locator_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
        deactivated_at TEXT,
        UNIQUE (version_id, ordinal),
        FOREIGN KEY (document_id) REFERENCES documents(document_id),
        FOREIGN KEY (version_id) REFERENCES document_versions(version_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_document_active
        ON chunks(document_id, is_active, ordinal)
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
        chunk_id UNINDEXED,
        document_id UNINDEXED,
        version_id UNINDEXED,
        heading,
        text,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_manifests (
        manifest_id TEXT PRIMARY KEY,
        schema_version INTEGER NOT NULL,
        index_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        chunk_config_hash TEXT NOT NULL,
        parser_versions_json TEXT NOT NULL,
        document_count INTEGER NOT NULL,
        version_count INTEGER NOT NULL,
        chunk_count INTEGER NOT NULL,
        state TEXT NOT NULL,
        corpus_hash TEXT NOT NULL,
        content_hash TEXT NOT NULL
    )
    """,
)


class SQLiteDocumentRegistry:
    """Single-writer registry for document/version/chunk/index contracts.

    The registry intentionally exposes no BM25 query API in Phase A. FTS5 rows
    are maintained transactionally so Phase B can add retrieval without changing
    identity, versioning or chunk persistence semantics.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        busy_timeout_ms: int = 5000,
        migrate: bool = True,
    ) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._closed = False
        if migrate:
            self.migrate()

    def migrate(self) -> int:
        with self._lock, self._transaction():
            for statement in SCHEMA_SQL:
                self._conn.execute(statement)
            self._conn.execute(
                "INSERT OR IGNORE INTO rag_schema_migrations(version, applied_at, description) "
                "VALUES (?, ?, ?)",
                (SCHEMA_VERSION, utc_now_iso(), "v0.09.1 Phase A document/index foundation"),
            )
        return self.current_schema_version()

    def current_schema_version(self) -> int:
        try:
            row = self._conn.execute(
                "SELECT MAX(version) AS version FROM rag_schema_migrations"
            ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["version"]) if row and row["version"] is not None else 0

    def add_document(
        self,
        *,
        identity: DocumentIdentity,
        version: DocumentVersion,
        artifact: SourceArtifact,
        chunks: Sequence[Chunk],
        manifest: IndexManifest,
    ) -> RegistryMutationResult:
        self._validate_bundle(identity, version, artifact, chunks, manifest)
        with self._lock, self._transaction():
            existing = self._conn.execute(
                "SELECT document_id FROM documents WHERE document_id = ? OR canonical_uri = ?",
                (identity.document_id, identity.canonical_uri),
            ).fetchone()
            if existing is not None:
                raise ValueError("document already exists; use update_document")
            now = utc_now_iso()
            self._insert_document(identity, now)
            self._insert_version_bundle(version, artifact, chunks)
            self._insert_manifest_after_count_check(manifest)
        return RegistryMutationResult(
            operation="add",
            document_id=identity.document_id,
            version_id=version.version_id,
            inserted_chunks=len(chunks),
            deactivated_versions=0,
            deactivated_chunks=0,
            manifest_id=manifest.manifest_id,
        )

    def update_document(
        self,
        *,
        identity: DocumentIdentity,
        version: DocumentVersion,
        artifact: SourceArtifact,
        chunks: Sequence[Chunk],
        manifest: IndexManifest,
    ) -> RegistryMutationResult:
        self._validate_bundle(identity, version, artifact, chunks, manifest)
        with self._lock, self._transaction():
            row = self._conn.execute(
                "SELECT document_id FROM documents WHERE document_id = ?",
                (identity.document_id,),
            ).fetchone()
            if row is None:
                raise ValueError("document does not exist; use add_document")
            uri_owner = self._conn.execute(
                "SELECT document_id FROM documents WHERE canonical_uri = ?",
                (identity.canonical_uri,),
            ).fetchone()
            if uri_owner is not None and uri_owner["document_id"] != identity.document_id:
                raise ValueError("canonical_uri belongs to a different document")

            existing_version = self._conn.execute(
                "SELECT version_id FROM document_versions WHERE version_id = ?",
                (version.version_id,),
            ).fetchone()
            if existing_version is not None:
                raise ValueError(
                    "document version already exists; source content and parser version are unchanged"
                )

            now = utc_now_iso()
            active_versions = self._conn.execute(
                "SELECT version_id FROM document_versions WHERE document_id = ? AND is_active = 1",
                (identity.document_id,),
            ).fetchall()
            version_ids = [row["version_id"] for row in active_versions]
            deactivated_versions = len(version_ids)
            if version_ids:
                placeholders = ",".join("?" for _ in version_ids)
                chunk_row = self._conn.execute(
                    f"SELECT COUNT(*) AS count FROM chunks WHERE version_id IN ({placeholders}) AND is_active = 1",
                    version_ids,
                ).fetchone()
                deactivated_chunks = int(chunk_row["count"])
                self._conn.execute(
                    f"UPDATE document_versions SET is_active = 0, deactivated_at = ? "
                    f"WHERE version_id IN ({placeholders})",
                    (now, *version_ids),
                )
                self._conn.execute(
                    f"UPDATE chunks SET is_active = 0, deactivated_at = ? "
                    f"WHERE version_id IN ({placeholders}) AND is_active = 1",
                    (now, *version_ids),
                )
                self._conn.execute(
                    f"DELETE FROM chunk_fts WHERE version_id IN ({placeholders})",
                    version_ids,
                )
            else:
                deactivated_chunks = 0

            self._conn.execute(
                "UPDATE documents SET canonical_uri = ?, display_name = ?, source_type = ?, "
                "updated_at = ?, deleted_at = NULL WHERE document_id = ?",
                (
                    identity.canonical_uri,
                    identity.display_name,
                    identity.source_type,
                    now,
                    identity.document_id,
                ),
            )
            self._insert_version_bundle(version, artifact, chunks)
            self._insert_manifest_after_count_check(manifest)
        return RegistryMutationResult(
            operation="update",
            document_id=identity.document_id,
            version_id=version.version_id,
            inserted_chunks=len(chunks),
            deactivated_versions=deactivated_versions,
            deactivated_chunks=deactivated_chunks,
            manifest_id=manifest.manifest_id,
        )

    def delete_document(
        self,
        *,
        document_id: str,
        manifest: IndexManifest,
    ) -> RegistryMutationResult:
        with self._lock, self._transaction():
            row = self._conn.execute(
                "SELECT document_id FROM documents WHERE document_id = ? AND deleted_at IS NULL",
                (document_id,),
            ).fetchone()
            if row is None:
                raise KeyError(document_id)
            now = utc_now_iso()
            version_row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM document_versions WHERE document_id = ? AND is_active = 1",
                (document_id,),
            ).fetchone()
            chunk_row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM chunks WHERE document_id = ? AND is_active = 1",
                (document_id,),
            ).fetchone()
            deactivated_versions = int(version_row["count"])
            deactivated_chunks = int(chunk_row["count"])
            self._conn.execute(
                "UPDATE documents SET deleted_at = ?, updated_at = ? WHERE document_id = ?",
                (now, now, document_id),
            )
            self._conn.execute(
                "UPDATE document_versions SET is_active = 0, deactivated_at = ? "
                "WHERE document_id = ? AND is_active = 1",
                (now, document_id),
            )
            self._conn.execute(
                "UPDATE chunks SET is_active = 0, deactivated_at = ? "
                "WHERE document_id = ? AND is_active = 1",
                (now, document_id),
            )
            self._conn.execute("DELETE FROM chunk_fts WHERE document_id = ?", (document_id,))
            self._insert_manifest_after_count_check(manifest)
        return RegistryMutationResult(
            operation="delete",
            document_id=document_id,
            version_id=None,
            inserted_chunks=0,
            deactivated_versions=deactivated_versions,
            deactivated_chunks=deactivated_chunks,
            manifest_id=manifest.manifest_id,
        )

    def active_counts(self) -> tuple[int, int, int]:
        document_count = int(
            self._conn.execute(
                "SELECT COUNT(*) AS count FROM documents WHERE deleted_at IS NULL"
            ).fetchone()["count"]
        )
        version_count = int(
            self._conn.execute(
                "SELECT COUNT(*) AS count FROM document_versions WHERE is_active = 1"
            ).fetchone()["count"]
        )
        chunk_count = int(
            self._conn.execute(
                "SELECT COUNT(*) AS count FROM chunks WHERE is_active = 1"
            ).fetchone()["count"]
        )
        return document_count, version_count, chunk_count

    def list_active_chunks(self, document_id: str) -> list[Chunk]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE document_id = ? AND is_active = 1 ORDER BY ordinal",
            (document_id,),
        ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def get_active_version(self, document_id: str) -> DocumentVersion | None:
        row = self._conn.execute(
            "SELECT * FROM document_versions WHERE document_id = ? AND is_active = 1",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        return DocumentVersion(
            version_id=row["version_id"],
            document_id=row["document_id"],
            source_artifact_id=row["source_artifact_id"],
            source_hash=row["source_hash"],
            parser_name=row["parser_name"],
            parser_version=row["parser_version"],
            created_at=row["created_at"],
        )

    def latest_manifest(self) -> IndexManifest | None:
        row = self._conn.execute(
            "SELECT * FROM index_manifests ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return IndexManifest(
            manifest_id=row["manifest_id"],
            schema_version=row["schema_version"],
            index_version=row["index_version"],
            created_at=row["created_at"],
            chunk_config_hash=row["chunk_config_hash"],
            parser_versions=tuple(json.loads(row["parser_versions_json"])),
            document_count=row["document_count"],
            version_count=row["version_count"],
            chunk_count=row["chunk_count"],
            state=row["state"],
            corpus_hash=row["corpus_hash"],
            content_hash=row["content_hash"],
        )

    def fts_row_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS count FROM chunk_fts").fetchone()["count"])

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._conn.close()

    def __enter__(self) -> "SQLiteDocumentRegistry":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def _insert_document(self, identity: DocumentIdentity, now: str) -> None:
        self._conn.execute(
            "INSERT INTO documents(document_id, canonical_uri, display_name, source_type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                identity.document_id,
                identity.canonical_uri,
                identity.display_name,
                identity.source_type,
                now,
                now,
            ),
        )

    def _insert_version_bundle(
        self,
        version: DocumentVersion,
        artifact: SourceArtifact,
        chunks: Sequence[Chunk],
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO source_artifacts(artifact_id, document_id, source_uri, media_type, byte_length, source_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                artifact.artifact_id,
                artifact.document_id,
                artifact.source_uri,
                artifact.media_type,
                artifact.byte_length,
                artifact.source_hash,
                artifact.created_at,
            ),
        )
        stored_artifact = self._conn.execute(
            "SELECT document_id, source_uri, media_type, byte_length, source_hash FROM source_artifacts "
            "WHERE artifact_id = ?",
            (artifact.artifact_id,),
        ).fetchone()
        expected_artifact = (
            artifact.document_id,
            artifact.source_uri,
            artifact.media_type,
            artifact.byte_length,
            artifact.source_hash,
        )
        actual_artifact = tuple(stored_artifact) if stored_artifact is not None else None
        if actual_artifact != expected_artifact:
            raise ValueError("artifact_id collision with different immutable metadata")
        self._conn.execute(
            "INSERT INTO document_versions(version_id, document_id, source_artifact_id, source_hash, parser_name, parser_version, created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (
                version.version_id,
                version.document_id,
                version.source_artifact_id,
                version.source_hash,
                version.parser_name,
                version.parser_version,
                version.created_at,
            ),
        )
        for chunk in chunks:
            locator_json = canonical_json(chunk.locator.to_dict())
            self._conn.execute(
                "INSERT INTO chunks(chunk_id, document_id, version_id, ordinal, text, content_hash, source_hash, "
                "chunk_config_hash, locator_json, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.version_id,
                    chunk.ordinal,
                    chunk.text,
                    chunk.content_hash,
                    chunk.source_hash,
                    chunk.chunk_config_hash,
                    locator_json,
                    chunk.created_at,
                ),
            )
            self._conn.execute(
                "INSERT INTO chunk_fts(chunk_id, document_id, version_id, heading, text) VALUES (?, ?, ?, ?, ?)",
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.version_id,
                    " > ".join(chunk.locator.heading_path),
                    chunk.text,
                ),
            )

    def _insert_manifest_after_count_check(self, manifest: IndexManifest) -> None:
        if manifest.schema_version != SCHEMA_VERSION:
            raise ValueError("manifest schema_version does not match registry schema")
        actual = self.active_counts()
        expected = (manifest.document_count, manifest.version_count, manifest.chunk_count)
        if actual != expected:
            raise ValueError(f"manifest counts {expected} do not match active registry counts {actual}")
        actual_fts_count = self.fts_row_count()
        if actual_fts_count != manifest.chunk_count:
            raise ValueError(
                f"FTS row count {actual_fts_count} does not match active chunk count {manifest.chunk_count}"
            )
        active_config_hashes = tuple(
            row["chunk_config_hash"]
            for row in self._conn.execute(
                "SELECT DISTINCT chunk_config_hash FROM chunks "
                "WHERE is_active = 1 ORDER BY chunk_config_hash"
            ).fetchall()
        )
        if active_config_hashes and active_config_hashes != (manifest.chunk_config_hash,):
            raise ValueError(
                f"manifest chunk_config_hash {manifest.chunk_config_hash} does not match "
                f"active chunk configs {active_config_hashes}"
            )
        actual_parser_versions = tuple(
            row["parser_version"]
            for row in self._conn.execute(
                "SELECT DISTINCT parser_name || ':' || parser_version AS parser_version "
                "FROM document_versions WHERE is_active = 1 ORDER BY parser_version"
            ).fetchall()
        )
        if tuple(sorted(manifest.parser_versions)) != actual_parser_versions:
            raise ValueError(
                f"manifest parser_versions {manifest.parser_versions} do not match active parsers {actual_parser_versions}"
            )
        actual_corpus_hash = self._active_corpus_hash()
        if manifest.corpus_hash != actual_corpus_hash:
            raise ValueError(
                f"manifest corpus_hash {manifest.corpus_hash} does not match active corpus {actual_corpus_hash}"
            )
        existing = self._conn.execute(
            "SELECT content_hash FROM index_manifests WHERE manifest_id = ?",
            (manifest.manifest_id,),
        ).fetchone()
        if existing is not None:
            if existing["content_hash"] != manifest.content_hash:
                raise ValueError(
                    f"manifest_id collision: {manifest.manifest_id} exists with different content"
                )
            # A corpus can legitimately return to an earlier snapshot after a
            # delete.  Manifests are content-addressed, so reusing that state
            # reuses its primary key.  Move the existing row to the append tail
            # so rowid-based readers observe the reactivated snapshot as current.
            self._conn.execute(
                "DELETE FROM index_manifests WHERE manifest_id = ?",
                (manifest.manifest_id,),
            )
        self._conn.execute(
            "INSERT INTO index_manifests(manifest_id, schema_version, index_version, created_at, chunk_config_hash, "
            "parser_versions_json, document_count, version_count, chunk_count, state, corpus_hash, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                manifest.manifest_id,
                manifest.schema_version,
                manifest.index_version,
                manifest.created_at,
                manifest.chunk_config_hash,
                canonical_json(list(manifest.parser_versions)),
                manifest.document_count,
                manifest.version_count,
                manifest.chunk_count,
                manifest.state,
                manifest.corpus_hash,
                manifest.content_hash,
            ),
        )

    def _active_corpus_hash(self) -> str:
        rows = self._conn.execute(
            "SELECT document_id, version_id, ordinal, content_hash, source_hash, chunk_config_hash "
            "FROM chunks WHERE is_active = 1 "
            "ORDER BY document_id, version_id, ordinal, chunk_id"
        ).fetchall()
        payload = [
            {
                "document_id": row["document_id"],
                "version_id": row["version_id"],
                "ordinal": row["ordinal"],
                "content_hash": row["content_hash"],
                "source_hash": row["source_hash"],
                "chunk_config_hash": row["chunk_config_hash"],
            }
            for row in rows
        ]
        return sha256_text(canonical_json(payload))

    @staticmethod
    def _validate_bundle(
        identity: DocumentIdentity,
        version: DocumentVersion,
        artifact: SourceArtifact,
        chunks: Sequence[Chunk],
        manifest: IndexManifest,
    ) -> None:
        if version.document_id != identity.document_id or artifact.document_id != identity.document_id:
            raise ValueError("identity, version and artifact document_id values must match")
        if version.source_artifact_id != artifact.artifact_id:
            raise ValueError("version must reference the supplied artifact")
        if version.source_hash != artifact.source_hash:
            raise ValueError("version and artifact source_hash values must match")
        ordinals = [chunk.ordinal for chunk in chunks]
        if ordinals != list(range(len(chunks))):
            raise ValueError("chunk ordinals must be contiguous and zero-based")
        for chunk in chunks:
            if chunk.document_id != identity.document_id:
                raise ValueError("chunk document_id does not match identity")
            if chunk.version_id != version.version_id:
                raise ValueError("chunk version_id does not match version")
            if chunk.source_hash != artifact.source_hash:
                raise ValueError("chunk source_hash does not match artifact")
            if chunk.chunk_config_hash != manifest.chunk_config_hash:
                raise ValueError("chunk_config_hash does not match manifest")
        expected_parser = f"{version.parser_name}:{version.parser_version}"
        if expected_parser not in manifest.parser_versions:
            raise ValueError("manifest parser_versions do not include document parser")
        if manifest.schema_version != SCHEMA_VERSION:
            raise ValueError("manifest schema_version does not match registry schema")

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> Chunk:
        raw = json.loads(row["locator_json"])
        locator = ChunkLocator(
            source_uri=raw["source_uri"],
            heading_path=tuple(raw["heading_path"]),
            start_line=raw["start_line"],
            end_line=raw["end_line"],
            start_paragraph=raw["start_paragraph"],
            end_paragraph=raw["end_paragraph"],
            start_fragment=raw.get("start_fragment", 0),
            end_fragment=raw.get("end_fragment", 0),
            overlap_from_previous=raw.get("overlap_from_previous", False),
        )
        return Chunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            version_id=row["version_id"],
            ordinal=row["ordinal"],
            text=row["text"],
            content_hash=row["content_hash"],
            source_hash=row["source_hash"],
            chunk_config_hash=row["chunk_config_hash"],
            locator=locator,
            created_at=row["created_at"],
        )
