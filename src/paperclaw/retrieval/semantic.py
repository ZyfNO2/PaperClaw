"""Persistent deterministic local vector retrieval for PaperClaw."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterable, Mapping, Sequence

from .contracts import ChunkLocator, canonical_json, sha256_text
from .query import RankedResult, RetrievalCandidate, RetrievalRequest

_TOKEN = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SemanticDocument:
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

    @classmethod
    def from_candidate(cls, candidate: RetrievalCandidate) -> "SemanticDocument":
        return cls(
            candidate.chunk_id,
            candidate.document_id,
            candidate.version_id,
            candidate.display_name,
            candidate.canonical_uri,
            candidate.text,
            candidate.content_hash,
            candidate.source_hash,
            candidate.chunk_config_hash,
            candidate.locator,
        )


@dataclass(frozen=True)
class HashingEmbeddingConfig:
    dimensions: int = 2048
    min_char_ngram: int = 3
    max_char_ngram: int = 5
    include_word_bigrams: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.dimensions, bool) or not 128 <= self.dimensions <= 65_536:
            raise ValueError("dimensions must be in [128, 65536]")
        if not 1 <= self.min_char_ngram <= self.max_char_ngram <= 8:
            raise ValueError("invalid character n-gram bounds")
        if not isinstance(self.include_word_bigrams, bool):
            raise ValueError("include_word_bigrams must be boolean")

    @property
    def fingerprint(self) -> str:
        return sha256_text(
            canonical_json(
                {
                    "dimensions": self.dimensions,
                    "min_char_ngram": self.min_char_ngram,
                    "max_char_ngram": self.max_char_ngram,
                    "include_word_bigrams": self.include_word_bigrams,
                }
            )
        )


class HashingSemanticEncoder:
    """Signed feature hashing over words, bigrams and character n-grams."""

    def __init__(self, config: HashingEmbeddingConfig | None = None) -> None:
        self.config = config or HashingEmbeddingConfig()

    def encode(self, text: str) -> dict[int, float]:
        normalized = " ".join(str(text).casefold().split())
        if not normalized:
            return {}
        words = _TOKEN.findall(normalized)
        features = [f"w:{word}" for word in words]
        if self.config.include_word_bigrams:
            features.extend(f"b:{left}\u241f{right}" for left, right in zip(words, words[1:]))
        padded = f"^{normalized}$"
        for size in range(self.config.min_char_ngram, self.config.max_char_ngram + 1):
            features.extend(
                f"c{size}:{padded[index:index + size]}"
                for index in range(max(0, len(padded) - size + 1))
            )
        vector: dict[int, float] = {}
        for feature in features:
            digest = blake2b(feature.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self.config.dimensions
            vector[index] = vector.get(index, 0.0) + (1.0 if digest[8] & 1 else -1.0)
        norm = math.sqrt(sum(value * value for value in vector.values()))
        return {index: value / norm for index, value in vector.items() if value} if norm else {}


class SQLiteHashingVectorRetriever:
    def __init__(
        self,
        database: str | Path,
        *,
        encoder: HashingSemanticEncoder | None = None,
        max_documents: int = 200_000,
    ) -> None:
        self.database = Path(database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.encoder = encoder or HashingSemanticEncoder()
        if isinstance(max_documents, bool) or max_documents < 1:
            raise ValueError("max_documents must be positive")
        self.max_documents = max_documents
        self._lock = threading.RLock()
        self._initialize()

    def replace_documents(self, documents: Iterable[SemanticDocument]) -> str:
        rows = _documents(documents, self.max_documents)
        corpus_hash = _corpus_hash(rows, self.encoder.config.fingerprint)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM semantic_chunks")
                for item in rows:
                    self._write(connection, item)
                self._write_manifest(connection, corpus_hash, len(rows))
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return corpus_hash

    def upsert_documents(self, documents: Iterable[SemanticDocument]) -> str:
        incoming = tuple(documents)
        if len({item.chunk_id for item in incoming}) != len(incoming):
            raise ValueError("semantic update contains duplicate chunk_id values")
        with self._lock, self._connect() as connection:
            existing_count = int(connection.execute("SELECT COUNT(*) FROM semantic_chunks").fetchone()[0])
            existing_ids = {
                str(row[0])
                for row in connection.execute("SELECT chunk_id FROM semantic_chunks").fetchall()
            }
            if existing_count + sum(item.chunk_id not in existing_ids for item in incoming) > self.max_documents:
                raise ValueError("semantic corpus exceeds max_documents")
            connection.execute("BEGIN IMMEDIATE")
            try:
                for item in incoming:
                    self._write(connection, item)
                rows = self._read_documents(connection)
                corpus_hash = _corpus_hash(rows, self.encoder.config.fingerprint)
                self._write_manifest(connection, corpus_hash, len(rows))
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return corpus_hash

    def query(self, request: RetrievalRequest) -> RankedResult:
        query_vector = self.encoder.encode(request.normalized_query)
        with self._lock, self._connect() as connection:
            manifest = connection.execute(
                "SELECT encoder_fingerprint, corpus_hash FROM semantic_manifest WHERE singleton=1"
            ).fetchone()
            if manifest is None:
                return RankedResult(
                    request.request_id,
                    None,
                    sha256_text(canonical_json([])),
                    (),
                    0,
                    0,
                    0,
                )
            if str(manifest[0]) != self.encoder.config.fingerprint:
                raise RuntimeError("semantic index encoder fingerprint does not match runtime")
            corpus_hash = str(manifest[1])
            if request.expected_corpus_hash and request.expected_corpus_hash != corpus_hash:
                raise RuntimeError("semantic index corpus hash does not match request")
            sql = "SELECT * FROM semantic_chunks"
            parameters: tuple[Any, ...] = ()
            if request.document_ids:
                sql += " WHERE document_id IN ({})".format(
                    ",".join("?" for _ in request.document_ids)
                )
                parameters = tuple(request.document_ids)
            rows = connection.execute(sql, parameters).fetchall()

        scored = [
            (_cosine(query_vector, _decode_vector(str(row[11]))), row)
            for row in rows
        ]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (-item[0], str(item[1][1])))
        selected: list[RetrievalCandidate] = []
        seen_documents: set[str] = set()
        filtered_duplicates = 0
        for score, row in scored[: request.candidate_pool_size]:
            document_id = str(row[2])
            if request.deduplicate and document_id in seen_documents:
                filtered_duplicates += 1
                continue
            seen_documents.add(document_id)
            selected.append(
                RetrievalCandidate(
                    chunk_id=str(row[1]),
                    document_id=document_id,
                    version_id=str(row[3]),
                    display_name=str(row[4]),
                    canonical_uri=str(row[5]),
                    text=str(row[6]),
                    content_hash=str(row[7]),
                    source_hash=str(row[8]),
                    chunk_config_hash=str(row[9]),
                    locator=_locator(json.loads(str(row[10]))),
                    bm25_score=round(score, 12),
                    rank=len(selected) + 1,
                )
            )
            if len(selected) >= request.top_k:
                break
        return RankedResult(
            request_id=request.request_id,
            manifest_id=f"semantic-{self.encoder.config.fingerprint[:16]}",
            corpus_hash=corpus_hash,
            candidates=tuple(selected),
            total_matches=len(scored),
            filtered_stale=0,
            filtered_duplicates=filtered_duplicates,
        )

    def manifest(self) -> Mapping[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT schema_version, encoder_fingerprint, corpus_hash, document_count FROM semantic_manifest WHERE singleton=1"
            ).fetchone()
        if row is None:
            return None
        return {
            "schema_version": int(row[0]),
            "encoder_fingerprint": str(row[1]),
            "corpus_hash": str(row[2]),
            "document_count": int(row[3]),
        }

    def close(self) -> None:
        return None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS semantic_chunks(
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id TEXT NOT NULL UNIQUE,
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    canonical_uri TEXT NOT NULL,
                    text TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    chunk_config_hash TEXT NOT NULL,
                    locator_json TEXT NOT NULL,
                    vector_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS semantic_manifest(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    schema_version INTEGER NOT NULL,
                    encoder_fingerprint TEXT NOT NULL,
                    corpus_hash TEXT NOT NULL,
                    document_count INTEGER NOT NULL
                );
                """
            )

    def _write(self, connection: sqlite3.Connection, item: SemanticDocument) -> None:
        connection.execute(
            """
            INSERT INTO semantic_chunks(
                chunk_id, document_id, version_id, display_name, canonical_uri,
                text, content_hash, source_hash, chunk_config_hash, locator_json,
                vector_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                document_id=excluded.document_id,
                version_id=excluded.version_id,
                display_name=excluded.display_name,
                canonical_uri=excluded.canonical_uri,
                text=excluded.text,
                content_hash=excluded.content_hash,
                source_hash=excluded.source_hash,
                chunk_config_hash=excluded.chunk_config_hash,
                locator_json=excluded.locator_json,
                vector_json=excluded.vector_json
            """,
            (
                item.chunk_id,
                item.document_id,
                item.version_id,
                item.display_name,
                item.canonical_uri,
                item.text,
                item.content_hash,
                item.source_hash,
                item.chunk_config_hash,
                canonical_json(item.locator.to_dict()),
                _encode_vector(self.encoder.encode(item.text)),
            ),
        )

    def _write_manifest(self, connection: sqlite3.Connection, corpus_hash: str, count: int) -> None:
        connection.execute(
            """
            INSERT INTO semantic_manifest(singleton, schema_version, encoder_fingerprint, corpus_hash, document_count)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                schema_version=excluded.schema_version,
                encoder_fingerprint=excluded.encoder_fingerprint,
                corpus_hash=excluded.corpus_hash,
                document_count=excluded.document_count
            """,
            (_SCHEMA_VERSION, self.encoder.config.fingerprint, corpus_hash, count),
        )

    def _read_documents(self, connection: sqlite3.Connection) -> tuple[SemanticDocument, ...]:
        return tuple(
            SemanticDocument(
                chunk_id=str(row[1]),
                document_id=str(row[2]),
                version_id=str(row[3]),
                display_name=str(row[4]),
                canonical_uri=str(row[5]),
                text=str(row[6]),
                content_hash=str(row[7]),
                source_hash=str(row[8]),
                chunk_config_hash=str(row[9]),
                locator=_locator(json.loads(str(row[10]))),
            )
            for row in connection.execute("SELECT * FROM semantic_chunks ORDER BY chunk_id")
        )


def _documents(rows: Iterable[SemanticDocument], maximum: int) -> tuple[SemanticDocument, ...]:
    result = tuple(rows)
    if len(result) > maximum:
        raise ValueError("semantic corpus exceeds max_documents")
    ids = [item.chunk_id for item in result]
    if len(ids) != len(set(ids)):
        raise ValueError("semantic corpus contains duplicate chunk_id values")
    return result


def _encode_vector(vector: Mapping[int, float]) -> str:
    return json.dumps(sorted(vector.items()), separators=(",", ":"))


def _decode_vector(encoded: str) -> dict[int, float]:
    return {int(index): float(value) for index, value in json.loads(encoded)}


def _cosine(left: Mapping[int, float], right: Mapping[int, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return max(0.0, sum(value * right.get(index, 0.0) for index, value in left.items()))


def _corpus_hash(documents: Sequence[SemanticDocument], encoder: str) -> str:
    return sha256_text(
        canonical_json(
            {
                "encoder": encoder,
                "chunks": [
                    {
                        "chunk_id": item.chunk_id,
                        "document_id": item.document_id,
                        "version_id": item.version_id,
                        "content_hash": item.content_hash,
                    }
                    for item in sorted(documents, key=lambda row: row.chunk_id)
                ],
            }
        )
    )


def _locator(payload: Mapping[str, Any]) -> ChunkLocator:
    return ChunkLocator(
        source_uri=str(payload["source_uri"]),
        heading_path=tuple(str(item) for item in payload.get("heading_path", ())),
        start_line=int(payload["start_line"]),
        end_line=int(payload["end_line"]),
        start_paragraph=int(payload["start_paragraph"]),
        end_paragraph=int(payload["end_paragraph"]),
        start_fragment=int(payload.get("start_fragment", 0)),
        end_fragment=int(payload.get("end_fragment", 0)),
        overlap_from_previous=bool(payload.get("overlap_from_previous", False)),
    )


__all__ = [
    "HashingEmbeddingConfig",
    "HashingSemanticEncoder",
    "SQLiteHashingVectorRetriever",
    "SemanticDocument",
]
