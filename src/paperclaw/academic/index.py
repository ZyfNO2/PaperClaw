"""Version-aware contracts and inspection seam for the academic object index."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import TYPE_CHECKING, Any

from .contracts import ACADEMIC_SCHEMA_VERSION, AcademicObject, EvidenceLocator
from .errors import (
    AcademicFingerprintMismatchError,
    AcademicIndexNotReadyError,
    AcademicIntegrityError,
    AcademicStaleIndexError,
    AcademicStaleSchemaError,
)

if TYPE_CHECKING:
    from .runtime import AcademicRuntime


ACADEMIC_INDEX_VERSION = "academic-object-index.v1"


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class AcademicIndexEntry:
    """Frozen identity and searchable metadata for one canonical paper object."""

    paper_id: str
    version_id: str
    source_hash: str
    object_id: str
    object_type: str
    page_number: int
    reading_order: int
    locator: EvidenceLocator
    text_hash: str | None
    asset_hashes: tuple[str, ...]
    provenance: str
    schema_version: str = ACADEMIC_SCHEMA_VERSION
    index_version: str = ACADEMIC_INDEX_VERSION

    @classmethod
    def from_object(cls, value: AcademicObject) -> AcademicIndexEntry:
        locator = value.locator
        return cls(
            paper_id=locator.paper_id,
            version_id=locator.version_id,
            source_hash=locator.source_hash,
            object_id=value.object_id,
            object_type=value.object_type,
            page_number=locator.page_number,
            reading_order=value.reading_order,
            locator=locator,
            text_hash=(
                hashlib.sha256(value.text.encode()).hexdigest()
                if value.text is not None
                else None
            ),
            asset_hashes=tuple(asset.asset_hash for asset in value.assets),
            provenance=value.provenance,
        )

    def __post_init__(self) -> None:
        identity = (
            self.locator.paper_id,
            self.locator.version_id,
            self.locator.source_hash,
            self.locator.object_id,
            self.locator.object_type,
            self.locator.page_number,
        )
        if identity != (
            self.paper_id,
            self.version_id,
            self.source_hash,
            self.object_id,
            self.object_type,
            self.page_number,
        ):
            raise ValueError("academic index entry identity does not match locator")
        if self.schema_version != ACADEMIC_SCHEMA_VERSION:
            raise ValueError("academic index entry has stale schema")
        if self.index_version != ACADEMIC_INDEX_VERSION:
            raise ValueError("academic index entry has stale index version")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["locator"] = self.locator.to_dict()
        value["asset_hashes"] = list(self.asset_hashes)
        return value


@dataclass(frozen=True)
class AcademicIndexManifest:
    """Deterministic snapshot of the active persisted object index."""

    generation_id: str
    corpus_hash: str
    model_fingerprint: str
    entries: tuple[AcademicIndexEntry, ...]
    content_hash: str
    schema_version: str = ACADEMIC_SCHEMA_VERSION
    index_version: str = ACADEMIC_INDEX_VERSION

    @classmethod
    def compute_content_hash(
        cls,
        *,
        generation_id: str,
        corpus_hash: str,
        model_fingerprint: str,
        entries: tuple[AcademicIndexEntry, ...],
    ) -> str:
        identity = {
            "schema_version": ACADEMIC_SCHEMA_VERSION,
            "index_version": ACADEMIC_INDEX_VERSION,
            "generation_id": generation_id,
            "corpus_hash": corpus_hash,
            "model_fingerprint": model_fingerprint,
            "entries": [entry.to_dict() for entry in entries],
        }
        return _digest(identity)

    @classmethod
    def create(
        cls,
        *,
        generation_id: str,
        corpus_hash: str,
        model_fingerprint: str,
        entries: tuple[AcademicIndexEntry, ...],
    ) -> AcademicIndexManifest:
        return cls(
            generation_id=generation_id,
            corpus_hash=corpus_hash,
            model_fingerprint=model_fingerprint,
            entries=entries,
            content_hash=cls.compute_content_hash(
                generation_id=generation_id,
                corpus_hash=corpus_hash,
                model_fingerprint=model_fingerprint,
                entries=entries,
            ),
        )

    def __post_init__(self) -> None:
        expected = type(self).compute_content_hash(
            generation_id=self.generation_id,
            corpus_hash=self.corpus_hash,
            model_fingerprint=self.model_fingerprint,
            entries=self.entries,
        )
        if self.content_hash != expected:
            raise ValueError("academic index manifest content hash mismatch")


class AcademicObjectIndex:
    """Expose one validated object-aware view over the existing persisted index."""

    def __init__(self, runtime: AcademicRuntime) -> None:
        self._runtime = runtime

    def rebuild(self) -> AcademicIndexManifest:
        self._runtime.build_index()
        return self.snapshot()

    def sync_version(self, paper_id: str, version_id: str) -> AcademicIndexManifest:
        self._runtime.sync_index_version(paper_id, version_id)
        return self.snapshot()

    def delete_version(self, paper_id: str, version_id: str) -> AcademicIndexManifest:
        previous = self.snapshot()
        self._runtime.papers.repository.get_version(
            self._runtime.project_id, paper_id, version_id
        )
        self._runtime.delete_index_version(paper_id, version_id)
        try:
            self._runtime.papers.delete_version(
                self._runtime.project_id, paper_id, version_id
            )
        except Exception:
            self._runtime._activate_index_generation(previous.generation_id)
            raise
        self._runtime.object_store.deactivate_version(paper_id, version_id)
        return self.snapshot()

    def snapshot(self) -> AcademicIndexManifest:
        with self._runtime._connect() as db:
            generation = db.execute(
                """
                SELECT generation_id,corpus_hash,model_fingerprint,state
                FROM index_generations WHERE active=1
                """
            ).fetchone()
            if generation is None or generation["state"] != "ready":
                raise AcademicIndexNotReadyError(
                    "academic object index is not ready"
                )
            locator_rows = db.execute(
                """
                SELECT locator_json FROM academic_index WHERE generation_id=?
                UNION
                SELECT locator_json FROM academic_visual_index WHERE generation_id=?
                """,
                (generation["generation_id"], generation["generation_id"]),
            ).fetchall()
        if (
            generation["model_fingerprint"]
            != self._runtime._runtime_model_fingerprint()
        ):
            raise AcademicFingerprintMismatchError(
                "academic object index encoder fingerprint is stale"
            )
        objects: dict[str, AcademicObject] = {}
        for row in locator_rows:
            locator = EvidenceLocator.from_dict(json.loads(row["locator_json"]))
            obj = self._runtime.resolve(locator)
            objects[obj.object_id] = obj
        entries = tuple(
            AcademicIndexEntry.from_object(obj)
            for obj in sorted(
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
        with self._runtime._connect() as db:
            stored = db.execute(
                """
                SELECT schema_version,index_version,content_hash
                FROM academic_index_manifests WHERE generation_id=?
                """,
                (manifest.generation_id,),
            ).fetchone()
        if stored is None:
            raise AcademicIntegrityError(
                "academic index integrity metadata is missing; rebuild"
            )
        if stored["schema_version"] != ACADEMIC_SCHEMA_VERSION:
            raise AcademicStaleSchemaError(
                "academic object index schema is stale; rebuild"
            )
        if stored["index_version"] != ACADEMIC_INDEX_VERSION:
            raise AcademicStaleIndexError(
                "academic object index version is stale; rebuild"
            )
        if stored["content_hash"] != manifest.content_hash:
            raise AcademicIntegrityError(
                "academic object index manifest integrity failure"
            )
        return manifest
