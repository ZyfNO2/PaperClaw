"""Grounded academic retrieval seam for PaperAgent and local callers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .contracts import (
    AcademicObject,
    AssetReference,
    EvidenceBundle,
    EvidenceLocator,
    RetrievalRequest,
    RetrievalResult,
)
from .runtime import AcademicRuntime
from .index import ACADEMIC_INDEX_VERSION, ACADEMIC_SCHEMA_VERSION, AcademicObjectIndex
from .errors import (
    AcademicIntegrityError,
    AcademicInvalidBudgetError,
    AcademicLocatorNotFoundError,
)


@dataclass(frozen=True)
class GroundedRetrievalHit:
    """A ranked candidate resolved back to its canonical object and assets."""

    object: AcademicObject
    neighbor_context: tuple[AcademicObject, ...] = ()
    assets: tuple[AssetReference, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "object": self.object.to_dict(),
            "neighbor_context": [item.to_dict() for item in self.neighbor_context],
            "assets": [asdict(item) for item in self.assets],
        }


@dataclass(frozen=True)
class RetrievalResponse:
    """One bounded retrieval result with canonical evidence and readback handles."""

    result: RetrievalResult
    bundle: EvidenceBundle
    hits: tuple[GroundedRetrievalHit, ...]
    asset_bytes_used: int = 0
    assets_truncated: bool = False
    text_chars_used: int = 0
    text_truncated: bool = False
    index_metadata: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle": self.bundle.to_dict(),
            "hits": [item.to_dict() for item in self.hits],
            "asset_bytes_used": self.asset_bytes_used,
            "assets_truncated": self.assets_truncated,
            "text_chars_used": self.text_chars_used,
            "text_truncated": self.text_truncated,
            "index_metadata": self.index_metadata or {},
        }


class RetrievalService:
    """Deep module that validates, retrieves, resolves, expands and budgets evidence."""

    def __init__(self, runtime: AcademicRuntime) -> None:
        self._runtime = runtime

    @staticmethod
    def validate_options(
        *,
        include_assets: bool,
        include_neighbor_context: bool,
        neighbor_count: int,
        max_asset_bytes: int,
    ) -> None:
        if include_neighbor_context and not 0 <= neighbor_count <= 5:
            raise AcademicInvalidBudgetError("neighbor count must be in [0, 5]")
        if include_assets and not 1 <= max_asset_bytes <= 50 * 1024 * 1024:
            raise AcademicInvalidBudgetError(
                "asset byte budget must be in [1, 52428800]"
            )

    def search(
        self,
        request: RetrievalRequest,
        *,
        include_assets: bool = False,
        include_neighbor_context: bool = False,
        neighbor_count: int = 1,
        max_asset_bytes: int = 10 * 1024 * 1024,
    ) -> RetrievalResponse:
        """Return only candidates whose canonical locators still resolve."""

        self.validate_options(
            include_assets=include_assets,
            include_neighbor_context=include_neighbor_context,
            neighbor_count=neighbor_count,
            max_asset_bytes=max_asset_bytes,
        )
        result = self._runtime.retrieve(request)
        manifest = AcademicObjectIndex(self._runtime).snapshot()
        remaining_asset_bytes = max_asset_bytes
        assets_truncated = False
        hits: list[GroundedRetrievalHit] = []
        for candidate in result.candidates:
            obj = self.resolve_locator(candidate.locator)
            neighbors = (
                self._runtime.expand(candidate, neighbors=neighbor_count)
                if include_neighbor_context
                else ()
            )
            assets: list[AssetReference] = []
            if include_assets:
                for asset in obj.assets:
                    size = (
                        self._runtime.object_store.asset_path(asset.asset_hash)
                        .stat()
                        .st_size
                    )
                    if size > remaining_asset_bytes:
                        assets_truncated = True
                        continue
                    # read_asset performs identity, association and hash validation.
                    self._runtime.read_asset(obj.locator, asset.asset_hash)
                    assets.append(asset)
                    remaining_asset_bytes -= size
            hits.append(GroundedRetrievalHit(obj, tuple(neighbors), tuple(assets)))
        return RetrievalResponse(
            result,
            self._runtime.evidence_bundle(result),
            tuple(hits),
            max_asset_bytes - remaining_asset_bytes if include_assets else 0,
            assets_truncated,
            sum(len(candidate.text) for candidate in result.candidates),
            any(
                "text truncated by retrieval character budget" in candidate.explanation
                for candidate in result.candidates
            ),
            {
                "schema_version": ACADEMIC_SCHEMA_VERSION,
                "index_version": ACADEMIC_INDEX_VERSION,
                "generation_id": manifest.generation_id,
                "corpus_hash": manifest.corpus_hash,
                "model_fingerprint": manifest.model_fingerprint,
                "content_hash": manifest.content_hash,
            },
        )

    def resolve_locator(self, locator: EvidenceLocator) -> AcademicObject:
        try:
            return self._runtime.resolve(locator)
        except KeyError as exc:
            message = str(exc)
            if "integrity" in message or "hash" in message or "drift" in message:
                raise AcademicIntegrityError(message) from exc
            raise AcademicLocatorNotFoundError(message) from exc

    def read_asset(self, locator: EvidenceLocator, asset_hash: str) -> bytes:
        try:
            return self._runtime.read_asset(locator, asset_hash)
        except KeyError as exc:
            message = str(exc)
            if "integrity" in message or "hash" in message:
                raise AcademicIntegrityError(message) from exc
            raise AcademicLocatorNotFoundError(message) from exc
