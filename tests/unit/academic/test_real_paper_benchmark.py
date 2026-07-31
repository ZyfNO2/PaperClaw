from __future__ import annotations

from paperclaw.academic.benchmark import (
    BenchmarkQuery,
    aggregate_results,
    bbox_iou,
    evaluate_query,
)
from paperclaw.academic.contracts import (
    BoundingBox,
    EvidenceLocator,
    RetrievalCandidate,
)


def _candidate(object_id: str, page: int, *, grade: float = 1.0) -> RetrievalCandidate:
    locator = EvidenceLocator(
        paper_id="paper-1",
        version_id="version-1",
        object_id=object_id,
        page_number=page,
        object_type="table_cell",
        source_hash="a" * 64,
        bounding_box=BoundingBox(0, 0, 10, 10),
        table_row=2,
        table_column=3,
    )
    return RetrievalCandidate(
        locator, object_id, {"lexical": grade}, grade, ("fixture",)
    )


def test_real_paper_metrics_keep_unlabelled_dimensions_unscored() -> None:
    query = BenchmarkQuery.from_dict(
        {
            "schema_version": "academic-retrieval-query.v1",
            "query_id": "Q01",
            "text": "Which result is reported?",
            "relevant_paper_ids": ["paper-1"],
            "relevant_pages": [{"paper_id": "paper-1", "page_number": 4}],
            "relevant_object_ids": ["object-b"],
            "object_relevance": {"object-b": 3, "object-a": 1},
            "expected_object_type": "table_cell",
            "expected_table_cell": {"row": 2, "column": 3},
            "expected_bbox": [0, 0, 10, 10],
        }
    )
    result = evaluate_query(
        query,
        (_candidate("object-a", 3), _candidate("object-b", 4)),
        top_k=5,
    )

    assert result["document_recall_at_k"] == 1
    assert result["page_recall_at_k"] == 1
    assert result["object_recall_at_k"] == 1
    assert result["reciprocal_rank"] == 0.5
    assert 0 < result["ndcg_at_k"] < 1
    assert result["locator_page_accuracy"] is False
    assert result["table_cell_exact"] is True
    assert result["bbox_iou"] == 1

    aggregate = aggregate_results([result])
    assert aggregate["query_count"] == 1
    assert aggregate["object_recall_at_k_sample_count"] == 1


def test_abstention_and_bbox_edge_cases_are_explicit() -> None:
    query = BenchmarkQuery.from_dict(
        {
            "schema_version": "academic-retrieval-query.v1",
            "query_id": "Q-negative",
            "text": "A deliberately unsupported claim",
            "should_abstain": True,
        }
    )
    result = evaluate_query(query, (), top_k=5)
    assert result["abstention_correct"] is True
    assert result["document_recall_at_k"] is None
    assert bbox_iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0
