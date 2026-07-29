"""Frozen real-paper retrieval benchmark contracts and metrics."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from .contracts import RetrievalCandidate


@dataclass(frozen=True)
class BenchmarkQuery:
    """One human-labelled query over blind paper identities."""

    query_id: str
    text: str
    relevant_paper_ids: frozenset[str]
    relevant_pages: frozenset[tuple[str, int]]
    relevant_object_ids: frozenset[str]
    object_relevance: Mapping[str, int]
    expected_object_type: str | None = None
    expected_table_cell: tuple[int, int] | None = None
    expected_bbox: tuple[float, float, float, float] | None = None
    should_abstain: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BenchmarkQuery":
        schema = value.get("schema_version")
        if schema != "academic-retrieval-query.v1":
            raise ValueError(f"unsupported benchmark query schema: {schema!r}")
        query_id = str(value.get("query_id", "")).strip()
        text = str(value.get("text", "")).strip()
        if not query_id or not text:
            raise ValueError("benchmark query_id and text are required")
        relevance = {
            str(object_id): int(grade)
            for object_id, grade in dict(value.get("object_relevance", {})).items()
        }
        if any(grade < 0 or grade > 3 for grade in relevance.values()):
            raise ValueError("object relevance grades must be in [0, 3]")
        pages = frozenset(
            (str(item["paper_id"]), int(item["page_number"]))
            for item in value.get("relevant_pages", [])
        )
        table_cell = value.get("expected_table_cell")
        bbox = value.get("expected_bbox")
        return cls(
            query_id=query_id,
            text=text,
            relevant_paper_ids=frozenset(
                str(item) for item in value.get("relevant_paper_ids", [])
            ),
            relevant_pages=pages,
            relevant_object_ids=frozenset(
                str(item) for item in value.get("relevant_object_ids", [])
            ),
            object_relevance=relevance,
            expected_object_type=(
                str(value["expected_object_type"])
                if value.get("expected_object_type")
                else None
            ),
            expected_table_cell=(
                (int(table_cell["row"]), int(table_cell["column"]))
                if table_cell
                else None
            ),
            expected_bbox=(
                tuple(float(item) for item in bbox)  # type: ignore[arg-type]
                if bbox
                else None
            ),
            should_abstain=bool(value.get("should_abstain", False)),
        )


def _recall(retrieved: Iterable[Any], relevant: frozenset[Any]) -> float | None:
    if not relevant:
        return None
    return len(set(retrieved) & relevant) / len(relevant)


def _reciprocal_rank(ranked_ids: list[str], relevant: frozenset[str]) -> float | None:
    if not relevant:
        return None
    for rank, object_id in enumerate(ranked_ids, start=1):
        if object_id in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg(ranked_ids: list[str], relevance: Mapping[str, int]) -> float | None:
    if not relevance:
        return None

    def dcg(grades: Iterable[int]) -> float:
        return sum(
            (2**grade - 1) / math.log2(rank + 1)
            for rank, grade in enumerate(grades, start=1)
        )

    actual = dcg(relevance.get(object_id, 0) for object_id in ranked_ids)
    ideal = dcg(sorted(relevance.values(), reverse=True)[: len(ranked_ids)])
    return 0.0 if ideal == 0 else actual / ideal


def bbox_iou(
    actual: tuple[float, float, float, float] | None,
    expected: tuple[float, float, float, float] | None,
) -> float | None:
    if actual is None or expected is None:
        return None
    ax0, ay0, ax1, ay1 = actual
    ex0, ey0, ex1, ey1 = expected
    intersection = max(0.0, min(ax1, ex1) - max(ax0, ex0)) * max(
        0.0, min(ay1, ey1) - max(ay0, ey0)
    )
    union = (ax1 - ax0) * (ay1 - ay0) + (ex1 - ex0) * (ey1 - ey0) - intersection
    return 0.0 if union <= 0 else intersection / union


def evaluate_query(
    query: BenchmarkQuery,
    candidates: tuple[RetrievalCandidate, ...],
    *,
    top_k: int,
) -> dict[str, Any]:
    """Score one ranked result without inventing labels for missing dimensions."""

    ranked = list(candidates[:top_k])
    object_ids = [item.locator.object_id for item in ranked]
    paper_ids = [item.locator.paper_id for item in ranked]
    pages = [(item.locator.paper_id, item.locator.page_number) for item in ranked]
    top = ranked[0].locator if ranked else None
    actual_bbox = None
    if top and top.bounding_box:
        box = top.bounding_box
        actual_bbox = (box.x0, box.y0, box.x1, box.y1)
    abstained = not ranked
    return {
        "query_id": query.query_id,
        "document_recall_at_k": _recall(paper_ids, query.relevant_paper_ids),
        "page_recall_at_k": _recall(pages, query.relevant_pages),
        "object_recall_at_k": _recall(object_ids, query.relevant_object_ids),
        "reciprocal_rank": _reciprocal_rank(object_ids, query.relevant_object_ids),
        "ndcg_at_k": _ndcg(object_ids, query.object_relevance),
        "locator_page_accuracy": (
            None
            if not query.relevant_pages
            else bool(top and (top.paper_id, top.page_number) in query.relevant_pages)
        ),
        "object_type_accuracy": (
            None
            if query.expected_object_type is None
            else bool(top and top.object_type == query.expected_object_type)
        ),
        "table_cell_exact": (
            None
            if query.expected_table_cell is None
            else bool(
                top and (top.table_row, top.table_column) == query.expected_table_cell
            )
        ),
        "bbox_iou": bbox_iou(actual_bbox, query.expected_bbox),
        "abstention_correct": abstained == query.should_abstain,
        "candidate_count": len(ranked),
    }


def aggregate_results(
    results: Iterable[Mapping[str, Any]],
) -> dict[str, float | int | None]:
    rows = list(results)
    metric_names = (
        "document_recall_at_k",
        "page_recall_at_k",
        "object_recall_at_k",
        "reciprocal_rank",
        "ndcg_at_k",
        "locator_page_accuracy",
        "object_type_accuracy",
        "table_cell_exact",
        "bbox_iou",
        "abstention_correct",
    )
    output: dict[str, float | int | None] = {"query_count": len(rows)}
    for name in metric_names:
        values = [float(row[name]) for row in rows if row.get(name) is not None]
        output[name] = sum(values) / len(values) if values else None
        output[f"{name}_sample_count"] = len(values)
    return output
