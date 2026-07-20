from __future__ import annotations

import json
from pathlib import Path

from paperclaw.retrieval import (
    ChunkLocator,
    EvidenceAwareReranker,
    HybridRetriever,
    ResearchAnswerObservation,
    ResearchQualityCase,
    RetrievalBackendAdapter,
    RetrievalCandidate,
    RetrievalRequest,
    RerankedHybridRetriever,
    SQLiteHashingVectorRetriever,
    SemanticDocument,
    WeightedRRFConfig,
    compare_quality_reports,
    evaluate_research_quality,
)
from paperclaw.retrieval.contracts import sha256_text
from paperclaw.retrieval.quality_cli import main as quality_main
from paperclaw.retrieval.query import RankedResult


def candidate(chunk_id: str, document_id: str, text: str, rank: int) -> RetrievalCandidate:
    digest = sha256_text(text)
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id=document_id,
        version_id=f"version-{document_id}",
        display_name=f"{document_id}.md",
        canonical_uri=f"file:///{document_id}.md",
        text=text,
        content_hash=digest,
        source_hash=digest,
        chunk_config_hash="c" * 64,
        locator=ChunkLocator(kind="line", value="1", end_value="4"),
        bm25_score=1.0 / rank,
        rank=rank,
    )


def document(item: RetrievalCandidate) -> SemanticDocument:
    return SemanticDocument.from_candidate(item)


def request(query: str, *, top_k: int = 3) -> RetrievalRequest:
    return RetrievalRequest(
        query=query,
        top_k=top_k,
        candidate_pool_size=20,
        deduplicate=False,
    )


def test_semantic_index_is_persistent_and_version_bound(tmp_path: Path) -> None:
    relevant = candidate(
        "chunk-neural",
        "doc-neural",
        "Dense neural retrieval embeds passages and queries into vectors.",
        1,
    )
    distractor = candidate(
        "chunk-sql",
        "doc-sql",
        "SQLite transactions provide atomic local persistence.",
        2,
    )
    database = tmp_path / "semantic.sqlite3"
    retriever = SQLiteHashingVectorRetriever(database)
    corpus_hash = retriever.replace_documents([document(relevant), document(distractor)])

    result = retriever.query(request("neural passage vector retrieval", top_k=2))
    assert result.corpus_hash == corpus_hash
    assert result.candidates[0].chunk_id == "chunk-neural"
    assert result.candidates[0].locator == relevant.locator
    assert result.candidates[0].content_hash == relevant.content_hash

    reopened = SQLiteHashingVectorRetriever(database)
    assert reopened.manifest()["corpus_hash"] == corpus_hash
    assert reopened.query(request("neural vector")).candidates[0].chunk_id == "chunk-neural"


def test_hybrid_rrf_and_reranker_preserve_citation_identity(tmp_path: Path) -> None:
    lexical_relevant = candidate(
        "chunk-bm25",
        "doc-bm25",
        "BM25 exact term matching is effective for lexical retrieval.",
        1,
    )
    semantic_relevant = candidate(
        "chunk-vector",
        "doc-vector",
        "Neural vector passage retrieval improves semantic recall.",
        2,
    )
    distractor = candidate(
        "chunk-other",
        "doc-other",
        "A database transaction uses write ahead logging.",
        3,
    )

    semantic = SQLiteHashingVectorRetriever(tmp_path / "semantic.sqlite3")
    semantic.replace_documents(
        [document(semantic_relevant), document(lexical_relevant), document(distractor)]
    )
    semantic_result = semantic.query(request("neural vector passage retrieval"))
    shared_corpus = semantic_result.corpus_hash

    def lexical_query(retrieval_request: RetrievalRequest) -> RankedResult:
        return RankedResult(
            request_id=retrieval_request.request_id,
            manifest_id="lexical",
            corpus_hash=shared_corpus,
            candidates=(lexical_relevant, distractor),
            total_matches=2,
            filtered_stale=0,
            filtered_duplicates=0,
        )

    def semantic_query(retrieval_request: RetrievalRequest) -> RankedResult:
        return RankedResult(
            request_id=retrieval_request.request_id,
            manifest_id=semantic_result.manifest_id,
            corpus_hash=shared_corpus,
            candidates=semantic_result.candidates,
            total_matches=semantic_result.total_matches,
            filtered_stale=0,
            filtered_duplicates=0,
        )

    hybrid = HybridRetriever(
        [
            RetrievalBackendAdapter("lexical", lexical_query),
            RetrievalBackendAdapter("semantic", semantic_query),
        ],
        config=WeightedRRFConfig(
            backend_weights={"lexical": 1.0, "semantic": 1.4},
            candidate_pool_size=10,
        ),
    )
    reranked = RerankedHybridRetriever(hybrid, EvidenceAwareReranker()).query(
        request("neural vector passage retrieval", top_k=3)
    )

    ids = [item.chunk_id for item in reranked.candidates]
    assert "chunk-bm25" in ids
    assert "chunk-vector" in ids
    assert reranked.candidates[0].chunk_id == "chunk-vector"
    original = {item.chunk_id: item for item in (lexical_relevant, semantic_relevant)}
    for item in reranked.candidates:
        if item.chunk_id in original:
            assert item.locator == original[item.chunk_id].locator
            assert item.content_hash == original[item.chunk_id].content_hash


def test_research_quality_report_separates_retrieval_grounding_and_cost() -> None:
    cases = (
        ResearchQualityCase(
            case_id="case-1",
            query="How does hybrid retrieval work?",
            relevant_chunk_ids=("chunk-bm25", "chunk-vector"),
            relevant_document_ids=("doc-bm25", "doc-vector"),
            required_claim_ids=("claim-fusion", "claim-vector"),
            required_answer_terms=("RRF", "vector"),
        ),
        ResearchQualityCase(
            case_id="case-2",
            query="Unsupported future claim",
            relevant_chunk_ids=(),
            should_abstain=True,
        ),
    )
    baseline = (
        ResearchAnswerObservation(
            case_id="case-1",
            ranked_chunk_ids=("chunk-bm25", "chunk-other"),
            ranked_document_ids=("doc-bm25", "doc-other"),
            cited_chunk_ids=("chunk-bm25", "chunk-other"),
            cited_document_ids=("doc-bm25",),
            claim_support={"claim-fusion": ("chunk-bm25",)},
            answer_text="BM25 retrieval only",
            latency_ms=20,
            input_tokens=20,
            output_tokens=10,
            estimated_cost_usd=0.001,
        ),
        ResearchAnswerObservation(
            case_id="case-2",
            ranked_chunk_ids=(),
            ranked_document_ids=(),
            abstained=False,
            answer_text="invented answer",
            latency_ms=10,
        ),
    )
    improved = (
        ResearchAnswerObservation(
            case_id="case-1",
            ranked_chunk_ids=("chunk-vector", "chunk-bm25"),
            ranked_document_ids=("doc-vector", "doc-bm25"),
            cited_chunk_ids=("chunk-vector", "chunk-bm25"),
            cited_document_ids=("doc-vector", "doc-bm25"),
            claim_support={
                "claim-fusion": ("chunk-bm25",),
                "claim-vector": ("chunk-vector",),
            },
            answer_text="Weighted RRF combines lexical and vector retrieval.",
            latency_ms=35,
            input_tokens=30,
            output_tokens=15,
            estimated_cost_usd=0.0015,
        ),
        ResearchAnswerObservation(
            case_id="case-2",
            ranked_chunk_ids=(),
            ranked_document_ids=(),
            abstained=True,
            answer_text="insufficient evidence",
            latency_ms=12,
            estimated_cost_usd=0.0,
        ),
    )

    baseline_report = evaluate_research_quality(cases, baseline)
    improved_report = evaluate_research_quality(cases, improved)
    comparison = compare_quality_reports(baseline_report, improved_report)

    assert improved_report.mean_recall_at_10 > baseline_report.mean_recall_at_10
    assert improved_report.citation_precision > baseline_report.citation_precision
    assert improved_report.grounded_claim_rate > baseline_report.grounded_claim_rate
    assert improved_report.abstention_accuracy == 1.0
    assert comparison.deltas["mean_recall_at_10"] > 0
    assert comparison.deltas["total_estimated_cost_usd"] > 0


def test_quality_cli_compares_predictions(tmp_path: Path, capsys) -> None:
    benchmark = tmp_path / "benchmark.json"
    baseline = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    benchmark.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "c1",
                        "query": "retrieval",
                        "relevant_chunk_ids": ["a"],
                        "should_abstain": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "observations": [
                    {
                        "case_id": "c1",
                        "ranked_chunk_ids": ["x"],
                        "ranked_document_ids": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(
            {
                "observations": [
                    {
                        "case_id": "c1",
                        "ranked_chunk_ids": ["a"],
                        "ranked_document_ids": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert quality_main(
        [
            "--benchmark",
            str(benchmark),
            "--predictions",
            str(candidate_path),
            "--baseline",
            str(baseline),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["deltas"]["mean_recall_at_10"] == 1.0
