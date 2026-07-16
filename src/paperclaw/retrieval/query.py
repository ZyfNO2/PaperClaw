"""Deterministic BM25 retrieval over the v0.09.1 SQLite FTS5 index."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from paperclaw.retrieval.contracts import ChunkLocator, canonical_json, sha256_text, stable_id

_QUERY_TOKEN = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


class RetrievalError(RuntimeError):
    """Base class for deterministic retrieval failures."""


class BrokenIndexError(RetrievalError):
    """Raised when the current index has no usable ready manifest."""


class StaleIndexError(RetrievalError):
    """Raised when a caller pins a manifest/corpus that is no longer current."""


@dataclass(frozen=True)
class RetrievalRequest:
    """Frozen read-side request for deterministic BM25 retrieval."""

    query: str
    top_k: int = 5
    candidate_pool_size: int = 50
    document_ids: tuple[str, ...] = ()
    deduplicate: bool = True
    expected_manifest_id: str | None = None
    expected_corpus_hash: str | None = None

    def __post_init__(self) -> None:
        normalized = " ".join(self.query.split())
        if not normalized:
            raise ValueError("query must be non-empty")
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.candidate_pool_size < self.top_k:
            raise ValueError("candidate_pool_size must be at least top_k")
        if self.candidate_pool_size > 10_000:
            raise ValueError("candidate_pool_size is unreasonably large")
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must not contain duplicates")
        if self.expected_corpus_hash is not None:
            _require_sha256("expected_corpus_hash", self.expected_corpus_hash)

    @property
    def normalized_query(self) -> str:
        return " ".join(self.query.split())

    @property
    def request_id(self) -> str:
        return stable_id(
            "retrieval",
            self.normalized_query.casefold(),
            str(self.top_k),
            str(self.candidate_pool_size),
            canonical_json(sorted(self.document_ids)),
            str(self.deduplicate),
            self.expected_manifest_id or "",
            self.expected_corpus_hash or "",
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["document_ids"] = list(self.document_ids)
        data["request_id"] = self.request_id
        data["normalized_query"] = self.normalized_query
        return data


@dataclass(frozen=True)
class RetrievalCandidate:
    """One active, version-bound chunk returned by the BM25 read side."""

    chunk_id: str
    document_id: str
    version_id: str
    display_name: str
    canonical_uri: str
    text: str
    content_hash: str
    source_hash: str
    chunk_config_hash: str
    locator: ChunkLocator
    bm25_score: float
    rank: int

    def __post_init__(self) -> None:
        for name in (
            "chunk_id",
            "document_id",
            "version_id",
            "display_name",
            "canonical_uri",
            "text",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        for name in ("content_hash", "source_hash", "chunk_config_hash"):
            _require_sha256(name, getattr(self, name))
        if self.rank <= 0:
            raise ValueError("rank must be positive")
        if self.bm25_score < 0:
            raise ValueError("bm25_score must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["locator"] = self.locator.to_dict()
        return data


@dataclass(frozen=True)
class RankedResult:
    """Deterministic ranked retrieval response with filtering diagnostics."""

    request_id: str
    manifest_id: str | None
    corpus_hash: str
    candidates: tuple[RetrievalCandidate, ...]
    total_matches: int
    filtered_stale: int
    filtered_duplicates: int

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must be non-empty")
        _require_sha256("corpus_hash", self.corpus_hash)
        if self.total_matches < 0 or self.filtered_stale < 0 or self.filtered_duplicates < 0:
            raise ValueError("result counters must be non-negative")
        expected_ranks = tuple(range(1, len(self.candidates) + 1))
        if tuple(candidate.rank for candidate in self.candidates) != expected_ranks:
            raise ValueError("candidate ranks must be contiguous and one-based")

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "manifest_id": self.manifest_id,
            "corpus_hash": self.corpus_hash,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "total_matches": self.total_matches,
            "filtered_stale": self.filtered_stale,
            "filtered_duplicates": self.filtered_duplicates,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_text(canonical_json(self.to_dict()))


@dataclass(frozen=True)
class _ManifestSnapshot:
    manifest_id: str
    corpus_hash: str
    state: str


class SQLiteBM25Retriever:
    """Read-only BM25 adapter that filters stale and duplicate FTS rows."""

    def __init__(self, db_path: str | Path, *, busy_timeout_ms: int = 5000) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self._closed = False

    def query(self, request: RetrievalRequest) -> RankedResult:
        manifest = self._current_manifest()
        if manifest is None:
            if self._active_chunk_count() == 0:
                corpus_hash = sha256_text(canonical_json([]))
                return RankedResult(
                    request_id=request.request_id,
                    manifest_id=None,
                    corpus_hash=corpus_hash,
                    candidates=(),
                    total_matches=0,
                    filtered_stale=0,
                    filtered_duplicates=0,
                )
            raise BrokenIndexError("active chunks exist but no index manifest is available")
        if manifest.state != "ready":
            raise BrokenIndexError(
                f"latest index manifest {manifest.manifest_id} is {manifest.state}"
            )
        self._validate_request_snapshot(request, manifest)

        match_query = _build_match_query(request.normalized_query)
        if not match_query:
            return RankedResult(
                request_id=request.request_id,
                manifest_id=manifest.manifest_id,
                corpus_hash=manifest.corpus_hash,
                candidates=(),
                total_matches=0,
                filtered_stale=0,
                filtered_duplicates=0,
            )

        match_filter = "chunk_fts MATCH ?"
        match_params: list[Any] = [match_query]
        if request.document_ids:
            placeholders = ",".join("?" for _ in request.document_ids)
            match_filter += f" AND document_id IN ({placeholders})"
            match_params.extend(request.document_ids)
        total_matches = int(
            self._conn.execute(
                f"SELECT COUNT(*) AS count FROM chunk_fts WHERE {match_filter}",
                match_params,
            ).fetchone()["count"]
        )
        rows = self._conn.execute(
            f"""
            WITH matches AS (
                SELECT rowid AS fts_rowid,
                       chunk_id AS fts_chunk_id,
                       document_id AS fts_document_id,
                       version_id AS fts_version_id,
                       heading AS fts_heading,
                       text AS fts_text,
                       bm25(chunk_fts, 0.0, 0.0, 0.0, 2.0, 1.0) AS raw_rank
                FROM chunk_fts
                WHERE {match_filter}
                ORDER BY raw_rank, fts_chunk_id, fts_rowid
                LIMIT ?
            )
            SELECT m.*,
                   c.chunk_id,
                   c.document_id,
                   c.version_id,
                   c.ordinal,
                   c.text,
                   c.content_hash,
                   c.source_hash,
                   c.chunk_config_hash,
                   c.locator_json,
                   c.is_active AS chunk_active,
                   v.is_active AS version_active,
                   d.deleted_at,
                   d.display_name,
                   d.canonical_uri
            FROM matches AS m
            LEFT JOIN chunks AS c ON c.chunk_id = m.fts_chunk_id
            LEFT JOIN document_versions AS v ON v.version_id = c.version_id
            LEFT JOIN documents AS d ON d.document_id = c.document_id
            ORDER BY m.raw_rank, m.fts_chunk_id, m.fts_rowid
            """,
            (*match_params, request.candidate_pool_size),
        ).fetchall()

        filtered_stale = 0
        filtered_duplicates = 0
        seen_chunks: set[str] = set()
        seen_content: set[str] = set()
        accepted: list[tuple[sqlite3.Row, float]] = []

        for row in rows:
            if not _row_is_active(row):
                filtered_stale += 1
                continue
            if row["chunk_id"] in seen_chunks:
                filtered_duplicates += 1
                continue
            seen_chunks.add(row["chunk_id"])
            if request.deduplicate and row["content_hash"] in seen_content:
                filtered_duplicates += 1
                continue
            seen_content.add(row["content_hash"])
            accepted.append((row, max(0.0, -float(row["raw_rank"]))))
            if len(accepted) >= request.top_k:
                break

        candidates = tuple(
            _candidate_from_row(row, score=score, rank=index)
            for index, (row, score) in enumerate(accepted, start=1)
        )
        return RankedResult(
            request_id=request.request_id,
            manifest_id=manifest.manifest_id,
            corpus_hash=manifest.corpus_hash,
            candidates=candidates,
            total_matches=total_matches,
            filtered_stale=filtered_stale,
            filtered_duplicates=filtered_duplicates,
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._conn.close()

    def __enter__(self) -> "SQLiteBM25Retriever":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _current_manifest(self) -> _ManifestSnapshot | None:
        try:
            row = self._conn.execute(
                "SELECT manifest_id, corpus_hash, state FROM index_manifests "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise BrokenIndexError("retrieval schema is unavailable") from exc
        if row is None:
            return None
        return _ManifestSnapshot(row["manifest_id"], row["corpus_hash"], row["state"])

    def _active_chunk_count(self) -> int:
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM chunks WHERE is_active = 1"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise BrokenIndexError("retrieval schema is unavailable") from exc
        return int(row["count"])

    @staticmethod
    def _validate_request_snapshot(
        request: RetrievalRequest,
        manifest: _ManifestSnapshot,
    ) -> None:
        if request.expected_manifest_id and request.expected_manifest_id != manifest.manifest_id:
            raise StaleIndexError(
                f"expected manifest {request.expected_manifest_id} but current is {manifest.manifest_id}"
            )
        if request.expected_corpus_hash and request.expected_corpus_hash != manifest.corpus_hash:
            raise StaleIndexError(
                f"expected corpus {request.expected_corpus_hash} but current is {manifest.corpus_hash}"
            )


def _build_match_query(query: str) -> str:
    tokens = []
    seen: set[str] = set()
    for token in _QUERY_TOKEN.findall(query.casefold()):
        if token in seen:
            continue
        seen.add(token)
        escaped = token.replace('"', '""')
        tokens.append(f'"{escaped}"')
    return " OR ".join(tokens)


def _row_is_active(row: sqlite3.Row) -> bool:
    if not (
        row["chunk_id"]
        and row["chunk_active"] == 1
        and row["version_active"] == 1
        and row["deleted_at"] is None
        and row["fts_chunk_id"] == row["chunk_id"]
        and row["fts_document_id"] == row["document_id"]
        and row["fts_version_id"] == row["version_id"]
        and row["fts_text"] == row["text"]
    ):
        return False
    try:
        locator = json.loads(row["locator_json"])
    except (TypeError, json.JSONDecodeError):
        return False
    expected_heading = " > ".join(locator.get("heading_path", ()))
    return row["fts_heading"] == expected_heading


def _candidate_from_row(
    row: sqlite3.Row,
    *,
    score: float,
    rank: int,
) -> RetrievalCandidate:
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
    return RetrievalCandidate(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        version_id=row["version_id"],
        display_name=row["display_name"],
        canonical_uri=row["canonical_uri"],
        text=row["text"],
        content_hash=row["content_hash"],
        source_hash=row["source_hash"],
        chunk_config_hash=row["chunk_config_hash"],
        locator=locator,
        bm25_score=score,
        rank=rank,
    )


def _require_sha256(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def retrieved_ids(result: RankedResult, *, field: str = "chunk_id") -> tuple[str, ...]:
    """Return one candidate identity projection for metric/eval consumers."""

    allowed = {"chunk_id", "document_id", "version_id", "canonical_uri"}
    if field not in allowed:
        raise ValueError(f"unsupported candidate identity field: {field}")
    return tuple(str(getattr(candidate, field)) for candidate in result.candidates)


def unique_in_order(values: Iterable[str]) -> tuple[str, ...]:
    """Deterministic helper used by fixtures and downstream adapters."""

    return tuple(dict.fromkeys(values))
