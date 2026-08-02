from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.academic.benchmark_labels import validate_ai_question_draft_file
from scripts.generate_p0_local_evidence_drafts import main


def test_ai_question_draft_is_always_human_blocked() -> None:
    result = validate_ai_question_draft_file(
        Path("benchmarks/academic_rag/v1/eval/questions.ai_draft.jsonl")
    )
    assert result.status == "blocked_by_human_labeling"
    assert result.question_count == 32
    assert len(result.missing_gold_question_ids) == 32


@pytest.mark.parametrize(
    ("question_id", "object_type"),
    [("Q09", "paragraph"), ("Q17", "paragraph"), ("Q25", "paragraph")],
)
def test_ai_question_draft_rejects_question_object_type_mismatch(
    tmp_path: Path,
    question_id: str,
    object_type: str,
) -> None:
    rows = [
        json.loads(line)
        for line in Path("benchmarks/academic_rag/v1/eval/questions.ai_draft.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    next(row for row in rows if row["question_id"] == question_id)["object_type"] = object_type
    path = tmp_path / "questions.ai_draft.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_ai_question_draft_file(path)


def test_local_drafts_never_claim_gold_or_cross_paper_approval(
    tmp_path: Path,
) -> None:
    inventory_path = tmp_path / "inventory.json"
    candidate_fields = {
        "blind_id": "P01",
        "paper_id": "paper-runtime",
        "version_id": "version-runtime",
        "source_hash": "a" * 64,
        "object_id": "object-1",
        "object_type": "paragraph",
        "reading_order": 1,
        "page_number": 1,
        "section_path": [],
        "table_row": None,
        "table_column": None,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "text_preview": "candidate",
        "text_sha256": "b" * 64,
        "provenance": None,
    }
    inventory = {
        "papers": [
            {
                "blind_id": f"P{index:02d}",
                "label_candidates": [
                    {**candidate_fields, "blind_id": f"P{index:02d}"},
                    {
                        **candidate_fields,
                        "blind_id": f"P{index:02d}",
                        "object_type": "figure",
                    },
                    {
                        **candidate_fields,
                        "blind_id": f"P{index:02d}",
                        "object_type": "table_cell",
                        "table_row": 0,
                        "table_column": 0,
                    },
                    {
                        **candidate_fields,
                        "blind_id": f"P{index:02d}",
                        "object_type": "equation",
                    },
                ],
            }
            for index in range(1, 13)
        ]
    }
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    gold_output = tmp_path / "gold_labels.ai_draft.private.jsonl"
    cross_paper_output = tmp_path / "cross_paper_decisions.ai_draft.jsonl"
    assert (
        main(
            [
                "--questions",
                "benchmarks/academic_rag/v1/eval/questions.ai_draft.jsonl",
                "--inventory",
                str(inventory_path),
                "--frozen-set",
                "benchmarks/academic_rag/v1/frozen_12.json",
                "--gold-output",
                str(gold_output),
                "--cross-paper-output",
                str(cross_paper_output),
            ]
        )
        == 0
    )
    labels = [json.loads(line) for line in gold_output.read_text().splitlines()]
    assert len(labels) == 32
    assert {row["draft_status"] for row in labels} == {
        "AI_DRAFT_NOT_HUMAN_ANNOTATION"
    }
    assert all(row["accepted_answers"] == [] for row in labels)
    scenarios = [
        json.loads(line) for line in cross_paper_output.read_text().splitlines()
    ]
    assert len(scenarios) == 2
    assert all(
        row["human_decision_status"] == "PENDING_INDEPENDENT_HUMAN_DECISION"
        and row["decision"] is None
        for row in scenarios
    )
