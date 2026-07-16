"""Shared SQLite helpers for the v0.09.1 retrieval read/write adapters."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from paperclaw.retrieval.contracts import (
    INDEX_SCHEMA_VERSION,
    Chunk,
    ChunkConfig,
    IndexManifest,
    canonical_json,
    sha256_text,
)


def connect(db_path: str | Path, *, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def active_index_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT c.chunk_id,
               c.document_id,
               c.version_id,
               c.ordinal,
               c.content_hash,
               c.source_hash,
               c.chunk_config_hash,
               c.locator_json,
               c.text,
               d.display_name,
               d.canonical_uri
        FROM chunks AS c
        JOIN document_versions AS v ON v.version_id = c.version_id
        JOIN documents AS d ON d.document_id = c.document_id
        WHERE c.is_active = 1 AND v.is_active = 1 AND d.deleted_at IS NULL
        ORDER BY c.document_id, c.version_id, c.ordinal, c.chunk_id
        """
    ).fetchall()


def active_counts(connection: sqlite3.Connection) -> tuple[int, int, int]:
    documents = int(
        connection.execute(
            "SELECT COUNT(*) AS count FROM documents WHERE deleted_at IS NULL"
        ).fetchone()["count"]
    )
    versions = int(
        connection.execute(
            "SELECT COUNT(*) AS count FROM document_versions AS v "
            "JOIN documents AS d ON d.document_id = v.document_id "
            "WHERE v.is_active = 1 AND d.deleted_at IS NULL"
        ).fetchone()["count"]
    )
    return documents, versions, len(active_index_rows(connection))


def locator_heading(locator_json: str) -> str:
    raw = json.loads(locator_json)
    return " > ".join(raw.get("heading_path", ()))


def fts_key(row: sqlite3.Row) -> tuple[str, str, str, str, str]:
    heading = row["heading"] if "heading" in row.keys() else locator_heading(row["locator_json"])
    return (
        row["chunk_id"],
        row["document_id"],
        row["version_id"],
        heading,
        row["text"],
    )


def corpus_entry(value: sqlite3.Row | Chunk) -> dict[str, Any]:
    if isinstance(value, sqlite3.Row):
        return {
            "document_id": value["document_id"],
            "version_id": value["version_id"],
            "ordinal": value["ordinal"],
            "content_hash": value["content_hash"],
            "source_hash": value["source_hash"],
            "chunk_config_hash": value["chunk_config_hash"],
            "chunk_id": value["chunk_id"],
        }
    return {
        "document_id": value.document_id,
        "version_id": value.version_id,
        "ordinal": value.ordinal,
        "content_hash": value.content_hash,
        "source_hash": value.source_hash,
        "chunk_config_hash": value.chunk_config_hash,
        "chunk_id": value.chunk_id,
    }


def corpus_hash_from_entries(entries: Sequence[dict[str, Any]]) -> str:
    ordered = sorted(
        entries,
        key=lambda item: (
            item["document_id"],
            item["version_id"],
            item["ordinal"],
            item["chunk_id"],
        ),
    )
    payload = [
        {
            "document_id": item["document_id"],
            "version_id": item["version_id"],
            "ordinal": item["ordinal"],
            "content_hash": item["content_hash"],
            "source_hash": item["source_hash"],
            "chunk_config_hash": item["chunk_config_hash"],
        }
        for item in ordered
    ]
    return sha256_text(canonical_json(payload))


def corpus_hash(rows: Sequence[sqlite3.Row]) -> str:
    return corpus_hash_from_entries([corpus_entry(row) for row in rows])


def project_manifest(
    connection: sqlite3.Connection,
    *,
    chunk_config: ChunkConfig,
    replacement_document_id: str,
    replacement_chunks: Sequence[Chunk],
    replacement_parser: str | None,
    include_replacement: bool,
) -> IndexManifest:
    rows = connection.execute(
        "SELECT chunk_id, document_id, version_id, ordinal, content_hash, source_hash, "
        "chunk_config_hash FROM chunks WHERE is_active = 1 AND document_id != ? "
        "ORDER BY document_id, version_id, ordinal, chunk_id",
        (replacement_document_id,),
    ).fetchall()
    entries = [corpus_entry(row) for row in rows]
    entries.extend(corpus_entry(chunk) for chunk in replacement_chunks)
    config_hashes = {entry["chunk_config_hash"] for entry in entries}
    if len(config_hashes) > 1:
        raise ValueError(f"active corpus has mixed chunk configurations: {sorted(config_hashes)}")
    config_hash = next(iter(config_hashes), chunk_config.config_hash)
    if replacement_chunks and config_hash != chunk_config.config_hash:
        raise ValueError("incremental update chunk configuration differs from active corpus")

    parser_versions = {
        row["parser_version"]
        for row in connection.execute(
            "SELECT DISTINCT parser_name || ':' || parser_version AS parser_version "
            "FROM document_versions WHERE is_active = 1 AND document_id != ?",
            (replacement_document_id,),
        ).fetchall()
    }
    if include_replacement and replacement_parser:
        parser_versions.add(replacement_parser)

    base_documents = int(
        connection.execute(
            "SELECT COUNT(*) AS count FROM documents "
            "WHERE deleted_at IS NULL AND document_id != ?",
            (replacement_document_id,),
        ).fetchone()["count"]
    )
    base_versions = int(
        connection.execute(
            "SELECT COUNT(*) AS count FROM document_versions "
            "WHERE is_active = 1 AND document_id != ?",
            (replacement_document_id,),
        ).fetchone()["count"]
    )
    increment = 1 if include_replacement else 0
    return IndexManifest.create(
        chunk_config_hash=config_hash,
        parser_versions=tuple(sorted(parser_versions)),
        document_count=base_documents + increment,
        version_count=base_versions + increment,
        chunk_count=len(entries),
        corpus_hash=corpus_hash_from_entries(entries),
        state="ready",
    )


def current_manifest(
    connection: sqlite3.Connection,
    *,
    chunk_config: ChunkConfig,
) -> IndexManifest:
    rows = active_index_rows(connection)
    documents, versions, chunks = active_counts(connection)
    config_hashes = {row["chunk_config_hash"] for row in rows}
    if len(config_hashes) > 1:
        raise ValueError("cannot rebuild an active corpus with mixed chunk configurations")
    latest = connection.execute(
        "SELECT chunk_config_hash FROM index_manifests ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    config_hash = next(
        iter(config_hashes),
        latest["chunk_config_hash"] if latest is not None else chunk_config.config_hash,
    )
    parser_versions = tuple(
        row["parser_version"]
        for row in connection.execute(
            "SELECT DISTINCT v.parser_name || ':' || v.parser_version AS parser_version "
            "FROM document_versions AS v JOIN documents AS d ON d.document_id = v.document_id "
            "WHERE v.is_active = 1 AND d.deleted_at IS NULL ORDER BY parser_version"
        ).fetchall()
    )
    return IndexManifest.create(
        schema_version=INDEX_SCHEMA_VERSION,
        chunk_config_hash=config_hash,
        parser_versions=parser_versions,
        document_count=documents,
        version_count=versions,
        chunk_count=chunks,
        corpus_hash=corpus_hash(rows),
        state="ready",
    )


def insert_manifest(connection: sqlite3.Connection, manifest: IndexManifest) -> None:
    connection.execute(
        "INSERT INTO index_manifests(manifest_id, schema_version, index_version, created_at, "
        "chunk_config_hash, parser_versions_json, document_count, version_count, chunk_count, "
        "state, corpus_hash, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
