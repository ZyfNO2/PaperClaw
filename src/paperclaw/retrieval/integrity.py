"""Exact FTS5 integrity inspection and deterministic rebuild support."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from paperclaw.retrieval._store import (
    active_counts,
    active_index_rows,
    connect,
    corpus_hash,
    current_manifest,
    fts_key,
    insert_manifest,
)
from paperclaw.retrieval.contracts import ChunkConfig, canonical_json, sha256_text
from paperclaw.retrieval.manifest import validate_manifest_row


@dataclass(frozen=True)
class IndexIntegrityReport:
    active_documents: int
    active_versions: int
    active_chunks: int
    fts_rows: int
    missing_fts_rows: int
    stale_fts_rows: int
    duplicate_fts_rows: int
    mismatched_fts_rows: int
    manifest_id: str | None
    manifest_state: str | None
    manifest_contract_match: bool
    manifest_counts_match: bool
    manifest_corpus_match: bool
    corpus_hash: str

    @property
    def is_broken(self) -> bool:
        return bool(
            self.missing_fts_rows
            or self.stale_fts_rows
            or self.duplicate_fts_rows
            or self.mismatched_fts_rows
            or self.manifest_state != "ready"
            or not self.manifest_contract_match
            or not self.manifest_counts_match
            or not self.manifest_corpus_match
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_broken"] = self.is_broken
        return data

    @property
    def fingerprint(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class IndexRebuildResult:
    rebuilt: bool
    removed_fts_rows: int
    written_fts_rows: int
    manifest_id: str
    before: IndexIntegrityReport
    after: IndexIntegrityReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "rebuilt": self.rebuilt,
            "removed_fts_rows": self.removed_fts_rows,
            "written_fts_rows": self.written_fts_rows,
            "manifest_id": self.manifest_id,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
        }


class SQLiteIndexMaintainer:
    """Inspect and rebuild FTS rows from active immutable chunk records."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        chunk_config: ChunkConfig | None = None,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.chunk_config = chunk_config or ChunkConfig()
        self._conn = connect(db_path, busy_timeout_ms=busy_timeout_ms)
        self._closed = False

    def inspect(self) -> IndexIntegrityReport:
        expected_rows = active_index_rows(self._conn)
        fts_rows = self._conn.execute(
            "SELECT rowid, chunk_id, document_id, version_id, heading, text "
            "FROM chunk_fts ORDER BY rowid"
        ).fetchall()
        expected_by_chunk = {row["chunk_id"]: row for row in expected_rows}
        exact_counts: dict[tuple[str, str, str, str, str], int] = {}
        stale = 0
        mismatched = 0
        for row in fts_rows:
            key = fts_key(row)
            exact_counts[key] = exact_counts.get(key, 0) + 1
            expected = expected_by_chunk.get(row["chunk_id"])
            if expected is None:
                stale += 1
            elif key != fts_key(expected):
                stale += 1
                mismatched += 1
        missing = sum(
            1 for expected in expected_rows if exact_counts.get(fts_key(expected), 0) == 0
        )
        duplicates = sum(max(0, count - 1) for count in exact_counts.values())
        documents, versions, chunks = active_counts(self._conn)
        current_hash = corpus_hash(expected_rows)
        manifest_row = self._conn.execute(
            "SELECT * FROM index_manifests ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if manifest_row is None:
            manifest_id = None
            manifest_state = None
            contract_match = documents == versions == chunks == 0
            counts_match = documents == versions == chunks == 0
            corpus_match = chunks == 0
        else:
            manifest_id = manifest_row["manifest_id"]
            manifest_state = manifest_row["state"]
            try:
                validate_manifest_row(manifest_row)
            except ValueError:
                contract_match = False
            else:
                contract_match = True
            counts_match = (
                int(manifest_row["document_count"]),
                int(manifest_row["version_count"]),
                int(manifest_row["chunk_count"]),
            ) == (documents, versions, chunks)
            corpus_match = manifest_row["corpus_hash"] == current_hash
        return IndexIntegrityReport(
            active_documents=documents,
            active_versions=versions,
            active_chunks=chunks,
            fts_rows=len(fts_rows),
            missing_fts_rows=missing,
            stale_fts_rows=stale,
            duplicate_fts_rows=duplicates,
            mismatched_fts_rows=mismatched,
            manifest_id=manifest_id,
            manifest_state=manifest_state,
            manifest_contract_match=contract_match,
            manifest_counts_match=counts_match,
            manifest_corpus_match=corpus_match,
            corpus_hash=current_hash,
        )

    def rebuild(self, *, force: bool = False) -> IndexRebuildResult:
        before = self.inspect()
        if not force and not before.is_broken:
            if before.manifest_id is None:
                raise RuntimeError("healthy index unexpectedly has no manifest")
            return IndexRebuildResult(False, 0, 0, before.manifest_id, before, before)

        self._conn.execute("BEGIN IMMEDIATE")
        try:
            rows = active_index_rows(self._conn)
            removed = int(
                self._conn.execute("SELECT COUNT(*) AS count FROM chunk_fts").fetchone()[
                    "count"
                ]
            )
            self._conn.execute("DELETE FROM chunk_fts")
            self._conn.executemany(
                "INSERT INTO chunk_fts(chunk_id, document_id, version_id, heading, text) "
                "VALUES (?, ?, ?, ?, ?)",
                [fts_key(row) for row in rows],
            )
            manifest = current_manifest(self._conn, chunk_config=self.chunk_config)
            self._conn.execute(
                "DELETE FROM index_manifests WHERE manifest_id = ? OR content_hash = ?",
                (manifest.manifest_id, manifest.content_hash),
            )
            insert_manifest(self._conn, manifest)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        after = self.inspect()
        if after.is_broken:
            raise RuntimeError("index rebuild completed but integrity remains broken")
        return IndexRebuildResult(
            rebuilt=True,
            removed_fts_rows=removed,
            written_fts_rows=len(rows),
            manifest_id=manifest.manifest_id,
            before=before,
            after=after,
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._conn.close()

    def __enter__(self) -> "SQLiteIndexMaintainer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
