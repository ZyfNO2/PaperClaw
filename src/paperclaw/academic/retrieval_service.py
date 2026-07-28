"""Grounded academic retrieval seam for PaperAgent and local callers."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    AcademicObject,
    AssetReference,
    EvidenceBundle,
    EvidenceLocator,
    RetrievalRequest,
    RetrievalResult,
)
from .runtime import AcademicRuntime


@dataclass(frozen=True)
class GroundedRetrievalHit:
    """A ranked candidate resolved back to its canonical object and assets."""

    object: AcademicObject
    neighbor_context: tuple[AcademicObject, ...] = ()
    assets: tuple[AssetReference, ...] = ()


@dataclass(frozen=True)
class RetrievalResponse:
    """One bounded retrieval result with canonical evidence and readback handles."""

    result: RetrievalResult
    bundle: EvidenceBundle
    hits: tuple[GroundedRetrievalHit, ...]


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
            raise ValueError("neighbor count must be in [0, 5]")
        if include_assets and not 1 <= max_asset_bytes <= 50 * 1024 * 1024:
            raise ValueError("asset byte budget must be in [1, 52428800]")

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
        remaining_asset_bytes = max_asset_bytes
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
                        continue
                    # read_asset performs identity, association and hash validation.
                    self._runtime.read_asset(obj.locator, asset.asset_hash)
                    assets.append(asset)
                    remaining_asset_bytes -= size
            hits.append(GroundedRetrievalHit(obj, tuple(neighbors), tuple(assets)))
        return RetrievalResponse(
            result, self._runtime.evidence_bundle(result), tuple(hits)
        )

    def resolve_locator(self, locator: EvidenceLocator) -> AcademicObject:
        return self._runtime.resolve(locator)

    def read_asset(self, locator: EvidenceLocator, asset_hash: str) -> bytes:
        return self._runtime.read_asset(locator, asset_hash)
