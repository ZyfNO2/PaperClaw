"""Backend-neutral deterministic hybrid retrieval with reciprocal-rank fusion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import math
from typing import Protocol, Sequence

from .contracts import canonical_json, sha256_text, stable_id
from .query import RankedResult, RetrievalCandidate, RetrievalRequest


class Retriever(Protocol):
    def query(self, request: RetrievalRequest) -> RankedResult: ...


@dataclass(frozen=True)
class RetrievalBackendAdapter:
    """Named adapter for a Retriever or a compatible query callable."""

    name: str
    backend: Retriever | Callable[[RetrievalRequest], RankedResult]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("retrieval backend name must be non-empty")
        if not callable(self.backend) and not callable(getattr(self.backend, "query", None)):
            raise TypeError("backend must be a Retriever or query callable")

    def query(self, request: RetrievalRequest) -> RankedResult:
        query = getattr(self.backend, "query", None)
        if callable(query):
            return query(request)
        return self.backend(request)  # type: ignore[misc,operator]

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()


@dataclass(frozen=True)
class WeightedRRFConfig:
    """Configuration for named weighted reciprocal-rank fusion."""

    backend_weights: Mapping[str, float]
    rrf_constant: int = 60
    candidate_pool_size: int = 50

    def __post_init__(self) -> None:
        if not isinstance(self.rrf_constant, int) or isinstance(self.rrf_constant, bool) or self.rrf_constant < 1:
            raise ValueError("rrf_constant must be a positive integer")
        if (
            not isinstance(self.candidate_pool_size, int)
            or isinstance(self.candidate_pool_size, bool)
            or not 1 <= self.candidate_pool_size <= 10_000
        ):
            raise ValueError("candidate_pool_size must be in [1, 10000]")
        normalized: dict[str, float] = {}
        for raw_name, raw_weight in self.backend_weights.items():
            name = str(raw_name).strip()
            if not name:
                raise ValueError("retrieval backend names must be non-empty")
            if (
                isinstance(raw_weight, bool)
                or not isinstance(raw_weight, (int, float))
                or not math.isfinite(float(raw_weight))
                or float(raw_weight) <= 0
            ):
                raise ValueError("retrieval backend weights must be finite and positive")
            normalized[name] = float(raw_weight)
        if not normalized:
            raise ValueError("backend_weights must not be empty")
        object.__setattr__(self, "backend_weights", normalized)


class HybridCorpusMismatchError(RuntimeError):
    """Raised when retrieval backends do not describe the same active corpus."""


class HybridCandidateMismatchError(RuntimeError):
    """Raised when backends disagree about citation-bound chunk identity."""


# Public semantic alias retained for the reranking layer. The stable wire/result
# contract remains RankedResult so existing callers do not need migration.
HybridRetrievalResult = RankedResult


class HybridRetriever:
    """Fuse ranked backends without changing citation-bound chunk identity.

    The original tuple API remains valid::

        HybridRetriever((("bm25", bm25, 1.0), ("semantic", semantic, 1.2)))

    v0.35 additionally supports named adapters and an explicit config::

        HybridRetriever(
            (RetrievalBackendAdapter("bm25", bm25), ...),
            config=WeightedRRFConfig({"bm25": 1.0, "semantic": 1.2}),
        )
    """

    def __init__(
        self,
        backends: Sequence[
            tuple[str, Retriever, float] | RetrievalBackendAdapter
        ],
        *,
        rrf_constant: int = 60,
        config: WeightedRRFConfig | None = None,
    ) -> None:
        if not backends:
            raise ValueError("at least one retrieval backend is required")

        normalized: list[tuple[str, Retriever, float]] = []
        if config is not None:
            adapter_names = {
                item.name
                for item in backends
                if isinstance(item, RetrievalBackendAdapter)
            }
            if len(adapter_names) != len(backends):
                raise TypeError("config mode requires RetrievalBackendAdapter entries")
            missing = sorted(adapter_names - set(config.backend_weights))
            extra = sorted(set(config.backend_weights) - adapter_names)
            if missing or extra:
                raise ValueError(f"backend weight mismatch: missing={missing} extra={extra}")
            for item in backends:
                assert isinstance(item, RetrievalBackendAdapter)
                normalized.append((item.name, item, config.backend_weights[item.name]))
            self.rrf_constant = config.rrf_constant
            self.candidate_pool_size: int | None = config.candidate_pool_size
        else:
            if (
                isinstance(rrf_constant, bool)
                or not isinstance(rrf_constant, int)
                or rrf_constant < 1
            ):
                raise ValueError("rrf_constant must be a positive integer")
            for item in backends:
                if isinstance(item, RetrievalBackendAdapter):
                    normalized.append((item.name, item, 1.0))
                else:
                    name, backend, weight = item
                    normalized.append((name, backend, float(weight)))
            self.rrf_constant = rrf_constant
            self.candidate_pool_size = None

        names = [name for name, _backend, _weight in normalized]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("retrieval backend names must be non-empty strings")
        if len(names) != len(set(names)):
            raise ValueError("retrieval backend names must be unique")
        for _name, _backend, weight in normalized:
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(weight)
                or weight <= 0
            ):
                raise ValueError("retrieval backend weights must be finite and positive")
        self.backends = tuple(normalized)

    def query(self, request: RetrievalRequest) -> HybridRetrievalResult:
        pool_size = self.candidate_pool_size or request.candidate_pool_size
        pool_size = max(request.top_k, pool_size)
        expanded = replace(
            request,
            top_k=pool_size,
            candidate_pool_size=max(request.candidate_pool_size, pool_size),
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
                if existing is not None and _citation_identity(existing) != _citation_identity(candidate):
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
    "HybridRetrievalResult",
    "HybridRetriever",
    "RetrievalBackendAdapter",
    "Retriever",
    "WeightedRRFConfig",
    "hybrid_configuration_fingerprint",
]
