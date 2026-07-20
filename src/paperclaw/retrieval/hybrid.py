"""Deterministic citation-preserving weighted hybrid retrieval."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import math
from typing import Protocol

from .contracts import canonical_json, sha256_text, stable_id
from .query import RankedResult, RetrievalCandidate, RetrievalRequest


class Retriever(Protocol):
    def query(self, request: RetrievalRequest) -> RankedResult: ...


@dataclass(frozen=True)
class RetrievalBackendAdapter:
    name: str
    backend: Retriever | Callable[[RetrievalRequest], RankedResult]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("retrieval backend name must be non-empty")
        if not callable(self.backend) and not callable(getattr(self.backend, "query", None)):
            raise TypeError("backend must be a Retriever or query callable")

    def query(self, request: RetrievalRequest) -> RankedResult:
        method = getattr(self.backend, "query", None)
        return method(request) if callable(method) else self.backend(request)  # type: ignore[misc,operator]

    def close(self) -> None:
        method = getattr(self.backend, "close", None)
        if callable(method):
            method()


@dataclass(frozen=True)
class WeightedRRFConfig:
    backend_weights: Mapping[str, float]
    rrf_constant: int = 60
    candidate_pool_size: int = 50

    def __post_init__(self) -> None:
        _positive_int(self.rrf_constant, "rrf_constant")
        if not 1 <= self.candidate_pool_size <= 10_000:
            raise ValueError("candidate_pool_size must be in [1, 10000]")
        normalized = {str(name).strip(): _weight(value) for name, value in self.backend_weights.items()}
        if not normalized or any(not name for name in normalized):
            raise ValueError("backend_weights must contain non-empty names")
        object.__setattr__(self, "backend_weights", normalized)


class HybridCorpusMismatchError(RuntimeError):
    pass


class HybridCandidateMismatchError(RuntimeError):
    pass


HybridRetrievalResult = RankedResult


class HybridRetriever:
    """Support the original tuple API and the v0.35 named-adapter API."""

    def __init__(
        self,
        backends: Sequence[tuple[str, Retriever, float] | RetrievalBackendAdapter],
        *,
        rrf_constant: int = 60,
        config: WeightedRRFConfig | None = None,
    ) -> None:
        if not backends:
            raise ValueError("at least one retrieval backend is required")
        rows: list[tuple[str, Retriever, float]] = []
        if config is None:
            _positive_int(rrf_constant, "rrf_constant")
            for item in backends:
                if isinstance(item, RetrievalBackendAdapter):
                    rows.append((item.name, item, 1.0))
                else:
                    name, backend, raw_weight = item
                    rows.append((name, backend, _weight(raw_weight)))
            self.rrf_constant = rrf_constant
            self.candidate_pool_size: int | None = None
        else:
            if not all(isinstance(item, RetrievalBackendAdapter) for item in backends):
                raise TypeError("config mode requires RetrievalBackendAdapter entries")
            names = {item.name for item in backends if isinstance(item, RetrievalBackendAdapter)}
            missing = sorted(names - set(config.backend_weights))
            extra = sorted(set(config.backend_weights) - names)
            if missing or extra:
                raise ValueError(f"backend weight mismatch: missing={missing} extra={extra}")
            for item in backends:
                assert isinstance(item, RetrievalBackendAdapter)
                rows.append((item.name, item, config.backend_weights[item.name]))
            self.rrf_constant = config.rrf_constant
            self.candidate_pool_size = config.candidate_pool_size
        names = [name for name, _backend, _value in rows]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("retrieval backend names must be non-empty strings")
        if len(names) != len(set(names)):
            raise ValueError("retrieval backend names must be unique")
        self.backends = tuple(rows)

    def query(self, request: RetrievalRequest) -> RankedResult:
        pool = max(request.top_k, self.candidate_pool_size or request.candidate_pool_size)
        expanded = replace(request, top_k=pool, candidate_pool_size=max(pool, request.candidate_pool_size))
        results = tuple((name, weight, backend.query(expanded)) for name, backend, weight in self.backends)
        corpus_hashes = {result.corpus_hash for _name, _weight, result in results}
        if len(corpus_hashes) != 1:
            raise HybridCorpusMismatchError("hybrid retrieval backends returned different corpus hashes")
        corpus_hash = next(iter(corpus_hashes))
        candidates: dict[str, RetrievalCandidate] = {}
        scores: dict[str, float] = {}
        for name, weight, result in results:
            seen: set[str] = set()
            for candidate in result.candidates:
                if candidate.chunk_id in seen:
                    raise HybridCandidateMismatchError(f"retrieval backend {name} returned duplicate chunk_id")
                seen.add(candidate.chunk_id)
                existing = candidates.get(candidate.chunk_id)
                if existing is not None and _identity(existing) != _identity(candidate):
                    raise HybridCandidateMismatchError(
                        f"retrieval backends returned conflicting citation identity for chunk_id {candidate.chunk_id}"
                    )
                candidates.setdefault(candidate.chunk_id, candidate)
                scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + weight / (
                    self.rrf_constant + candidate.rank
                )
        ordered = sorted(candidates.values(), key=lambda item: (-scores[item.chunk_id], item.chunk_id))[
            : request.top_k
        ]
        fused = tuple(
            replace(item, rank=rank, bm25_score=scores[item.chunk_id])
            for rank, item in enumerate(ordered, start=1)
        )
        manifests = sorted(result.manifest_id or "empty" for _name, _weight, result in results)
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
                    {"name": name, "weight": weight, "fingerprint": result.fingerprint}
                    for name, weight, result in results
                ]
            ),
        )
        return RankedResult(
            request_id=request_id,
            manifest_id=manifest_id,
            corpus_hash=corpus_hash,
            candidates=fused,
            total_matches=sum(result.total_matches for _name, _weight, result in results),
            filtered_stale=sum(result.filtered_stale for _name, _weight, result in results),
            filtered_duplicates=(
                sum(len(result.candidates) for _name, _weight, result in results)
                - len(candidates)
                + sum(result.filtered_duplicates for _name, _weight, result in results)
            ),
        )

    def close(self) -> None:
        closed: set[int] = set()
        for _name, backend, _weight in self.backends:
            if id(backend) not in closed:
                closed.add(id(backend))
                method = getattr(backend, "close", None)
                if callable(method):
                    method()


def _weight(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("retrieval backend weights must be finite and positive")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("retrieval backend weights must be finite and positive")
    return normalized


def _positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _identity(candidate: RetrievalCandidate) -> tuple[object, ...]:
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
    backends: Sequence[tuple[str, float]], *, rrf_constant: int = 60
) -> str:
    _positive_int(rrf_constant, "rrf_constant")
    normalized = [{"name": name, "weight": _weight(weight)} for name, weight in backends]
    if any(not isinstance(item["name"], str) or not str(item["name"]).strip() for item in normalized):
        raise ValueError("retrieval backend names must be non-empty strings")
    if len({item["name"] for item in normalized}) != len(normalized):
        raise ValueError("retrieval backend names must be unique")
    return sha256_text(
        canonical_json(
            {"backends": sorted(normalized, key=lambda item: str(item["name"])), "rrf_constant": rrf_constant}
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
