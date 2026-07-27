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
    RetrievalResult,
)
from .visual import VisualEncoder, late_interaction_score
from .text import DenseEncoder

_PARSER = "pymupdf"
_PARSER_VERSION = "1"
_MODEL_FINGERPRINT = "bm25+hashing-dense+colqwen2-base:unavailable"
_TOKENS = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class AcademicRuntime:
    def __init__(
        self,
        workspace: Path,
        project_id: str,
        *,
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
        self.visual_encoder = visual_encoder
        self.dense_encoder = dense_encoder
        self.memory = ProjectScopedMemoryStore(
            self.workspace / ".paperclaw" / "memory", project_id
        )
        self._init_db()

    @classmethod
    def for_workspace(
        cls,
        workspace: str | Path,
        project_id: str,
        *,
        visual_encoder: VisualEncoder | None = None,
        dense_encoder: DenseEncoder | None = None,
    ) -> "AcademicRuntime":
        if visual_encoder is None and os.getenv("PAPERCLAW_ACADEMIC_VISUAL") == "1":
            from .visual import ColQwen2Encoder

            visual_encoder = ColQwen2Encoder()
        if dense_encoder is None and os.getenv("PAPERCLAW_ACADEMIC_DENSE") == "1":
            from .text import MiniLMEncoder

            dense_encoder = MiniLMEncoder()
        return cls(
            Path(workspace).resolve(strict=True),
            project_id,
            visual_encoder=visual_encoder,
            dense_encoder=dense_encoder,
        )

    def parse_paper(self, paper_id: str) -> ParseResult:
        paper = self.papers.get_paper(self.project_id, paper_id)
        version = self.papers.repository.get_version(
            self.project_id, paper_id, paper.current_version_id
        )
        fingerprint = hashlib.sha256(
            f"{_PARSER}:{_PARSER_VERSION}:{version.sha256}".encode()
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
        if version.format != "pdf":
            raise ValueError("structured academic parser currently requires PDF")
        result = self._parse_pdf(
            paper_id, version.version_id, version.sha256, content, fingerprint
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
            in {"section", "paragraph", "caption", "table", "equation"}
        ]
        visual_objects = [
            item
            for item in parsed_objects
            if item.asset_hash and item.object_type in {"page", "figure", "table"}
        ]
        dense_fingerprint = (
            self.dense_encoder.fingerprint if self.dense_encoder else "hashing-dense"
        )
        model_fingerprint = (
            f"bm25+{dense_fingerprint}+{self.visual_encoder.fingerprint}"
            if self.visual_encoder
            else f"bm25+{dense_fingerprint}+visual:unavailable"
        )
        dense_vectors = (
            self.dense_encoder.encode_documents([item.text or "" for item in objects])
            if self.dense_encoder
            else [_vector(item.text or "") for item in objects]
        )
        corpus_hash = hashlib.sha256(
            "".join(f"{item.object_id}:{item.text}" for item in objects).encode()
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
        return IndexGeneration(
            generation_id,
            corpus_hash,
            model_fingerprint,
            "ready",
            len(objects) + len(visual_objects),
        )

    def retrieve(
        self, query: AcademicQuery, *, budget: RetrievalBudget = RetrievalBudget()
    ) -> RetrievalResult:
        if not query.text.strip():
            raise ValueError("query must not be empty")
        with self._connect() as db:
            active = db.execute(
                "SELECT generation_id FROM index_generations WHERE active=1"
            ).fetchone()
            if not active:
                raise RuntimeError("academic index is not ready")
            rows = db.execute(
                "SELECT object_id,text,locator_json,vector_json FROM academic_index WHERE generation_id=?",
                (active[0],),
            ).fetchall()
            visual_rows = db.execute(
                "SELECT object_id,locator_json,vector_json FROM academic_visual_index WHERE generation_id=?",
                (active[0],),
            ).fetchall()
        query_tokens = set(_tokens(query.text))
        query_vector = (
            self.dense_encoder.encode_query(query.text)
            if self.dense_encoder
            else _vector(query.text)
        )
        candidates = []
        for row in rows:
            locator = _locator(json.loads(row[2]))
            if query.paper_ids and locator.paper_id not in query.paper_ids:
                continue
            if query.object_types and locator.object_type not in query.object_types:
                continue
            text_tokens = set(_tokens(row[1]))
            lexical = len(query_tokens & text_tokens) / max(1, len(query_tokens))
            dense = _cosine(query_vector, json.loads(row[3]))
            visual = 0.0
            fused = 0.65 * lexical + 0.35 * dense
            candidates.append(
                RetrievalCandidate(
                    locator,
                    row[1],
                    {"lexical": lexical, "dense": dense, "visual": visual},
                    fused,
                    (
                        "bm25-compatible lexical",
                        "deterministic dense fallback",
                        "visual unavailable",
                    ),
                )
            )
        if self.visual_encoder and visual_rows:
            query_embedding = self.visual_encoder.encode_query(query.text)
            for row in visual_rows:
                locator = _locator(json.loads(row[1]))
                if query.paper_ids and locator.paper_id not in query.paper_ids:
                    continue
                if query.object_types and locator.object_type not in query.object_types:
                    continue
                visual = late_interaction_score(query_embedding, json.loads(row[2]))
                candidates.append(
                    RetrievalCandidate(
                        locator,
                        None,
                        {"lexical": 0.0, "dense": 0.0, "visual": visual},
                        visual,
                        ("ColQwen2 late-interaction visual score",),
                    )
                )
        candidates.sort(key=lambda item: (-item.fused_score, item.locator.object_id))
        selected = tuple(
            item for item in candidates[: budget.max_candidates] if item.fused_score > 0
        )
        top = selected[0].fused_score if selected else 0
        sufficiency = (
            "sufficient"
            if top >= 0.65
            else "partial"
            if top >= 0.25
            else "insufficient"
        )
        reasons = (
            ("matching grounded objects found",)
            if selected
            else ("no grounded object matched",)
        )
        return RetrievalResult(query.text, selected, sufficiency, reasons)

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
            "candidates": [
                {
                    "locator": item.locator.to_dict(),
                    "text": item.text,
                    "score": item.fused_score,
                }
                for item in result.candidates
            ],
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

    def _parse_pdf(self, paper_id, version_id, source_hash, content, fingerprint):
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
        objects = []
        order = 0
        doc_locator = AcademicLocator(
            paper_id, version_id, f"{version_id}:document", 1, "document", source_hash
        )
        objects.append(
            AcademicObject(doc_locator.object_id, "document", order, doc_locator)
        )
        headings: list[str] = []
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            pix = page.get_pixmap(dpi=120, alpha=False)
            asset = pix.tobytes("png")
            asset_hash = hashlib.sha256(asset).hexdigest()
            asset_path = self.assets / asset_hash[:2] / f"{asset_hash}.png"
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            if not asset_path.exists():
                asset_path.write_bytes(asset)
            order += 1
            page_locator = AcademicLocator(
                paper_id,
                version_id,
                f"{version_id}:page:{page_number}",
                page_number,
                "page",
                source_hash,
                bounding_box=BoundingBox(0, 0, page.rect.width, page.rect.height),
            )
            objects.append(
                AcademicObject(
                    page_locator.object_id,
                    "page",
                    order,
                    page_locator,
                    asset_hash=asset_hash,
                )
            )
            for block_index, block in enumerate(page.get_text("blocks", sort=True)):
                text = str(block[4]).strip()
                if not text:
                    continue
                bbox = BoundingBox(
                    float(block[0]), float(block[1]), float(block[2]), float(block[3])
                )
                is_heading = len(text) < 160 and (
                    block_index == 0 or re.match(r"^\d+(\.\d+)*\s+\S+", text)
                )
                normalized = text.lower().strip()
                object_type = "section" if is_heading else "paragraph"
                if normalized.startswith(("figure ", "fig. ", "图 ")):
                    object_type = "caption"
                elif normalized.startswith(("algorithm ", "算法 ")):
                    object_type = "algorithm"
                elif normalized.startswith(("references", "参考文献")):
                    object_type = "reference"
                elif re.search(r"[=∑∫√]|\\b(?:argmin|argmax)\\b", text):
                    object_type = "equation"
                if is_heading:
                    headings = [text.replace("\n", " ").strip()]
                order += 1
                object_id = f"{version_id}:{page_number}:{block_index}:{object_type}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    page_number,
                    object_type,
                    source_hash,
                    tuple(headings),
                    bbox,
                )
                objects.append(
                    AcademicObject(object_id, object_type, order, locator, text=text)
                )
            for drawing_index, drawing in enumerate(page.get_drawings()):
                rect = drawing.get("rect")
                if rect is None or rect.width < 10 or rect.height < 10:
                    continue
                clip = page.get_pixmap(clip=rect, dpi=120, alpha=False).tobytes("png")
                clip_hash = hashlib.sha256(clip).hexdigest()
                clip_path = self.assets / clip_hash[:2] / f"{clip_hash}.png"
                clip_path.parent.mkdir(parents=True, exist_ok=True)
                if not clip_path.exists():
                    clip_path.write_bytes(clip)
                order += 1
                object_id = f"{version_id}:{page_number}:drawing:{drawing_index}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    page_number,
                    "figure",
                    source_hash,
                    tuple(headings),
                    BoundingBox(rect.x0, rect.y0, rect.x1, rect.y1),
                )
                objects.append(
                    AcademicObject(
                        object_id, "figure", order, locator, asset_hash=clip_hash
                    )
                )
            try:
                tables = page.find_tables().tables
            except Exception:
                tables = ()
            for table_index, table in enumerate(tables):
                bbox = table.bbox
                order += 1
                object_id = f"{version_id}:{page_number}:table:{table_index}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    page_number,
                    "table",
                    source_hash,
                    tuple(headings),
                    BoundingBox(*map(float, bbox)),
                )
                table_text = "\n".join(
                    " | ".join(str(cell or "") for cell in row)
                    for row in table.extract()
                )
                objects.append(
                    AcademicObject(object_id, "table", order, locator, text=table_text)
                )
        document.close()
        return ParseResult(
            f"parse-{fingerprint}",
            paper_id,
            version_id,
            _PARSER,
            _PARSER_VERSION,
            fingerprint,
            "ready",
            len([o for o in objects if o.object_type == "page"]),
            tuple(objects),
        )

    def _init_db(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS parse_manifests(manifest_id TEXT PRIMARY KEY,paper_id TEXT,version_id TEXT,fingerprint TEXT UNIQUE,payload TEXT);
            CREATE TABLE IF NOT EXISTS index_generations(generation_id TEXT PRIMARY KEY,corpus_hash TEXT,model_fingerprint TEXT,state TEXT,object_count INTEGER,active INTEGER);
            CREATE TABLE IF NOT EXISTS academic_index(generation_id TEXT,object_id TEXT,text TEXT,locator_json TEXT,vector_json TEXT,PRIMARY KEY(generation_id,object_id));
            CREATE TABLE IF NOT EXISTS academic_visual_index(generation_id TEXT,object_id TEXT,locator_json TEXT,vector_json TEXT,PRIMARY KEY(generation_id,object_id));
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
    return AcademicLocator(
        value["paper_id"],
        value["version_id"],
        value["object_id"],
        value["page_number"],
        value["object_type"],
        value["source_hash"],
        tuple(value.get("section_path", ())),
        bbox,
    )


def _tokens(text):
    return [token.lower() for token in _TOKENS.findall(text)]


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
