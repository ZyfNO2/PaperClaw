"""Backend-neutral deterministic hybrid retrieval with reciprocal-rank fusion."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Protocol, Sequence

from .contracts import canonical_json, sha256_text, stable_id
from .query import RankedResult, RetrievalCandidate, RetrievalRequest


class Retriever(Protocol):
    def query(self, request: RetrievalRequest) -> RankedResult: ...


class HybridCorpusMismatchError(RuntimeError):
    """Raised when retrieval backends do not describe the same active corpus."""


class HybridCandidateMismatchError(RuntimeError):
    """Raised when backends disagree about citation-bound chunk identity."""


class HybridRetriever:
    """Fuse ranked backends without changing citation-bound chunk identity.

    Backends must read the same corpus. Fusion uses weighted reciprocal rank and
    deterministic tie breaking by chunk ID. This class performs no network calls;
    semantic/vector backends are optional adapters supplied by the caller.
    """

    def __init__(
        self,
        backends: Sequence[tuple[str, Retriever, float]],
        *,
        rrf_constant: int = 60,
    ) -> None:
        if not backends:
            raise ValueError("at least one retrieval backend is required")
        if (
            isinstance(rrf_constant, bool)
            or not isinstance(rrf_constant, int)
            or rrf_constant < 1
        ):
            raise ValueError("rrf_constant must be a positive integer")
        names = [name for name, _backend, _weight in backends]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("retrieval backend names must be non-empty strings")
        if len(names) != len(set(names)):
            raise ValueError("retrieval backend names must be unique")
        for _name, _backend, weight in backends:
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(weight)
                or weight <= 0
            ):
                raise ValueError("retrieval backend weights must be finite and positive")
        self.backends = tuple(
            (name, backend, float(weight)) for name, backend, weight in backends
        )
        self.rrf_constant = rrf_constant

    def query(self, request: RetrievalRequest) -> RankedResult:
        expanded = replace(
            request,
            top_k=request.candidate_pool_size,
            candidate_pool_size=request.candidate_pool_size,
        )
        results = tuple(
            (name, weight, backend.query(expanded))
            for name, backend, weight in self.backends
        )
        corpus_hashes = {result.corpus_hash for _name, _weight, result in results}
        if len(corpus_hashes) != 1:
            raise HybridCorpusMismatchError(
                "hybrid retrieval backends returned different corpus hashes"
            )
        corpus_hash = next(iter(corpus_hashes))
        candidates: dict[str, RetrievalCandidate] = {}
        scores: dict[str, float] = {}
        for name, weight, result in results:
            backend_seen: set[str] = set()
            for candidate in result.candidates:
                if candidate.chunk_id in backend_seen:
                    raise HybridCandidateMismatchError(
                        f"retrieval backend {name} returned duplicate chunk_id"
                    )
                backend_seen.add(candidate.chunk_id)
                existing = candidates.get(candidate.chunk_id)
                if existing is not None and _citation_identity(existing) != _citation_identity(
                    candidate
                ):
                    raise HybridCandidateMismatchError(
                        "retrieval backends returned conflicting citation identity "
                        f"for chunk_id {candidate.chunk_id}"
                    )
                candidates.setdefault(candidate.chunk_id, candidate)
                scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + (
                    weight / (self.rrf_constant + candidate.rank)
                )
        ordered = sorted(
            candidates.values(),
            key=lambda candidate: (-scores[candidate.chunk_id], candidate.chunk_id),
        )[: request.top_k]
        fused = tuple(
            replace(
                candidate,
                rank=rank,
                bm25_score=scores[candidate.chunk_id],
            )
            for rank, candidate in enumerate(ordered, start=1)
        )
        manifests = sorted(
            result.manifest_id or "empty" for _name, _weight, result in results
        )
        manifest_id = (
            manifests[0]
            if len(set(manifests)) == 1 and manifests[0] != "empty"
            else stable_id("hybrid_manifest", corpus_hash, canonical_json(manifests))
        )
        request_id = stable_id(
            "hybrid_retrieval",
            request.request_id,
            canonical_json(
                [
                    {
                        "name": name,
                        "weight": weight,
                        "fingerprint": result.fingerprint,
                    }
                    for name, weight, result in results
                ]
            ),
        )
        return RankedResult(
            request_id=request_id,
            manifest_id=manifest_id,
            corpus_hash=corpus_hash,
            candidates=fused,
            total_matches=sum(result.total_matches for _n, _w, result in results),
            filtered_stale=sum(result.filtered_stale for _n, _w, result in results),
            filtered_duplicates=(
                sum(len(result.candidates) for _n, _w, result in results)
                - len(candidates)
                + sum(result.filtered_duplicates for _n, _w, result in results)
            ),
        )

    def close(self) -> None:
        closed: set[int] = set()
        for _name, backend, _weight in self.backends:
            if id(backend) in closed:
                continue
            closed.add(id(backend))
            close = getattr(backend, "close", None)
            if callable(close):
                close()


def _citation_identity(candidate: RetrievalCandidate) -> tuple[object, ...]:
    return (
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


def hybrid_configuration_fingerprint(
    backends: Sequence[tuple[str, float]],
    *,
    rrf_constant: int = 60,
) -> str:
    if (
        isinstance(rrf_constant, bool)
        or not isinstance(rrf_constant, int)
        or rrf_constant < 1
    ):
        raise ValueError("rrf_constant must be a positive integer")
    normalized: list[dict[str, object]] = []
    for name, weight in backends:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("retrieval backend names must be non-empty strings")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not math.isfinite(weight)
            or weight <= 0
        ):
            raise ValueError("retrieval backend weights must be finite and positive")
        normalized.append({"name": name, "weight": float(weight)})
    if len({item["name"] for item in normalized}) != len(normalized):
        raise ValueError("retrieval backend names must be unique")
    return sha256_text(
        canonical_json(
            {
                "backends": sorted(normalized, key=lambda item: str(item["name"])),
                "rrf_constant": rrf_constant,
            }
        )
    )


__all__ = [
    "HybridCandidateMismatchError",
    "HybridCorpusMismatchError",
    "HybridRetriever",
    "Retriever",
    "hybrid_configuration_fingerprint",
]
