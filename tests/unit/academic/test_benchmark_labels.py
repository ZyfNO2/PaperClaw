from pathlib import Path

from paperclaw.academic.benchmark_labels import validate_blinded_question_file


def test_32_question_template_is_valid_and_human_blocked() -> None:
    result = validate_blinded_question_file(
        Path("benchmarks/academic_rag/v1/eval/questions.template.jsonl")
    )
    assert result.question_count == 32
    assert result.status == "blocked_by_human_labeling"
    assert len(result.missing_gold_question_ids) == 32
    assert len(result.source_digest) == 64
