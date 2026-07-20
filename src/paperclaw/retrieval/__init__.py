"""PaperClaw local retrieval, grounding and hybrid ranking foundation."""

from paperclaw.retrieval.chunking import build_chunks
from paperclaw.retrieval.context_source import (
    CitationAnchor,
    RetrievalContextSource,
    RetrievalGroundingDecision,
    RetrievalGroundingPolicy,
    extract_retrieval_query,
    register_retrieval_context_source,
)
from paperclaw.retrieval.contracts import (
    BlockLocator,
    Chunk,
    ChunkConfig,
    ChunkLocator,
    DocumentIdentity,
    DocumentVersion,
    IndexManifest,
    ParsedBlock,
    RegistryMutationResult,
    SourceArtifact,
    canonical_json,
    compute_corpus_hash,
    sha256_bytes,
    sha256_text,
    stable_id,
)
from paperclaw.retrieval.evaluation import (
    RankedIdMetrics,
    RetrievalEvalCase,
    RetrievalJudgment,
    RetrievalMetrics,
    evaluate_judgment,
    evaluate_ranked_ids,
    evaluate_suite,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from paperclaw.retrieval.grounding import (
    GroundingClaimJudgment,
    GroundingMetrics,
    cited_anchor_ids,
    evaluate_grounding,
)
from paperclaw.retrieval.hybrid import (
    HybridCandidateMismatchError,
    HybridCorpusMismatchError,
    HybridRetrievalResult,
    HybridRetriever,
    RetrievalBackendAdapter,
    Retriever,
    WeightedRRFConfig,
    hybrid_configuration_fingerprint,
)
from paperclaw.retrieval.incremental import IncrementalIndexer, IncrementalIndexResult
from paperclaw.retrieval.integrity import (
    IndexIntegrityReport,
    IndexRebuildResult,
    SQLiteIndexMaintainer,
)
from paperclaw.retrieval.parsers import MarkdownParser, ParserOutput, PlainTextParser, select_parser
from paperclaw.retrieval.quality_eval import (
    QualityComparison,
    ResearchAnswerObservation,
    ResearchCaseMetrics,
    ResearchQualityCase,
    ResearchQualityReport,
    compare_quality_reports,
    evaluate_research_case,
    evaluate_research_quality,
    load_quality_cases,
    load_quality_observations,
)
from paperclaw.retrieval.query import (
    BrokenIndexError,
    RankedResult,
    RetrievalCandidate,
    RetrievalError,
    RetrievalRequest,
    SQLiteBM25Retriever,
    StaleIndexError,
    retrieved_ids,
)
from paperclaw.retrieval.registry import SQLiteDocumentRegistry
from paperclaw.retrieval.rerank import (
    CandidateReranker,
    EvidenceAwareReranker,
    EvidenceRerankConfig,
    RerankedHybridResult,
    RerankedHybridRetriever,
)
from paperclaw.retrieval.semantic import (
    HashingEmbeddingConfig,
    HashingSemanticEncoder,
    SQLiteHashingVectorRetriever,
    SemanticDocument,
)

__all__ = [
    "BlockLocator", "BrokenIndexError", "CandidateReranker", "Chunk", "ChunkConfig",
    "ChunkLocator", "CitationAnchor", "DocumentIdentity", "DocumentVersion",
    "EvidenceAwareReranker", "EvidenceRerankConfig", "GroundingClaimJudgment",
    "GroundingMetrics", "HashingEmbeddingConfig", "HashingSemanticEncoder",
    "HybridCandidateMismatchError", "HybridCorpusMismatchError", "HybridRetrievalResult",
    "HybridRetriever", "IncrementalIndexer", "IncrementalIndexResult", "IndexIntegrityReport",
    "IndexManifest", "IndexRebuildResult", "MarkdownParser", "ParsedBlock", "ParserOutput",
    "PlainTextParser", "QualityComparison", "RankedIdMetrics", "RankedResult",
    "RegistryMutationResult", "RerankedHybridResult", "RerankedHybridRetriever",
    "ResearchAnswerObservation", "ResearchCaseMetrics", "ResearchQualityCase",
    "ResearchQualityReport", "RetrievalBackendAdapter", "RetrievalCandidate",
    "RetrievalContextSource", "RetrievalError", "RetrievalEvalCase",
    "RetrievalGroundingDecision", "RetrievalGroundingPolicy", "RetrievalJudgment",
    "RetrievalMetrics", "RetrievalRequest", "Retriever", "SQLiteBM25Retriever",
    "SQLiteDocumentRegistry", "SQLiteHashingVectorRetriever", "SQLiteIndexMaintainer",
    "SemanticDocument", "SourceArtifact", "StaleIndexError", "WeightedRRFConfig",
    "build_chunks", "canonical_json", "cited_anchor_ids", "compare_quality_reports",
    "compute_corpus_hash", "evaluate_grounding", "evaluate_judgment",
    "evaluate_ranked_ids", "evaluate_research_case", "evaluate_research_quality",
    "evaluate_suite", "extract_retrieval_query", "hybrid_configuration_fingerprint",
    "load_quality_cases", "load_quality_observations", "ndcg_at_k", "recall_at_k",
    "reciprocal_rank", "register_retrieval_context_source", "retrieved_ids", "select_parser",
    "sha256_bytes", "sha256_text", "stable_id",
]
