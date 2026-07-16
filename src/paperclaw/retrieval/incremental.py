"""High-level incremental add/update/delete orchestration for local documents."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from paperclaw.retrieval._store import connect, project_manifest
from paperclaw.retrieval.chunking import build_chunks
from paperclaw.retrieval.contracts import (
    ChunkConfig,
    DocumentIdentity,
    DocumentVersion,
    RegistryMutationResult,
    SourceArtifact,
)
from paperclaw.retrieval.parsers import select_parser
from paperclaw.retrieval.registry import SQLiteDocumentRegistry


@dataclass(frozen=True)
class IncrementalIndexResult:
    operation: Literal["add", "update", "delete", "noop"]
    document_id: str
    version_id: str | None
    manifest_id: str | None
    inserted_chunks: int = 0
    deactivated_versions: int = 0
    deactivated_chunks: int = 0

    @classmethod
    def from_mutation(cls, mutation: RegistryMutationResult) -> "IncrementalIndexResult":
        return cls(
            operation=mutation.operation,
            document_id=mutation.document_id,
            version_id=mutation.version_id,
            manifest_id=mutation.manifest_id,
            inserted_chunks=mutation.inserted_chunks,
            deactivated_versions=mutation.deactivated_versions,
            deactivated_chunks=mutation.deactivated_chunks,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IncrementalIndexer:
    """Compute projected manifests, then delegate atomic writes to Phase A Registry."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        chunk_config: ChunkConfig | None = None,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.chunk_config = chunk_config or ChunkConfig()
        self.registry = SQLiteDocumentRegistry(
            db_path,
            busy_timeout_ms=busy_timeout_ms,
            migrate=True,
        )
        self._conn = connect(db_path, busy_timeout_ms=busy_timeout_ms)
        self._lock = threading.RLock()
        self._closed = False

    def index_bytes(
        self,
        *,
        canonical_uri: str,
        display_name: str,
        media_type: str,
        content: bytes,
    ) -> IncrementalIndexResult:
        identity = DocumentIdentity.from_file_uri(canonical_uri, display_name)
        parser = select_parser(source_uri=canonical_uri, media_type=media_type)
        parsed = parser.parse(content.decode("utf-8"), source_uri=canonical_uri)
        artifact = SourceArtifact.from_bytes(
            document_id=identity.document_id,
            source_uri=canonical_uri,
            media_type=media_type,
            content=content,
        )
        version = DocumentVersion.create(
            document_id=identity.document_id,
            artifact=artifact,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
        )
        chunks = build_chunks(
            identity=identity,
            version=version,
            artifact=artifact,
            blocks=parsed.blocks,
            config=self.chunk_config,
        )

        with self._lock:
            active_version = self.registry.get_active_version(identity.document_id)
            latest = self.registry.latest_manifest()
            if active_version is not None and active_version.version_id == version.version_id:
                return IncrementalIndexResult(
                    operation="noop",
                    document_id=identity.document_id,
                    version_id=version.version_id,
                    manifest_id=latest.manifest_id if latest else None,
                )
            existing = self._conn.execute(
                "SELECT document_id FROM documents WHERE document_id = ?",
                (identity.document_id,),
            ).fetchone()
            manifest = project_manifest(
                self._conn,
                chunk_config=self.chunk_config,
                replacement_document_id=identity.document_id,
                replacement_chunks=chunks,
                replacement_parser=f"{parsed.parser_name}:{parsed.parser_version}",
                include_replacement=True,
            )
            if existing is None:
                mutation = self.registry.add_document(
                    identity=identity,
                    version=version,
                    artifact=artifact,
                    chunks=chunks,
                    manifest=manifest,
                )
            else:
                mutation = self.registry.update_document(
                    identity=identity,
                    version=version,
                    artifact=artifact,
                    chunks=chunks,
                    manifest=manifest,
                )
            return IncrementalIndexResult.from_mutation(mutation)

    def delete_document(self, document_id: str) -> IncrementalIndexResult:
        if not document_id.strip():
            raise ValueError("document_id must be non-empty")
        with self._lock:
            manifest = project_manifest(
                self._conn,
                chunk_config=self.chunk_config,
                replacement_document_id=document_id,
                replacement_chunks=(),
                replacement_parser=None,
                include_replacement=False,
            )
            return IncrementalIndexResult.from_mutation(
                self.registry.delete_document(document_id=document_id, manifest=manifest)
            )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._conn.close()
            self.registry.close()

    def __enter__(self) -> "IncrementalIndexer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
