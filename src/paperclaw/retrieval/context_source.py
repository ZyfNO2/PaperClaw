"""RAG ContextSource, citation anchors and abstention policy for v0.09.1."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from paperclaw.context.orchestration import ContextCandidate, ContextRequest
from paperclaw.context.source_registry import (
    ContextSourceDescriptor,
    ContextSourceRegistry,
)
from paperclaw.retrieval.contracts import ChunkLocator, canonical_json, stable_id
from paperclaw.retrieval.query import (
    BrokenIndexError,
    RankedResult,
    RetrievalCandidate,
    RetrievalRequest,
    SQLiteBM25Retriever,
    StaleIndexError,
)

_TASK_SECTION = re.compile(r"\[Task\]\s*(.*?)(?:\n\[History\]|\Z)", re.DOTALL)
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "could",
        "did", "do", "does", "for", "from", "how", "in", "is", "it", "of",
        "on", "or", "should", "that", "the", "this", "to", "use", "using",
        "was", "were", "what", "when", "where", "which", "who", "why", "with",
        "would",
    }
)


@dataclass(frozen=True)
class CitationAnchor:
    """Stable citation target bound to one active retrieval candidate."""

    anchor_id: str
    label: str
    manifest_id: str | None
    corpus_hash: str
    chunk_id: str
    document_id: str
    version_id: str
    display_name: str
    canonical_uri: str
    content_hash: str
    locator: ChunkLocator

    @classmethod
    def from_candidate(
        cls,
        candidate: RetrievalCandidate,
        *,
        manifest_id: str | None,
        corpus_hash: str,
    ) -> "CitationAnchor":
        anchor_id = stable_id(
            "citation",
            manifest_id or "empty",
            corpus_hash,
            candidate.chunk_id,
            candidate.version_id,
            candidate.content_hash,
            canonical_json(candidate.locator.to_dict()),
        )
        return cls(
            anchor_id=anchor_id,
            label=f"[C-{anchor_id[-10:]}]",
            manifest_id=manifest_id,
            corpus_hash=corpus_hash,
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            version_id=candidate.version_id,
            display_name=candidate.display_name,
            canonical_uri=candidate.canonical_uri,
            content_hash=candidate.content_hash,
            locator=candidate.locator,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["locator"] = self.locator.to_dict()
        return data


@dataclass(frozen=True)
class RetrievalGroundingPolicy:
    top_k: int = 5
    candidate_pool_size: int = 50
    min_candidates: int = 1
    min_unique_documents: int = 1
    abstain_on_index_error: bool = True

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.candidate_pool_size < self.top_k:
            raise ValueError("candidate_pool_size must be at least top_k")
        if self.min_candidates <= 0 or self.min_candidates > self.top_k:
            raise ValueError("min_candidates must be in [1, top_k]")
        if self.min_unique_documents <= 0:
            raise ValueError("min_unique_documents must be positive")


@dataclass(frozen=True)
class RetrievalGroundingDecision:
    status: Literal["answerable", "abstain"]
    reason: str
    query: str
    manifest_id: str | None
    corpus_hash: str | None
    anchor_ids: tuple[str, ...]
    result_fingerprint: str | None = None

    @property
    def answerable(self) -> bool:
        return self.status == "answerable"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["answerable"] = self.answerable
        return data


class RetrievalContextSource:
    """Convert active BM25 results into untrusted, citation-bound candidates."""

    def __init__(
        self,
        retriever: SQLiteBM25Retriever,
        *,
        policy: RetrievalGroundingPolicy | None = None,
    ) -> None:
        self.retriever = retriever
        self.policy = policy or RetrievalGroundingPolicy()
        self.last_result: RankedResult | None = None
        self.last_anchors: tuple[CitationAnchor, ...] = ()
        self.last_decision: RetrievalGroundingDecision | None = None

    def collect(self, request: ContextRequest) -> tuple[ContextCandidate, ...]:
        query = extract_retrieval_query(request.raw_prompt)
        try:
            result = self.retriever.query(
                RetrievalRequest(
                    query=query,
                    top_k=self.policy.top_k,
                    candidate_pool_size=self.policy.candidate_pool_size,
                    deduplicate=True,
                )
            )
        except (BrokenIndexError, StaleIndexError) as exc:
            if not self.policy.abstain_on_index_error:
                raise
            self.last_result = None
            self.last_anchors = ()
            self.last_decision = RetrievalGroundingDecision(
                status="abstain",
                reason=f"retrieval_index_unavailable:{type(exc).__name__}",
                query=query,
                manifest_id=None,
                corpus_hash=None,
                anchor_ids=(),
            )
            return (_abstention_candidate(self.last_decision),)

        self.last_result = result
        unique_candidates = _defensive_unique_active_candidates(result.candidates)
        anchors = tuple(
            CitationAnchor.from_candidate(
                candidate,
                manifest_id=result.manifest_id,
                corpus_hash=result.corpus_hash,
            )
            for candidate in unique_candidates
        )
        unique_documents = {anchor.document_id for anchor in anchors}
        if (
            len(anchors) < self.policy.min_candidates
            or len(unique_documents) < self.policy.min_unique_documents
        ):
            self.last_anchors = ()
            self.last_decision = RetrievalGroundingDecision(
                status="abstain",
                reason="insufficient_retrieval_evidence",
                query=query,
                manifest_id=result.manifest_id,
                corpus_hash=result.corpus_hash,
                anchor_ids=(),
                result_fingerprint=result.fingerprint,
            )
            return (_abstention_candidate(self.last_decision),)

        self.last_anchors = anchors
        self.last_decision = RetrievalGroundingDecision(
            status="answerable",
            reason="retrieval_evidence_available",
            query=query,
            manifest_id=result.manifest_id,
            corpus_hash=result.corpus_hash,
            anchor_ids=tuple(anchor.anchor_id for anchor in anchors),
            result_fingerprint=result.fingerprint,
        )
        return tuple(
            _retrieval_candidate(candidate, anchor, rank=index)
            for index, (candidate, anchor) in enumerate(
                zip(unique_candidates, anchors),
                start=1,
            )
        )


def register_retrieval_context_source(
    registry: ContextSourceRegistry,
    source: RetrievalContextSource,
    *,
    source_id: str = "rag.bm25_retrieval",
    priority: int = 90,
) -> ContextSourceDescriptor:
    return registry.register(
        source_id,
        source,
        kind="retrieval",
        priority=priority,
        scopes=("shared",),
    )


def extract_retrieval_query(raw_prompt: str) -> str:
    """Extract task terms and remove fixed stopwords before BM25 retrieval."""

    match = _TASK_SECTION.search(raw_prompt)
    task = match.group(1) if match else raw_prompt
    tokens = []
    seen: set[str] = set()
    for token in _WORD.findall(task.casefold()):
        if token in _STOPWORDS or len(token) < 2 or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    if not tokens:
        return "no_retrieval_query_terms"
    return " ".join(tokens)[:2_000]


def _defensive_unique_active_candidates(
    candidates: tuple[RetrievalCandidate, ...],
) -> tuple[RetrievalCandidate, ...]:
    seen_chunks: set[str] = set()
    seen_content: set[str] = set()
    selected: list[RetrievalCandidate] = []
    for candidate in candidates:
        if candidate.chunk_id in seen_chunks or candidate.content_hash in seen_content:
            continue
        seen_chunks.add(candidate.chunk_id)
        seen_content.add(candidate.content_hash)
        selected.append(candidate)
    return tuple(selected)


def _retrieval_candidate(
    candidate: RetrievalCandidate,
    anchor: CitationAnchor,
    *,
    rank: int,
) -> ContextCandidate:
    locator = candidate.locator
    content = (
        f"{anchor.label} source={anchor.canonical_uri} "
        f"lines={locator.start_line}-{locator.end_line} "
        f"paragraphs={locator.start_paragraph}-{locator.end_paragraph}\n"
        f"{candidate.text}"
    )
    return ContextCandidate(
        candidate_id=f"retrieval:{candidate.chunk_id}",
        source="bm25_retrieval",
        source_ref=anchor.anchor_id,
        layer="L4",
        kind="evidence_ref",
        scope=("shared",),
        priority=max(1, 500 - rank),
        trust="external_untrusted",
        freshness=0,
        estimated_tokens=max(1, (len(content) + 3) // 4),
        content=content,
        bucket="retrieval",
        metadata={
            "citation_anchor": anchor.to_dict(),
            "rank": rank,
            "bm25_score": candidate.bm25_score,
            "manifest_id": anchor.manifest_id,
            "corpus_hash": anchor.corpus_hash,
            "stale_filtered": True,
            "duplicate_filtered": True,
        },
    )


def _abstention_candidate(decision: RetrievalGroundingDecision) -> ContextCandidate:
    content = (
        "Local retrieval grounding policy: sufficient indexed evidence is not "
        "available for this task. Do not invent retrieval-backed facts or citations. "
        "Explicitly abstain or state that the indexed evidence is unavailable. "
        f"Reason={decision.reason}."
    )
    digest = hashlib.sha256(
        json.dumps(
            decision.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return ContextCandidate(
        candidate_id=f"retrieval-abstention:{digest}",
        source="retrieval_grounding_policy",
        source_ref=decision.reason,
        layer="L1",
        kind="constraint",
        scope=("shared",),
        priority=900,
        trust="trusted_local",
        freshness=0,
        estimated_tokens=max(1, (len(content) + 3) // 4),
        content=content,
        bucket="task",
        pinned=True,
        compressible=False,
        metadata={"answerable": False, "reason": decision.reason},
    )


__all__ = [
    "CitationAnchor",
    "RetrievalContextSource",
    "RetrievalGroundingDecision",
    "RetrievalGroundingPolicy",
    "extract_retrieval_query",
    "register_retrieval_context_source",
]
