"""Local academic parsing, indexing and evidence retrieval runtime."""

from __future__ import annotations

from dataclasses import asdict
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
    BoundingBox,
    IndexGeneration,
    ParseResult,
    RetrievalBudget,
    RetrievalCandidate,
    RetrievalRequest,
    RetrievalResult,
    RetrievalTrace,
)
from .fusion import ChannelWeight, DEFAULT_WEIGHTS, weighted_rrf
from .parser import PaperParser
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
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM parse_manifests WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
        if row:
            return self._parse_result(json.loads(row[0]))
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
        payload = self._result_dict(result)
        with self._connect() as db:
            db.execute(
                "INSERT INTO parse_manifests VALUES(?,?,?,?,?)",
                (
                    result.manifest_id,
                    paper_id,
                    version.version_id,
                    fingerprint,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            db.commit()
        return result

    def build_index(self) -> IndexGeneration:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM parse_manifests ORDER BY manifest_id"
            ).fetchall()
        parsed_objects = [
            item
            for row in rows
            for item in self._parse_result(json.loads(row[0])).objects
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
        generation_id = hashlib.sha256(
            f"{corpus_hash}:{model_fingerprint}".encode()
        ).hexdigest()
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
                    "UPDATE index_generations SET active=1 WHERE generation_id=? AND state='ready'",
                    (generation_id,),
                )
                db.commit()
        return IndexGeneration(
            generation_id,
            corpus_hash,
            model_fingerprint,
            "ready",
            len(objects) + len(visual_objects),
        )

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
                "SELECT generation_id,model_fingerprint FROM index_generations WHERE active=1"
            ).fetchone()
            if not active:
                raise RuntimeError("academic index is not ready")
            if active[1] != self._runtime_model_fingerprint():
                raise RuntimeError(
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

        locator_map: dict[str, AcademicLocator] = {}
        text_map: dict[str, str] = {}
        vector_map: dict[str, list[float]] = {}
        for row in rows:
            locator_map[row[0]] = _locator(json.loads(row[2]))
            text_map[row[0]] = row[1]
            vector_map[row[0]] = json.loads(row[3])

        def _passes_filters(locator: AcademicLocator) -> bool:
            if query.paper_ids and locator.paper_id not in query.paper_ids:
                return False
            if query.object_types and locator.object_type not in query.object_types:
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
        selected = tuple(candidates)
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
            {"corrective": 0, "conflict": 0},
            tuple(degraded),
            "budget_or_candidates_exhausted",
        )
        return RetrievalResult(query.text, selected, sufficiency, reasons, trace)

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
        paper = self.papers.get_paper(self.project_id, locator.paper_id)
        if paper.current_version_id != locator.version_id:
            raise KeyError(
                "academic locator references a superseded version; "
                "resolve is fail-closed for non-current versions"
            )
        result = self.get_parse(locator.paper_id, locator.version_id)
        for item in result.objects:
            if (
                item.object_id == locator.object_id
                and item.locator.source_hash == locator.source_hash
            ):
                return item
        raise KeyError("academic locator could not be resolved")

    def get_parse(self, paper_id: str, version_id: str) -> ParseResult:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM parse_manifests WHERE paper_id=? AND version_id=? ORDER BY rowid DESC LIMIT 1",
                (paper_id, version_id),
            ).fetchone()
        if not row:
            raise KeyError("paper version has not been parsed")
        return self._parse_result(json.loads(row[0]))

    def save_evidence_bundle(self, result: RetrievalResult) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "query": result.query,
            "sufficiency": result.sufficiency,
            "reasons": list(result.reasons),
            "candidates": [item.to_dict() for item in result.candidates],
            "trace": result.trace.to_dict() if result.trace else None,
        }
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
        return {
            "artifact_id": record.artifact_id,
            "artifact_type": record.artifact_type,
            "revision_number": revision.revision_number,
            "sufficiency": result.sufficiency,
        }

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
        return {
            "fingerprint": snapshot.fingerprint,
            "project": [entry.content for entry in snapshot.memory_entries],
            "user": [entry.content for entry in snapshot.user_entries],
        }

    def _init_db(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS parse_manifests(manifest_id TEXT PRIMARY KEY,paper_id TEXT,version_id TEXT,fingerprint TEXT UNIQUE,payload TEXT);
            CREATE TABLE IF NOT EXISTS index_generations(generation_id TEXT PRIMARY KEY,corpus_hash TEXT,model_fingerprint TEXT,state TEXT,object_count INTEGER,active INTEGER);
            CREATE TABLE IF NOT EXISTS academic_index(generation_id TEXT,object_id TEXT,text TEXT,locator_json TEXT,vector_json TEXT,PRIMARY KEY(generation_id,object_id));
            CREATE TABLE IF NOT EXISTS academic_visual_index(generation_id TEXT,object_id TEXT,locator_json TEXT,vector_json TEXT,PRIMARY KEY(generation_id,object_id));
            CREATE VIRTUAL TABLE IF NOT EXISTS academic_fts USING fts5(generation_id UNINDEXED,object_id UNINDEXED,text,tokenize='unicode61');
            """)
            db.commit()

    def _connect(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _result_dict(self, result):
        return {
            **asdict(result),
            "objects": [item.to_dict() for item in result.objects],
        }

    def _parse_result(self, payload):
        objects = tuple(
            AcademicObject(
                item["object_id"],
                item["object_type"],
                item["reading_order"],
                _locator(item["locator"]),
                item.get("text"),
                item.get("asset_hash"),
                item.get("provenance", "extracted"),
            )
            for item in payload["objects"]
        )
        return ParseResult(
            payload["manifest_id"],
            payload["paper_id"],
            payload["version_id"],
            payload["parser_name"],
            payload["parser_version"],
            payload["parser_fingerprint"],
            payload["status"],
            payload["page_count"],
            objects,
            tuple(payload.get("warnings", ())),
        )


def _locator(value):
    bbox = BoundingBox(**value["bounding_box"]) if value.get("bounding_box") else None
    line_range = tuple(value["line_range"]) if value.get("line_range") else None
    return AcademicLocator(
        value["paper_id"],
        value["version_id"],
        value["object_id"],
        value["page_number"],
        value["object_type"],
        value["source_hash"],
        tuple(value.get("section_path", ())),
        bbox,
        value.get("paragraph_index"),
        line_range,
        value.get("table_row"),
        value.get("table_column"),
    )


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
