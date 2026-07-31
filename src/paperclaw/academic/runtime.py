"""Local academic parsing, indexing and evidence retrieval runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from paperclaw.artifacts import ArtifactSourceLinks, FileArtifactStore
from paperclaw.papers import PaperService
from paperclaw.memory import ProjectScopedMemoryStore

from .contracts import (
    AcademicLocator,
    AcademicObject,
    AcademicQuery,
    ArtifactRevision,
    BoundingBox,
    EvidenceBundle,
    EvidenceLocator,
    IndexGeneration,
    MemoryEntrySnapshot,
    MemorySnapshot,
    ParseResult,
    RetrievalBudget,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalResult,
    RetrievalTrace,
)
from .fusion import DEFAULT_WEIGHTS, weighted_rrf
from .errors import (
    AcademicFingerprintMismatchError,
    AcademicIndexNotReadyError,
    AcademicIntegrityError,
    AcademicStaleIndexError,
    AcademicStaleSchemaError,
)
from .parser import PaperParser
from .store import AcademicObjectStore
from .visual import VisualEncoder, late_interaction_score
from .text import DenseEncoder

_MODEL_FINGERPRINT = "bm25+hashing-dense+colqwen2-base:unavailable"
_TOKENS = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_IDENTIFIERS = re.compile(
    r"\b(?:10\.\d{4,9}/[-._;()/:A-Za-z0-9]+|arXiv:\d{4}\.\d{4,5})\b",
    re.IGNORECASE,
)


class AcademicRuntime:
    def __init__(
        self,
        workspace: Path,
        project_id: str,
        *,
        parser: PaperParser | None = None,
        visual_encoder: VisualEncoder | None = None,
        dense_encoder: DenseEncoder | None = None,
    ) -> None:
        self.workspace = workspace
        self.project_id = project_id
        self.papers = PaperService.for_workspace(workspace, project_id=project_id)
        self.root = workspace / ".paperclaw" / "academic"
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "academic.sqlite3"
        self.assets = self.root / "assets"
        if parser is None:
            from .parsers import PyMuPDFParser

            parser = PyMuPDFParser()
        self.parser = parser
        self._parsers: dict[str, PaperParser] = {}
        self._register_parser(parser)
        from .parsers import LatexParser, MarkdownParser, TextParser

        for extra in (MarkdownParser(), TextParser(), LatexParser()):
            self._register_parser(extra)
        self.visual_encoder = visual_encoder
        self.dense_encoder = dense_encoder
        self.memory = ProjectScopedMemoryStore(
            self.workspace / ".paperclaw" / "memory", project_id
        )
        self._init_db()
        self.object_store = AcademicObjectStore(
            self.database,
            self.assets,
            version_source_hash=lambda paper_id, version_id: (
                self.papers.repository.get_version(
                    self.project_id, paper_id, version_id
                ).sha256
            ),
        )

    def _register_parser(self, parser: PaperParser) -> None:
        for fmt in parser.supported_formats:
            if fmt not in self._parsers:
                self._parsers[fmt] = parser

    @classmethod
    def for_workspace(
        cls,
        workspace: str | Path,
        project_id: str,
        *,
        parser: PaperParser | None = None,
        visual_encoder: VisualEncoder | None = None,
        dense_encoder: DenseEncoder | None = None,
    ) -> "AcademicRuntime":
        if parser is None and os.getenv("PAPERCLAW_ACADEMIC_PARSER") == "docling":
            from .parsers.docling_parser import DoclingParser

            parser = DoclingParser()
        if visual_encoder is None and os.getenv("PAPERCLAW_ACADEMIC_VISUAL") == "1":
            from .visual import ColQwen2Encoder

            visual_encoder = ColQwen2Encoder()
        if dense_encoder is None and os.getenv("PAPERCLAW_ACADEMIC_DENSE") == "1":
            from .text import MiniLMEncoder

            dense_encoder = MiniLMEncoder()
        return cls(
            Path(workspace).resolve(strict=True),
            project_id,
            parser=parser,
            visual_encoder=visual_encoder,
            dense_encoder=dense_encoder,
        )

    def parse_paper(self, paper_id: str) -> ParseResult:
        paper = self.papers.get_paper(self.project_id, paper_id)
        version = self.papers.repository.get_version(
            self.project_id, paper_id, paper.current_version_id
        )
        if version.format not in self._parsers:
            raise ValueError(
                f"no parser registered for format '{version.format}'; "
                f"supported: {sorted(self._parsers.keys())}"
            )
        active_parser = self._parsers[version.format]
        fingerprint = hashlib.sha256(
            f"{active_parser.fingerprint}:{version.sha256}".encode()
        ).hexdigest()
        existing = self.object_store.get_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        content = self.papers.read_version(
            self.project_id, paper_id, version.version_id
        )
        result = active_parser.parse(
            content,
            version.format,
            paper_id=paper_id,
            version_id=version.version_id,
            source_hash=version.sha256,
            asset_dir=self.assets,
        )
        if result.source_hash != version.sha256:
            raise ValueError(
                "parser returned a source hash that does not match paper version"
            )
        self.object_store.save(result, parse_fingerprint=fingerprint)
        return result

    def build_index(self, *, force_new_generation: bool = False) -> IndexGeneration:
        parsed_objects = [
            item
            for result in self.object_store.list_active()
            for item in result.objects
        ]
        objects = [
            item
            for item in parsed_objects
            if item.text
            and item.object_type
            in {"section", "paragraph", "caption", "table", "table_cell", "equation"}
        ]
        visual_objects = [
            item
            for item in parsed_objects
            if item.asset_hash and item.object_type in {"page", "figure", "table"}
        ]
        model_fingerprint = self._runtime_model_fingerprint()
        dense_vectors = (
            self.dense_encoder.encode_documents([item.text or "" for item in objects])
            if self.dense_encoder
            else [_vector(item.text or "") for item in objects]
        )
        corpus_hash = hashlib.sha256(
            "".join(
                [
                    f"text:{item.object_type}:{item.object_id}:{item.locator.source_hash}:{item.text}"
                    for item in objects
                ]
                + [
                    f"visual:{item.object_type}:{item.object_id}:{item.locator.source_hash}:{item.asset_hash}"
                    for item in visual_objects
                ]
            ).encode()
        ).hexdigest()
        generation_identity = f"{corpus_hash}:{model_fingerprint}"
        if force_new_generation:
            generation_identity = f"{generation_identity}:{uuid4().hex}"
        generation_id = hashlib.sha256(generation_identity.encode()).hexdigest()
        with self._connect() as db:
            existing = db.execute(
                "SELECT generation_id FROM index_generations WHERE generation_id=?",
                (generation_id,),
            ).fetchone()
            if not existing:
                db.execute("UPDATE index_generations SET active=0")
                db.execute(
                    "INSERT INTO index_generations VALUES(?,?,?,?,?,1)",
                    (
                        generation_id,
                        corpus_hash,
                        model_fingerprint,
                        "building",
                        len(objects) + len(visual_objects),
                    ),
                )
                db.execute(
                    "DELETE FROM academic_index WHERE generation_id=?", (generation_id,)
                )
                for item, dense_vector in zip(objects, dense_vectors, strict=True):
                    db.execute(
                        "INSERT INTO academic_index VALUES(?,?,?,?,?)",
                        (
                            generation_id,
                            item.object_id,
                            item.text,
                            json.dumps(item.locator.to_dict()),
                            json.dumps(dense_vector, separators=(",", ":")),
                        ),
                    )
                    db.execute(
                        "INSERT INTO academic_fts(generation_id,object_id,text) VALUES(?,?,?)",
                        (generation_id, item.object_id, item.text),
                    )
                if self.visual_encoder and visual_objects:
                    paths = [
                        self.assets / item.asset_hash[:2] / f"{item.asset_hash}.png"
                        for item in visual_objects
                    ]
                    embeddings = self.visual_encoder.encode_images(paths)
                    for item, embedding in zip(visual_objects, embeddings, strict=True):
                        db.execute(
                            "INSERT INTO academic_visual_index VALUES(?,?,?,?)",
                            (
                                generation_id,
                                item.object_id,
                                json.dumps(item.locator.to_dict()),
                                json.dumps(embedding, separators=(",", ":")),
                            ),
                        )
                db.execute(
                    "UPDATE index_generations SET state='ready' WHERE generation_id=?",
                    (generation_id,),
                )
                db.commit()
            else:
                db.execute("UPDATE index_generations SET active=0")
                db.execute(
                    "DELETE FROM academic_index_manifests WHERE generation_id=?",
                    (generation_id,),
                )
                db.execute(
                    "DELETE FROM academic_index WHERE generation_id=?",
                    (generation_id,),
                )
                db.execute(
                    "DELETE FROM academic_visual_index WHERE generation_id=?",
                    (generation_id,),
                )
                db.execute(
                    "DELETE FROM academic_fts WHERE generation_id=?",
                    (generation_id,),
                )
                for item, dense_vector in zip(objects, dense_vectors, strict=True):
                    db.execute(
                        "INSERT INTO academic_index VALUES(?,?,?,?,?)",
                        (
                            generation_id,
                            item.object_id,
                            item.text,
                            json.dumps(item.locator.to_dict()),
                            json.dumps(dense_vector, separators=(",", ":")),
                        ),
                    )
                    db.execute(
                        "INSERT INTO academic_fts(generation_id,object_id,text) VALUES(?,?,?)",
                        (generation_id, item.object_id, item.text),
                    )
                if self.visual_encoder and visual_objects:
                    paths = [
                        self.assets / item.asset_hash[:2] / f"{item.asset_hash}.png"
                        for item in visual_objects
                    ]
                    embeddings = self.visual_encoder.encode_images(paths)
                    for item, embedding in zip(visual_objects, embeddings, strict=True):
                        db.execute(
                            "INSERT INTO academic_visual_index VALUES(?,?,?,?)",
                            (
                                generation_id,
                                item.object_id,
                                json.dumps(item.locator.to_dict()),
                                json.dumps(embedding, separators=(",", ":")),
                            ),
                        )
                db.execute(
                    """
                    UPDATE index_generations
                    SET active=1,state='ready',object_count=?
                    WHERE generation_id=?
                    """,
                    (len(objects) + len(visual_objects), generation_id),
                )
                db.commit()
        generation = IndexGeneration(
            generation_id,
            corpus_hash,
            model_fingerprint,
            "ready",
            len(objects) + len(visual_objects),
        )
        self._seal_active_index()
        return generation

    def sync_index_version(self, paper_id: str, version_id: str) -> IndexGeneration:
        """Atomically upsert one parsed version into a copy-on-write generation."""

        parsed = self.object_store.get(paper_id, version_id)
        expected = self.papers.repository.get_version(
            self.project_id, paper_id, version_id
        )
        if parsed.source_hash != expected.sha256:
            raise AcademicIntegrityError(
                "parsed version source hash conflicts with paper store"
            )
        text_objects = [
            item
            for item in parsed.objects
            if item.text
            and item.object_type
            in {"section", "paragraph", "caption", "table", "table_cell", "equation"}
        ]
        visual_objects = [
            item
            for item in parsed.objects
            if item.asset_hash and item.object_type in {"page", "figure", "table"}
        ]
        model_fingerprint = self._runtime_model_fingerprint()
        vectors = (
            self.dense_encoder.encode_documents(
                [item.text or "" for item in text_objects]
            )
            if self.dense_encoder
            else [_vector(item.text or "") for item in text_objects]
        )
        with self._connect() as db:
            active = db.execute(
                """
                SELECT generation_id,model_fingerprint
                FROM index_generations WHERE active=1 AND state='ready'
                """
            ).fetchone()
            old_text = []
            old_visual = []
            if active is not None:
                if active["model_fingerprint"] != model_fingerprint:
                    raise AcademicFingerprintMismatchError(
                        "academic index model fingerprint is incompatible with runtime; "
                        "rebuild the index with the active encoders"
                    )
                old_text = db.execute(
                    """
                    SELECT object_id,text,locator_json,vector_json
                    FROM academic_index WHERE generation_id=?
                    """,
                    (active["generation_id"],),
                ).fetchall()
                old_visual = db.execute(
                    """
                    SELECT object_id,locator_json,vector_json
                    FROM academic_visual_index WHERE generation_id=?
                    """,
                    (active["generation_id"],),
                ).fetchall()
        text_rows = [
            (row["object_id"], row["text"], row["locator_json"], row["vector_json"])
            for row in old_text
            if (
                (locator := _locator(json.loads(row["locator_json"]))).paper_id,
                locator.version_id,
            )
            != (paper_id, version_id)
        ]
        text_rows.extend(
            (
                item.object_id,
                item.text or "",
                json.dumps(item.locator.to_dict()),
                json.dumps(vector, separators=(",", ":")),
            )
            for item, vector in zip(text_objects, vectors, strict=True)
        )
        visual_rows = [
            (row["object_id"], row["locator_json"], row["vector_json"])
            for row in old_visual
            if (
                (locator := _locator(json.loads(row["locator_json"]))).paper_id,
                locator.version_id,
            )
            != (paper_id, version_id)
        ]
        if self.visual_encoder and visual_objects:
            paths = [
                self.assets / item.asset_hash[:2] / f"{item.asset_hash}.png"
                for item in visual_objects
            ]
            embeddings = self.visual_encoder.encode_images(paths)
            visual_rows.extend(
                (
                    item.object_id,
                    json.dumps(item.locator.to_dict()),
                    json.dumps(embedding, separators=(",", ":")),
                )
                for item, embedding in zip(visual_objects, embeddings, strict=True)
            )
        return self._commit_index_generation(
            text_rows, visual_rows, model_fingerprint=model_fingerprint
        )

    def delete_index_version(self, paper_id: str, version_id: str) -> IndexGeneration:
        """Converge the active index after canonical version deletion."""

        with self._connect() as db:
            active = db.execute(
                """
                SELECT generation_id,model_fingerprint
                FROM index_generations WHERE active=1 AND state='ready'
                """
            ).fetchone()
            if active is None:
                raise AcademicIndexNotReadyError("academic index is not ready")
            text_rows = db.execute(
                """
                SELECT object_id,text,locator_json,vector_json
                FROM academic_index WHERE generation_id=?
                """,
                (active["generation_id"],),
            ).fetchall()
            visual_rows = db.execute(
                """
                SELECT object_id,locator_json,vector_json
                FROM academic_visual_index WHERE generation_id=?
                """,
                (active["generation_id"],),
            ).fetchall()
        kept_text = [
            (row["object_id"], row["text"], row["locator_json"], row["vector_json"])
            for row in text_rows
            if (
                (locator := _locator(json.loads(row["locator_json"]))).paper_id,
                locator.version_id,
            )
            != (paper_id, version_id)
        ]
        kept_visual = [
            (row["object_id"], row["locator_json"], row["vector_json"])
            for row in visual_rows
            if (
                (locator := _locator(json.loads(row["locator_json"]))).paper_id,
                locator.version_id,
            )
            != (paper_id, version_id)
        ]
        return self._commit_index_generation(
            kept_text,
            kept_visual,
            model_fingerprint=str(active["model_fingerprint"]),
        )

    def _commit_index_generation(
        self,
        text_rows: list[tuple[str, str, str, str]],
        visual_rows: list[tuple[str, str, str]],
        *,
        model_fingerprint: str,
    ) -> IndexGeneration:
        text_rows.sort(key=lambda row: row[0])
        visual_rows.sort(key=lambda row: row[0])
        corpus_hash = hashlib.sha256(
            json.dumps(
                {"text": text_rows, "visual": visual_rows},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        generation_identity = f"{corpus_hash}:{model_fingerprint}"
        generation_id = hashlib.sha256(generation_identity.encode()).hexdigest()
        created = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """
                SELECT state FROM index_generations WHERE generation_id=?
                """,
                (generation_id,),
            ).fetchone()
            if existing is None:
                created = True
                db.execute(
                    "INSERT INTO index_generations VALUES(?,?,?,?,?,0)",
                    (
                        generation_id,
                        corpus_hash,
                        model_fingerprint,
                        "building",
                        len(text_rows) + len(visual_rows),
                    ),
                )
                db.executemany(
                    "INSERT INTO academic_index VALUES(?,?,?,?,?)",
                    (
                        (generation_id, object_id, text, locator_json, vector_json)
                        for object_id, text, locator_json, vector_json in text_rows
                    ),
                )
                db.executemany(
                    "INSERT INTO academic_fts(generation_id,object_id,text) VALUES(?,?,?)",
                    (
                        (generation_id, object_id, text)
                        for object_id, text, _, _ in text_rows
                    ),
                )
                db.executemany(
                    "INSERT INTO academic_visual_index VALUES(?,?,?,?)",
                    (
                        (generation_id, object_id, locator_json, vector_json)
                        for object_id, locator_json, vector_json in visual_rows
                    ),
                )
                db.execute(
                    """
                    UPDATE index_generations SET state='ready'
                    WHERE generation_id=?
                    """,
                    (generation_id,),
                )
            elif existing["state"] != "ready":
                raise AcademicIntegrityError(
                    "matching academic index generation is not ready"
                )
            db.execute("UPDATE index_generations SET active=0")
            db.execute(
                """
                UPDATE index_generations SET active=1
                WHERE generation_id=? AND state='ready'
                """,
                (generation_id,),
            )
            db.commit()
        generation = IndexGeneration(
            generation_id,
            corpus_hash,
            model_fingerprint,
            "ready",
            len(text_rows) + len(visual_rows),
        )
        if created:
            self._seal_active_index()
        else:
            from .index import AcademicObjectIndex

            AcademicObjectIndex(self).snapshot()
        return generation

    def _seal_active_index(self) -> None:
        """Validate locators and persist the canonical active-manifest digest."""

        from .index import AcademicIndexEntry, AcademicIndexManifest

        with self._connect() as db:
            generation = db.execute(
                """
                SELECT generation_id,corpus_hash,model_fingerprint,state
                FROM index_generations WHERE active=1
                """
            ).fetchone()
            if generation is None or generation["state"] != "ready":
                raise AcademicIndexNotReadyError("academic index is not ready")
            rows = db.execute(
                """
                SELECT locator_json FROM academic_index WHERE generation_id=?
                UNION
                SELECT locator_json FROM academic_visual_index WHERE generation_id=?
                """,
                (generation["generation_id"], generation["generation_id"]),
            ).fetchall()
        objects: dict[tuple[str, str, str], AcademicObject] = {}
        for row in rows:
            locator = EvidenceLocator.from_dict(json.loads(row["locator_json"]))
            item = self.resolve(locator)
            objects[(locator.paper_id, locator.version_id, locator.object_id)] = item
        entries = tuple(
            AcademicIndexEntry.from_object(item)
            for item in sorted(
                objects.values(),
                key=lambda item: (
                    item.locator.paper_id,
                    item.locator.version_id,
                    item.reading_order,
                    item.object_id,
                ),
            )
        )
        manifest = AcademicIndexManifest.create(
            generation_id=str(generation["generation_id"]),
            corpus_hash=str(generation["corpus_hash"]),
            model_fingerprint=str(generation["model_fingerprint"]),
            entries=entries,
        )
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO academic_index_manifests(
                    generation_id,schema_version,index_version,content_hash
                ) VALUES(?,?,?,?)
                ON CONFLICT(generation_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    index_version=excluded.index_version,
                    content_hash=excluded.content_hash
                """,
                (
                    manifest.generation_id,
                    manifest.schema_version,
                    manifest.index_version,
                    manifest.content_hash,
                ),
            )
            db.commit()

    def _activate_index_generation(self, generation_id: str) -> None:
        """Rollback helper: reactivate one previously sealed ready generation."""

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            target = db.execute(
                """
                SELECT g.state,m.content_hash
                FROM index_generations g
                LEFT JOIN academic_index_manifests m USING(generation_id)
                WHERE g.generation_id=?
                """,
                (generation_id,),
            ).fetchone()
            if (
                target is None
                or target["state"] != "ready"
                or target["content_hash"] is None
            ):
                raise AcademicIntegrityError(
                    "rollback academic index generation is not sealed and ready"
                )
            db.execute("UPDATE index_generations SET active=0")
            db.execute(
                "UPDATE index_generations SET active=1 WHERE generation_id=?",
                (generation_id,),
            )
            db.commit()

    def retrieve(
        self,
        query: AcademicQuery | RetrievalRequest,
        *,
        budget: RetrievalBudget = RetrievalBudget(),
    ) -> RetrievalResult:
        if not query.text.strip():
            raise ValueError("query must not be empty")
        channels = (
            query.channels
            if isinstance(query, RetrievalRequest)
            else ("lexical", "dense", "visual")
        )
        if isinstance(query, RetrievalRequest):
            budget = query.budget
        with self._connect() as db:
            active = db.execute(
                """
                SELECT g.generation_id,g.model_fingerprint,g.state,
                       m.schema_version,m.index_version,m.content_hash
                FROM index_generations g
                LEFT JOIN academic_index_manifests m USING(generation_id)
                WHERE g.active=1
                """
            ).fetchone()
            if not active:
                raise AcademicIndexNotReadyError("academic index is not ready")
            from .index import ACADEMIC_INDEX_VERSION

            if active["state"] != "ready" or active["content_hash"] is None:
                raise AcademicIntegrityError(
                    "academic index integrity metadata is missing; rebuild"
                )
            if active["schema_version"] != "academic.v1":
                raise AcademicStaleSchemaError(
                    "academic index schema version is stale; rebuild"
                )
            if active["index_version"] != ACADEMIC_INDEX_VERSION:
                raise AcademicStaleIndexError(
                    "academic index version is stale; rebuild"
                )
            if active[1] != self._runtime_model_fingerprint():
                raise AcademicFingerprintMismatchError(
                    "academic index model fingerprint is incompatible with runtime; "
                    "rebuild the index with the active encoders"
                )
            generation_id = active[0]
            rows = db.execute(
                "SELECT object_id,text,locator_json,vector_json FROM academic_index WHERE generation_id=?",
                (generation_id,),
            ).fetchall()
            visual_rows = db.execute(
                "SELECT object_id,locator_json,vector_json FROM academic_visual_index WHERE generation_id=?",
                (generation_id,),
            ).fetchall()
        from .index import AcademicObjectIndex

        AcademicObjectIndex(self).snapshot()

        locator_map: dict[str, AcademicLocator] = {}
        text_map: dict[str, str] = {}
        vector_map: dict[str, list[float]] = {}
        for row in rows:
            locator_map[row[0]] = _locator(json.loads(row[2]))
            text_map[row[0]] = row[1]
            vector_map[row[0]] = json.loads(row[3])
        current_versions: dict[str, str] = {}

        def _passes_filters(locator: AcademicLocator) -> bool:
            if query.paper_ids and locator.paper_id not in query.paper_ids:
                return False
            if (
                isinstance(query, RetrievalRequest)
                and query.version_ids
                and locator.version_id not in query.version_ids
            ):
                return False
            if isinstance(query, RetrievalRequest) and not query.version_ids:
                if locator.paper_id not in current_versions:
                    try:
                        current_versions[locator.paper_id] = self.papers.get_paper(
                            self.project_id, locator.paper_id
                        ).current_version_id
                    except KeyError:
                        return False
                if locator.version_id != current_versions[locator.paper_id]:
                    return False
            if query.object_types and locator.object_type not in query.object_types:
                return False
            if isinstance(query, RetrievalRequest) and query.section_scope:
                section = " / ".join(locator.section_path).casefold()
                if not any(
                    scope.casefold() in section for scope in query.section_scope
                ):
                    return False
            return True

        query_identifiers = {
            value.casefold() for value in _IDENTIFIERS.findall(query.text)
        }
        degraded: list[str] = []
        channel_rankings: dict[str, list[tuple[str, float]]] = {}

        if "exact" in channels and query_identifiers:
            exact_scores: list[tuple[str, float]] = []
            for oid, text in text_map.items():
                if not _passes_filters(locator_map[oid]):
                    continue
                text_ids = {v.casefold() for v in _IDENTIFIERS.findall(text)}
                if query_identifiers <= text_ids:
                    exact_scores.append((oid, 1.0))
            if exact_scores:
                channel_rankings["exact"] = exact_scores

        if "lexical" in channels:
            lexical_scores = self._bm25_rank(
                generation_id, query.text, locator_map, _passes_filters
            )
            if lexical_scores:
                channel_rankings["lexical"] = lexical_scores

        if "dense" in channels:
            if self.dense_encoder:
                try:
                    query_vector = self.dense_encoder.encode_query(query.text)
                    dense_scores: list[tuple[str, float]] = []
                    for oid, vec in vector_map.items():
                        if not _passes_filters(locator_map[oid]):
                            continue
                        score = _cosine(query_vector, vec)
                        if score > 0.1:
                            dense_scores.append((oid, score))
                    dense_scores.sort(key=lambda x: -x[1])
                    if dense_scores:
                        channel_rankings["dense"] = dense_scores
                except Exception:
                    degraded.append("dense")
            else:
                degraded.append("dense")

        if "visual" in channels:
            if self.visual_encoder and visual_rows:
                try:
                    query_embedding = self.visual_encoder.encode_query(query.text)
                    visual_scores: list[tuple[str, float]] = []
                    for row in visual_rows:
                        locator = _locator(json.loads(row[1]))
                        if not _passes_filters(locator):
                            continue
                        score = late_interaction_score(
                            query_embedding, json.loads(row[2])
                        )
                        if score > 0:
                            visual_scores.append((row[0], score))
                    visual_scores.sort(key=lambda x: -x[1])
                    if visual_scores:
                        channel_rankings["visual"] = visual_scores
                except Exception:
                    degraded.append("visual")
            else:
                degraded.append("visual")

        fused = weighted_rrf(channel_rankings, DEFAULT_WEIGHTS)
        candidates: list[RetrievalCandidate] = []
        for item in fused[: budget.max_candidates]:
            locator = locator_map.get(item.object_id)
            if locator is None:
                for row in visual_rows:
                    if row[0] == item.object_id:
                        locator = _locator(json.loads(row[1]))
                        break
            if locator is None:
                continue
            candidates.append(
                RetrievalCandidate(
                    locator,
                    text_map.get(item.object_id, ""),
                    item.channel_scores,
                    item.fused_score,
                    tuple(
                        f"{ch}: rank {item.channel_ranks.get(ch, '-')}"
                        for ch in sorted(item.channel_scores.keys())
                    ),
                )
            )
        selected_values: list[RetrievalCandidate] = []
        remaining_chars = budget.max_chars
        for candidate in candidates:
            if remaining_chars <= 0:
                break
            text = candidate.text
            if len(text) > remaining_chars:
                candidate = replace(
                    candidate,
                    text=text[:remaining_chars],
                    explanation=(
                        *candidate.explanation,
                        "text truncated by retrieval character budget",
                    ),
                )
            selected_values.append(candidate)
            remaining_chars -= len(candidate.text)
        selected = tuple(selected_values)
        top = selected[0].fused_score if selected else 0.0
        sufficiency = (
            "sufficient"
            if top >= 0.02
            else "partial"
            if top >= 0.008
            else "insufficient"
        )
        reasons = (
            ("matching grounded objects found",)
            if selected
            else ("no grounded object matched",)
        )
        if channels == ("visual",) and "visual" in degraded:
            sufficiency = "insufficient"
            reasons = ("visual channel unavailable",)
        corrective_used = 0
        conflict_used = 0
        corrective_details: dict[str, object] = {}
        final_stop_reason = "budget_or_candidates_exhausted"
        from .conflicts import detect_evidence_conflicts

        primary_conflicts = detect_evidence_conflicts(
            _structured_candidates(selected, query.text)
        )
        if primary_conflicts and budget.max_conflict_rounds > 0:
            from .corrective import plan_corrective_retrieval

            conflict_used = 1
            original_request = (
                query
                if isinstance(query, RetrievalRequest)
                else RetrievalRequest(
                    query.text,
                    channels,
                    query.paper_ids,
                    query.object_types,
                    budget,
                )
            )
            conflict_reason = _corrective_reason_for_conflict(
                primary_conflicts[0].conflict_type
            )
            plan = plan_corrective_retrieval(
                original_request,
                reason=conflict_reason,
                identity_constraints=tuple(
                    dict.fromkeys(_IDENTIFIERS.findall(query.text))
                ),
                section_scope=(
                    original_request.section_scope
                    if isinstance(original_request, RetrievalRequest)
                    else ()
                ),
            )
            planned = plan.request()
            conflict_request = replace(
                planned,
                budget=replace(
                    planned.budget,
                    max_corrective_rounds=0,
                    max_conflict_rounds=0,
                ),
            )
            conflict_result = self._retrieve_single(conflict_request, generation_id)
            conflict_candidates = conflict_result.candidates
            remaining_conflicts = detect_evidence_conflicts(
                _structured_candidates(conflict_candidates, query.text)
            )
            if not conflict_candidates:
                remaining_conflicts = primary_conflicts
            before_ids = [item.locator.object_id for item in selected]
            after_ids = [item.locator.object_id for item in conflict_candidates]
            corrective_details = {
                "primary_reason": conflict_reason,
                "original_query": query.text,
                "rewritten_query": conflict_request.text,
                "strategy": primary_conflicts[0].recommended_corrective_strategy,
                "channel_changes": {
                    "before": list(channels),
                    "after": list(conflict_request.channels),
                },
                "filter_changes": {
                    "paper_ids": list(conflict_request.paper_ids),
                    "version_ids": list(conflict_request.version_ids),
                    "object_types_before": list(query.object_types),
                    "object_types_after": list(conflict_request.object_types),
                    "section_scope": list(conflict_request.section_scope),
                },
                "candidate_changes": {"before": before_ids, "after": after_ids},
                "original_conflicts": [
                    _conflict_dict(item) for item in primary_conflicts
                ],
                "resolved_conflicts": [
                    _conflict_dict(item)
                    for item in primary_conflicts
                    if _conflict_identity(item)
                    not in {_conflict_identity(other) for other in remaining_conflicts}
                ],
                "unresolved_conflicts": [
                    _conflict_dict(item) for item in remaining_conflicts
                ],
            }
            selected = conflict_candidates
            if remaining_conflicts:
                sufficiency = "insufficient"
                reasons = ("structured evidence conflict remains unresolved",)
                final_stop_reason = "conflict_unresolved"
            elif selected:
                sufficiency = conflict_result.sufficiency
                reasons = ("conflict round resolved structured evidence conflicts",)
                final_stop_reason = "conflict_resolved"
        if (
            not primary_conflicts
            and sufficiency == "insufficient"
            and budget.max_corrective_rounds > 0
        ):
            from .corrective import CorrectiveReason, plan_corrective_retrieval

            corrective_used = 1
            original_request = (
                query
                if isinstance(query, RetrievalRequest)
                else RetrievalRequest(
                    query.text,
                    channels,
                    query.paper_ids,
                    query.object_types,
                    budget,
                )
            )
            if channels == ("visual",) and "visual" in degraded:
                corrective_reason: CorrectiveReason = "channel_unavailable"
            elif query.paper_ids or query.object_types:
                corrective_reason = "filter_exhausted"
            else:
                corrective_reason = "no_candidates"
            identity_constraints = tuple(
                dict.fromkeys(_IDENTIFIERS.findall(query.text))
            )
            plan = plan_corrective_retrieval(
                original_request,
                reason=corrective_reason,
                identity_constraints=identity_constraints,
            )
            corrected_request = plan.request()
            corrective_result = self._retrieve_single(corrected_request, generation_id)
            primary_ids = [item.locator.object_id for item in selected]
            corrected_ids = [
                item.locator.object_id for item in corrective_result.candidates
            ]
            corrective_details = {
                "primary_reason": corrective_reason,
                "original_query": query.text,
                "rewritten_query": corrected_request.text,
                "channel_changes": {
                    "before": list(channels),
                    "after": list(corrected_request.channels),
                },
                "filter_changes": {
                    "paper_ids": list(corrected_request.paper_ids),
                    "version_ids": list(corrected_request.version_ids),
                    "object_types_before": list(query.object_types),
                    "object_types_after": list(corrected_request.object_types),
                },
                "budget_changes": {
                    "max_candidates": corrected_request.budget.max_candidates,
                    "max_chars": corrected_request.budget.max_chars,
                },
                "candidate_changes": {
                    "before": primary_ids,
                    "after": corrected_ids,
                },
                "resolved_conflicts": [],
                "unresolved_conflicts": ([] if corrected_ids else [corrective_reason]),
            }
            if (
                corrective_result.candidates
                and corrective_reason != "channel_unavailable"
            ):
                selected = corrective_result.candidates
                top = selected[0].fused_score
                sufficiency = (
                    "sufficient"
                    if top >= 0.02
                    else "partial"
                    if top >= 0.008
                    else "insufficient"
                )
                reasons = ("corrective round: relaxed filters produced matches",)
                degraded = (
                    list(corrective_result.trace.degraded_channels)
                    if corrective_result.trace
                    else degraded
                )
                final_stop_reason = "corrective_resolved"
            else:
                final_stop_reason = "corrective_unresolved"
        per_channel_top = {
            ch: ranked[0][1] if ranked else 0.0
            for ch, ranked in channel_rankings.items()
        }
        trace = RetrievalTrace(
            f"trace-{uuid4().hex}",
            hashlib.sha256(
                json.dumps(
                    {
                        "text": query.text,
                        "channels": channels,
                        "paper_ids": query.paper_ids,
                        "version_ids": (
                            query.version_ids
                            if isinstance(query, RetrievalRequest)
                            else ()
                        ),
                        "object_types": query.object_types,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            generation_id,
            tuple(channels),
            {
                "generation": self._runtime_model_fingerprint(),
                "per_channel_top": json.dumps(per_channel_top, sort_keys=True),
            },
            {
                "primary": 1,
                "corrective": corrective_used,
                "conflict": conflict_used,
            },
            tuple(degraded),
            final_stop_reason,
            corrective_details,
        )
        return RetrievalResult(query.text, selected, sufficiency, reasons, trace)

    def _retrieve_single(
        self, request: RetrievalRequest, generation_id: str
    ) -> RetrievalResult:
        return self.retrieve(request)

    def _bm25_rank(
        self,
        generation_id: str,
        query_text: str,
        locator_map: dict[str, AcademicLocator],
        passes_filters,
    ) -> list[tuple[str, float]]:
        tokens = _tokens(query_text)
        if not tokens:
            return []
        match_expr = " OR ".join(f'"{t}"*' for t in dict.fromkeys(tokens))
        try:
            with self._connect() as db:
                fts_rows = db.execute(
                    "SELECT object_id, bm25(academic_fts) AS rank"
                    " FROM academic_fts"
                    " WHERE academic_fts MATCH ? AND generation_id=?"
                    " ORDER BY rank LIMIT 200",
                    (match_expr, generation_id),
                ).fetchall()
        except Exception:
            return self._token_overlap_rank(query_text, locator_map, passes_filters)
        results: list[tuple[str, float]] = []
        for row in fts_rows:
            oid = row[0]
            locator = locator_map.get(oid)
            if locator is None or not passes_filters(locator):
                continue
            results.append((oid, -float(row[1])))
        if not results:
            return self._token_overlap_rank(query_text, locator_map, passes_filters)
        return results

    def _token_overlap_rank(
        self,
        query_text: str,
        locator_map: dict[str, AcademicLocator],
        passes_filters,
    ) -> list[tuple[str, float]]:
        query_tokens = set(_tokens(query_text))
        if not query_tokens:
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT object_id,text FROM academic_index WHERE generation_id=("
                "SELECT generation_id FROM index_generations WHERE active=1)"
            ).fetchall()
        scored: list[tuple[str, float]] = []
        for row in rows:
            locator = locator_map.get(row[0])
            if locator is None or not passes_filters(locator):
                continue
            text_tokens = set(_tokens(row[1]))
            overlap = len(query_tokens & text_tokens) / len(query_tokens)
            if overlap > 0:
                scored.append((row[0], overlap))
        scored.sort(key=lambda x: -x[1])
        return scored

    def expand(
        self, candidate: RetrievalCandidate, *, neighbors: int = 1
    ) -> tuple[AcademicObject, ...]:
        result = self.get_parse(
            candidate.locator.paper_id, candidate.locator.version_id
        )
        ordered = list(result.objects)
        index = next(
            i
            for i, item in enumerate(ordered)
            if item.object_id == candidate.locator.object_id
        )
        return tuple(ordered[max(0, index - neighbors) : index + neighbors + 1])

    def resolve(self, locator: AcademicLocator) -> AcademicObject:
        version = self.papers.repository.get_version(
            self.project_id, locator.paper_id, locator.version_id
        )
        if version.sha256 != locator.source_hash:
            raise KeyError("academic locator source hash does not match paper version")
        return self.object_store.resolve(locator)

    def read_asset(self, locator: AcademicLocator, asset_hash: str) -> bytes:
        # Resolve performs the full current-version and identity checks before
        # the object store verifies the attached content-addressed asset.
        self.resolve(locator)
        return self.object_store.read_asset(locator, asset_hash)

    def get_parse(self, paper_id: str, version_id: str) -> ParseResult:
        return self.object_store.get(paper_id, version_id)

    def save_evidence_bundle(self, result: RetrievalResult) -> dict[str, object]:
        bundle = self.evidence_bundle(result)
        payload = bundle.to_dict()
        store = FileArtifactStore(
            self.root / "product_artifacts", confinement_root=self.workspace
        )
        idempotency_key = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        record, revision, _ = store.create_artifact(
            idempotency_key=f"academic-evidence:{idempotency_key}",
            artifact_type="evidence_bundle",
            title=f"Evidence: {result.query[:120]}",
            content=json.dumps(payload, ensure_ascii=False).encode(),
            media_type="application/json",
            source=ArtifactSourceLinks(project_id=self.project_id),
        )
        canonical = ArtifactRevision(
            artifact_id=record.artifact_id,
            revision_id=revision.revision_id,
            revision_number=revision.revision_number,
            parent_revision_id=None,
            state="draft",
            content_hash=revision.content_hash,
            byte_length=revision.byte_length,
            media_type=revision.media_type,
            evidence=tuple(item.locator for item in result.candidates),
            created_at=datetime.fromtimestamp(revision.created_at, UTC).isoformat(),
        )
        return {
            **canonical.to_dict(),
            "artifact_type": record.artifact_type,
            "sufficiency": result.sufficiency,
        }

    def evidence_bundle(self, result: RetrievalResult) -> EvidenceBundle:
        if result.trace is None:
            raise ValueError("retrieval result has no trace")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "project_id": self.project_id,
                    "query": result.query,
                    "trace_id": result.trace.trace_id,
                    "locators": [item.locator.to_dict() for item in result.candidates],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return EvidenceBundle(
            bundle_id=f"evidence-{fingerprint}",
            project_id=self.project_id,
            query=result.query,
            candidates=result.candidates,
            sufficiency=result.sufficiency,
            reasons=result.reasons,
            trace=result.trace,
        )

    def _active_model_fingerprint(self) -> str:
        with self._connect() as db:
            row = db.execute(
                "SELECT model_fingerprint FROM index_generations WHERE active=1"
            ).fetchone()
        return str(row[0]) if row else "unavailable"

    def _runtime_model_fingerprint(self) -> str:
        dense = (
            self.dense_encoder.fingerprint if self.dense_encoder else "hashing-dense"
        )
        visual = (
            self.visual_encoder.fingerprint
            if self.visual_encoder
            else "visual:unavailable"
        )
        return f"{self.parser.fingerprint}+bm25+{dense}+{visual}"

    def save_research_artifact(
        self, artifact_type: str, title: str, payload: dict[str, object]
    ) -> dict[str, object]:
        allowed = {
            "paper_comparison",
            "baseline_card",
            "module_card",
            "compatibility_matrix",
            "evidence_bundle",
        }
        if artifact_type not in allowed:
            raise ValueError("unsupported academic artifact type")
        encoded = json.dumps(
            {"schema_version": 1, **payload}, ensure_ascii=False, sort_keys=True
        ).encode()
        key = hashlib.sha256(encoded).hexdigest()
        store = FileArtifactStore(
            self.root / "product_artifacts", confinement_root=self.workspace
        )
        record, revision, _ = store.create_artifact(
            idempotency_key=f"academic:{artifact_type}:{key}",
            artifact_type=artifact_type,
            title=title,
            media_type="application/json",
            content=encoded,
            source=ArtifactSourceLinks(project_id=self.project_id),
        )
        return {
            "artifact_id": record.artifact_id,
            "artifact_type": artifact_type,
            "revision_number": revision.revision_number,
        }

    def remember(self, scope: str, content: str) -> dict[str, object]:
        if scope not in {"project", "user"}:
            raise ValueError("academic memory scope must be project or user")
        target = "memory" if scope == "project" else "user"
        category = "project" if scope == "project" else "preference"
        entry = self.memory.add(
            target, content, category=category, source="academic_user_confirmed"
        )
        return {
            "entry_id": entry.entry_id,
            "scope": scope,
            "content_hash": entry.content_hash,
        }

    def memory_snapshot(self) -> dict[str, object]:
        snapshot = self.memory.snapshot()
        entries = tuple(
            MemoryEntrySnapshot(
                entry.entry_id,
                scope,
                entry.category,
                entry.content,
                entry.content_hash,
                entry.updated_at,
            )
            for scope, collection in (
                ("project", snapshot.memory_entries),
                ("user", snapshot.user_entries),
            )
            for entry in collection
        )
        canonical = MemorySnapshot(
            project_id=self.project_id,
            entries=entries,
            used_chars={
                "project": snapshot.memory_used_chars,
                "user": snapshot.user_used_chars,
                "task": 0,
            },
            limit_chars={
                "project": snapshot.memory_limit_chars,
                "user": snapshot.user_limit_chars,
                "task": 0,
            },
            fingerprint=snapshot.fingerprint,
            generated_at=datetime.now(UTC).isoformat(),
        ).to_dict()
        # Deprecated convenience projections retained for the 0.43 Python
        # interface; REST/CLI/Desktop use the canonical entries collection.
        canonical["project"] = [entry.content for entry in snapshot.memory_entries]
        canonical["user"] = [entry.content for entry in snapshot.user_entries]
        return canonical

    def _init_db(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS parse_manifests(manifest_id TEXT PRIMARY KEY,paper_id TEXT,version_id TEXT,fingerprint TEXT UNIQUE,payload TEXT);
            CREATE TABLE IF NOT EXISTS index_generations(generation_id TEXT PRIMARY KEY,corpus_hash TEXT,model_fingerprint TEXT,state TEXT,object_count INTEGER,active INTEGER);
            CREATE TABLE IF NOT EXISTS academic_index(generation_id TEXT,object_id TEXT,text TEXT,locator_json TEXT,vector_json TEXT,PRIMARY KEY(generation_id,object_id));
            CREATE TABLE IF NOT EXISTS academic_visual_index(generation_id TEXT,object_id TEXT,locator_json TEXT,vector_json TEXT,PRIMARY KEY(generation_id,object_id));
            CREATE TABLE IF NOT EXISTS academic_index_manifests(
                generation_id TEXT PRIMARY KEY REFERENCES index_generations(generation_id),
                schema_version TEXT NOT NULL,
                index_version TEXT NOT NULL,
                content_hash TEXT NOT NULL CHECK(length(content_hash)=64)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS academic_fts USING fts5(generation_id UNINDEXED,object_id UNINDEXED,text,tokenize='unicode61');
            """)
            db.commit()

    def _connect(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _result_dict(self, result):
        return result.to_dict()

    def _parse_result(self, payload):
        objects = tuple(AcademicObject.from_dict(item) for item in payload["objects"])
        source_hash = payload.get("source_hash")
        if source_hash is None and objects:
            source_hash = objects[0].locator.source_hash
        return ParseResult(
            payload["manifest_id"],
            payload["paper_id"],
            payload["version_id"],
            source_hash,
            payload["parser_name"],
            payload["parser_version"],
            payload["parser_fingerprint"],
            payload["status"],
            payload["page_count"],
            objects,
            tuple(payload.get("warnings", ())),
        )


def _locator(value):
    return AcademicLocator.from_dict(value)


def _tokens(text):
    return [token.lower() for token in _TOKENS.findall(text)]


def _safe_bbox(values, page_width, page_height):
    x0, y0, x1, y1 = values
    width = max(0.0, float(page_width))
    height = max(0.0, float(page_height))
    left = min(width, max(0.0, min(x0, x1)))
    right = min(width, max(left, max(x0, x1)))
    top = min(height, max(0.0, min(y0, y1)))
    bottom = min(height, max(top, max(y0, y1)))
    return BoundingBox(left, top, right, bottom)


def _vector(text, dimensions=128):
    vector = [0.0] * dimensions
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1
    return [value / norm for value in vector]


def _vector_json(text):
    return json.dumps(_vector(text), separators=(",", ":"))


def _cosine(left, right):
    return sum(float(a) * float(b) for a, b in zip(left, right))


_METRIC_FACT = re.compile(
    r"\b(?P<metric>[A-Za-z][A-Za-z0-9_. -]{0,30}?)\s*"
    r"(?:=|:|\bis\b)\s*(?P<value>-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|ratio|mm|cm|m|ms|s|dB|fps)?\b",
    re.IGNORECASE,
)
_LABELED_FACT = re.compile(
    r"\b(?P<label>dataset|split)\s*(?:=|:|\bis\b)\s*"
    r"(?P<value>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


def _structured_candidates(
    candidates: tuple[RetrievalCandidate, ...],
    query_text: str,
):
    from .conflicts import StructuredEvidence

    structured = []
    for candidate in candidates:
        metric_match = _METRIC_FACT.search(candidate.text)
        labels = {
            match.group("label").casefold(): match.group("value")
            for match in _LABELED_FACT.finditer(candidate.text)
        }
        identifiers = _IDENTIFIERS.findall(candidate.text)
        doi = next(
            (value for value in identifiers if value.casefold().startswith("10.")),
            None,
        )
        arxiv_id = next(
            (value for value in identifiers if value.casefold().startswith("arxiv:")),
            None,
        )
        metric = metric_match.group("metric").strip() if metric_match else None
        claim_key = (
            metric.casefold()
            if metric
            else hashlib.sha256(" ".join(_tokens(query_text)).encode()).hexdigest()
        )
        structured.append(
            StructuredEvidence(
                evidence_id=(
                    f"{candidate.locator.paper_id}:"
                    f"{candidate.locator.version_id}:"
                    f"{candidate.locator.object_id}"
                ),
                claim_key=claim_key,
                locator=candidate.locator,
                doi=doi,
                arxiv_id=arxiv_id,
                metric=metric,
                value=metric_match.group("value") if metric_match else None,
                unit=metric_match.group("unit") if metric_match else None,
                dataset=labels.get("dataset"),
                split=labels.get("split"),
            )
        )
    return tuple(structured)


def _corrective_reason_for_conflict(conflict_type: str):
    from .corrective import CorrectiveReason

    mapping: dict[str, CorrectiveReason] = {
        "identity": "identity_conflict",
        "metric_value": "metric_conflict",
        "unit": "unit_conflict",
        "paper_version": "version_conflict",
        "superseded_locator": "version_conflict",
        "dataset": "metric_conflict",
        "split": "metric_conflict",
        "direction": "metric_conflict",
        "method_configuration": "metric_conflict",
    }
    return mapping[conflict_type]


def _conflict_identity(conflict) -> tuple[object, ...]:
    return (conflict.conflict_type, conflict.evidence_ids, conflict.reason)


def _conflict_dict(conflict) -> dict[str, object]:
    return {
        "conflict_type": conflict.conflict_type,
        "evidence_ids": list(conflict.evidence_ids),
        "locator_versions": list(conflict.locator_versions),
        "reason": conflict.reason,
        "severity": conflict.severity,
        "recommended_corrective_strategy": conflict.recommended_corrective_strategy,
    }
