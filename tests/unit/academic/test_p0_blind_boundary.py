from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.academic.benchmark_labels import (
    load_blinded_questions,
    run_blinded_questions,
    validate_gold_label_file,
)


PACK = Path("benchmarks/academic_rag/v1/eval")
QUESTIONS = PACK / "questions.blinded.jsonl"


def _locator(object_id: str = "object-1") -> dict[str, object]:
    return {
        "schema_version": "academic.v1",
        "paper_id": "paper-1",
        "version_id": "version-1",
        "object_id": object_id,
        "page_number": 1,
        "object_type": "paragraph",
        "source_hash": "a" * 64,
    }


def _gold(question_id: str = "Q01", object_id: str = "object-1") -> dict[str, object]:
    return {
        "schema_version": "academic-rag-p0-gold-label.v1",
        "question_id": question_id,
        "accepted_answers": ["human answer"],
        "supporting_paper_ids": ["paper-1"],
        "evidence_locators": [_locator(object_id)],
        "allowable_inference": "none",
        "forbidden_overclaim": "no causal claim",
        "should_abstain": False,
        "severe_error_conditions": ["wrong paper"],
        "annotator_id": "human-a",
        "reviewer_id": "human-b",
        "annotated_at": "2026-07-31T00:00:00Z",
        "disagreement_resolution": "none",
    }


def test_blinded_pack_has_exact_32_questions_and_no_gold_fields() -> None:
    rows = load_blinded_questions(QUESTIONS)
    assert len(rows) == 32
    assert not any("gold" in key for row in rows for key in row)


def test_duplicate_question_id_is_rejected(tmp_path: Path) -> None:
    rows = QUESTIONS.read_text(encoding="utf-8").splitlines()
    path = tmp_path / "questions.jsonl"
    path.write_text("\n".join([rows[0], *rows[1:31], rows[0]]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_blinded_questions(path)


def test_blind_runner_does_not_emit_gold_path_or_gold_content(tmp_path: Path) -> None:
    output = run_blinded_questions(
        QUESTIONS,
        lambda question: {
            "text": question["question"],
            "gold_locator": "must-not-leak",
            "nested": {"gold": "must-not-leak"},
        },
    )
    assert len(output) == 32
    assert all("gold_locator" not in row["answer"] for row in output)
    assert all("gold" not in json.dumps(row, ensure_ascii=False) for row in output)


def test_missing_gold_is_blocked(tmp_path: Path) -> None:
    result = validate_gold_label_file(QUESTIONS, tmp_path / "gold.jsonl")
    assert result.status == "blocked_by_human_labeling"
    assert len(result.missing_question_ids) == 32


def test_invalid_and_stale_locator_are_blocked(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text(json.dumps(_gold(object_id="not-active")) + "\n", encoding="utf-8")
    result = validate_gold_label_file(
        QUESTIONS,
        invalid,
        active_locator_keys={("paper-1", "version-1", "active")},
    )
    assert result.status == "blocked_by_human_labeling"
    assert result.stale_locator_question_ids == ("Q01",)

    malformed = tmp_path / "malformed.jsonl"
    row = _gold()
    row["evidence_locators"] = [{"schema_version": "academic.v1"}]
    malformed.write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = validate_gold_label_file(QUESTIONS, malformed)
    assert result.invalid_question_ids == ("Q01",)
