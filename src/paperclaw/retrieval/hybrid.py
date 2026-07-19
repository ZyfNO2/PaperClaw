"""Backend-neutral deterministic hybrid retrieval with reciprocal-rank fusion."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol, Sequence

from .contracts import canonical_json, sha256_text, stable_id
from .query import RankedResult, RetrievalCandidate, RetrievalRequest


class Retriever(Protocol):
    def query(self, request: RetrievalRequest) -> RankedResult: ...


class HybridCorpusMismatchError(RuntimeError):
    """Raised when retrieval backends do not describe the same active corpus."""


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
        if rrf_constant < 1:
            raise ValueError("rrf_constant must be positive")
        names = [name for name, _backend, _weight in backends]
        if len(names) != len(set(names)) or any(not name.strip() for name in names):
            raise ValueError("retrieval backend names must be unique and non-empty")
        if any(weight <= 0 for _name, _backend, weight in backends):
            raise ValueError("retrieval backend weights must be positive")
        self.backends = tuple(backends)
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
        for _name, weight, result in results:
            for candidate in result.candidates:
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


def hybrid_configuration_fingerprint(
    backends: Sequence[tuple[str, float]],
    *,
    rrf_constant: int = 60,
) -> str:
    return sha256_text(
        canonical_json(
            {
                "backends": [
                    {"name": name, "weight": weight}
                    for name, weight in sorted(backends)
                ],
                "rrf_constant": rrf_constant,
            }
        )
    )


__all__ = [
    "HybridCorpusMismatchError",
    "HybridRetriever",
    "Retriever",
    "hybrid_configuration_fingerprint",
]
