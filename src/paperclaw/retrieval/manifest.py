"""Strict validation for persisted retrieval index manifests."""

from __future__ import annotations

import json
import sqlite3

from paperclaw.retrieval.contracts import (
    INDEX_SCHEMA_VERSION,
    INDEX_VERSION,
    IndexManifest,
)


def validate_manifest_row(row: sqlite3.Row) -> IndexManifest:
    """Rehydrate and validate one persisted manifest or fail closed."""

    try:
        parser_versions = tuple(json.loads(row["parser_versions_json"]))
        manifest = IndexManifest(
            manifest_id=row["manifest_id"],
            schema_version=int(row["schema_version"]),
            index_version=row["index_version"],
            created_at=row["created_at"],
            chunk_config_hash=row["chunk_config_hash"],
            parser_versions=parser_versions,
            document_count=int(row["document_count"]),
            version_count=int(row["version_count"]),
            chunk_count=int(row["chunk_count"]),
            state=row["state"],
            corpus_hash=row["corpus_hash"],
            content_hash=row["content_hash"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("persisted index manifest is invalid") from exc
    if manifest.schema_version != INDEX_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported index schema version: {manifest.schema_version}"
        )
    if manifest.index_version != INDEX_VERSION:
        raise ValueError(f"unsupported index version: {manifest.index_version}")
    if manifest.state not in {"ready", "building", "broken"}:
        raise ValueError(f"unsupported index state: {manifest.state}")
    return manifest
