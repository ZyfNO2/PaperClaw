"""Validation for the blinded Academic RAG P0 evaluation boundary.

The question loader deliberately has no gold-label parameter.  This is a small
but important boundary: a runner can consume the blinded questions without
being able to accidentally load the private human labels into a prompt or
trace.  Gold validation is a separate, post-run operation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any, Literal

from .contracts import EvidenceLocator


P0_QUESTION_SCHEMA = "academic-rag-p0-blinded-question.v1"
P0_AI_DRAFT_SCHEMA = "academic-retrieval-question-authoring.v1"
P0_GOLD_SCHEMA = "academic-rag-p0-gold-label.v1"
P0_QUESTION_TYPES = ("text", "figure", "table", "equation")
_REQUIRED_GOLD_FIELDS = {
    "question_id",
    "accepted_answers",
    "supporting_paper_ids",
    "evidence_locators",
    "allowable_inference",
    "forbidden_overclaim",
    "should_abstain",
    "severe_error_conditions",
    "annotator_id",
    "reviewer_id",
    "annotated_at",
    "disagreement_resolution",
}


@dataclass(frozen=True)
class BenchmarkLabelValidation:
    status: Literal["blocked_by_human_labeling", "ready"]
    question_count: int
    source_digest: str
    missing_gold_question_ids: tuple[str, ...]


@dataclass(frozen=True)
class GoldLabelValidation:
    status: Literal["blocked_by_human_labeling", "ready"]
    question_count: int
    gold_count: int
    source_digest: str | None
    missing_question_ids: tuple[str, ...]
    invalid_question_ids: tuple[str, ...]
    stale_locator_question_ids: tuple[str, ...]


def _jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row {line_number} must be an object")
        rows.append(value)
    return tuple(rows)


def load_blinded_questions(path: Path) -> tuple[dict[str, Any], ...]:
    """Load only safe question fields for a blind runner.

    The file must not contain a gold answer, locator, label, or expected
    decision.  Placeholder question text is accepted so the authoring pack can
    be committed without fabricating scientific questions; the validator will
    then report ``blocked_by_human_labeling``.
    """

    rows = _jsonl(path)
    if len(rows) != 32:
        raise ValueError("P0 blinded benchmark must contain exactly 32 questions")
    ids = [str(row.get("question_id", "")) for row in rows]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("P0 question IDs must be non-empty and unique")
    allowed = {
        "schema_version",
        "question_id",
        "question_type",
        "question",
        "corpus_id",
        "blind",
        "authoring_status",
    }
    for row in rows:
        if row.get("schema_version") != P0_QUESTION_SCHEMA:
            raise ValueError("unsupported P0 blinded question schema")
        if row.get("blind") is not True:
            raise ValueError(f"question {row['question_id']} is not marked blind")
        if row.get("question_type") not in P0_QUESTION_TYPES:
            raise ValueError(f"invalid question type for {row['question_id']}")
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError(f"question {row['question_id']} has no text")
        forbidden = sorted(set(row) - allowed)
        if forbidden:
            raise ValueError(
                f"question {row['question_id']} contains non-blind fields: {forbidden}"
            )
    counts = {kind: sum(row["question_type"] == kind for row in rows) for kind in P0_QUESTION_TYPES}
    if counts != {"text": 8, "figure": 8, "table": 8, "equation": 8}:
        raise ValueError(f"invalid P0 question distribution: {counts}")
    return rows


def run_blinded_questions(
    path: Path,
    answer: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Run a caller-supplied answerer without exposing gold labels.

    Returned rows intentionally contain only the question ID and answerer
    output.  The function has no gold-path argument and therefore cannot put a
    gold path or gold content into the run trace by construction.
    """

    rows = load_blinded_questions(path)
    output: list[dict[str, Any]] = []
    for question in rows:
        result = _redact_gold(answer(question))
        output.append({"question_id": question["question_id"], "answer": result})
    return tuple(output)


def _redact_gold(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _redact_gold(item)
            for key, item in value.items()
            if "gold" not in str(key).lower()
        }
    if isinstance(value, list):
        return [_redact_gold(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_gold(item) for item in value)
    if isinstance(value, str) and "must-not-leak" in value:
        return "[REDACTED]"
    return value


def _locator_key(locator: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(locator.get("paper_id", "")),
        str(locator.get("version_id", "")),
        str(locator.get("object_id", "")),
    )


def validate_gold_label_file(
    questions_path: Path,
    gold_path: Path,
    *,
    active_locator_keys: set[tuple[str, str, str]] | None = None,
) -> GoldLabelValidation:
    """Validate human gold after a blind run, failing closed on stale locators."""

    questions = load_blinded_questions(questions_path)
    question_ids = {str(row["question_id"]) for row in questions}
    if not gold_path.is_file():
        return GoldLabelValidation(
            status="blocked_by_human_labeling",
            question_count=len(questions),
            gold_count=0,
            source_digest=None,
            missing_question_ids=tuple(sorted(question_ids)),
            invalid_question_ids=(),
            stale_locator_question_ids=(),
        )
    raw = gold_path.read_bytes()
    rows = _jsonl(gold_path)
    seen: set[str] = set()
    invalid: set[str] = set()
    stale: set[str] = set()
    for row in rows:
        question_id = str(row.get("question_id", ""))
        if not question_id or question_id in seen or question_id not in question_ids:
            invalid.add(question_id or "<missing>")
            continue
        seen.add(question_id)
        if row.get("schema_version") != P0_GOLD_SCHEMA:
            invalid.add(question_id)
            continue
        if _REQUIRED_GOLD_FIELDS - set(row):
            invalid.add(question_id)
            continue
        if not isinstance(row["accepted_answers"], list) or not row["accepted_answers"]:
            invalid.add(question_id)
        locators = row["evidence_locators"]
        if not isinstance(locators, list):
            invalid.add(question_id)
            continue
        if row["should_abstain"] and locators:
            invalid.add(question_id)
        for raw_locator in locators:
            if not isinstance(raw_locator, dict):
                invalid.add(question_id)
                continue
            try:
                EvidenceLocator.from_dict(raw_locator)
            except (KeyError, TypeError, ValueError):
                invalid.add(question_id)
                continue
            if active_locator_keys is not None and _locator_key(raw_locator) not in active_locator_keys:
                stale.add(question_id)
    missing = question_ids - seen
    status: Literal["blocked_by_human_labeling", "ready"] = (
        "ready" if not missing and not invalid and not stale else "blocked_by_human_labeling"
    )
    return GoldLabelValidation(
        status=status,
        question_count=len(questions),
        gold_count=len(rows),
        source_digest=hashlib.sha256(raw).hexdigest(),
        missing_question_ids=tuple(sorted(missing)),
        invalid_question_ids=tuple(sorted(invalid)),
        stale_locator_question_ids=tuple(sorted(stale)),
    )


def validate_blinded_question_file(path: Path) -> BenchmarkLabelValidation:
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) != 32:
        raise ValueError("blinded benchmark must contain exactly 32 questions")
    ids = [str(row.get("question_id", "")) for row in rows]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("question IDs must be non-empty and unique")
    expected_types = {
        "text": 8,
        "figure": 8,
        "table": 8,
        "equation": 8,
    }
    actual_types = {
        name: sum(row.get("question_type") == name for row in rows)
        for name in expected_types
    }
    if actual_types != expected_types:
        raise ValueError(f"question type distribution is invalid: {actual_types}")
    missing = tuple(
        row["question_id"]
        for row in rows
        if row.get("label_status") != "human_verified"
        or not row.get("gold_locator")
    )
    return BenchmarkLabelValidation(
        status="blocked_by_human_labeling" if missing else "ready",
        question_count=len(rows),
        source_digest=hashlib.sha256(raw).hexdigest(),
        missing_gold_question_ids=missing,
    )


def validate_ai_question_draft_file(path: Path) -> BenchmarkLabelValidation:
    """Validate the AI-assisted authoring draft without promoting it to gold.

    The draft is intentionally a different contract from ``questions.blinded``.
    It may contain proposed paper IDs and question text, but every row must
    remain explicitly pending human review and all gold-bearing fields must be
    empty.  A caller must never pass this file to the blinded runner or the
    human-gold validator as a substitute for reviewed labels.
    """

    raw = path.read_bytes()
    rows = _jsonl(path)
    if len(rows) != 32:
        raise ValueError("AI-assisted P0 draft must contain exactly 32 questions")
    expected_ids = tuple(f"Q{index:02d}" for index in range(1, 33))
    ids = tuple(str(row.get("question_id", "")) for row in rows)
    if ids != expected_ids or len(set(ids)) != len(ids):
        raise ValueError("AI-assisted P0 draft IDs must be Q01-Q32 in order")
    expected_types = (
        ("text", 8),
        ("figure", 8),
        ("table", 8),
        ("equation", 8),
    )
    actual_types = {
        question_type: sum(row.get("question_type") == question_type for row in rows)
        for question_type, _ in expected_types
    }
    if actual_types != dict(expected_types):
        raise ValueError(f"AI-assisted P0 draft distribution is invalid: {actual_types}")
    required = {
        "schema_version",
        "question_id",
        "question_type",
        "text",
        "corpus_id",
        "paper_id",
        "gold_locator",
        "object_type",
        "bbox_target",
        "table_cell_target",
        "abstention_target",
        "split",
        "fingerprint",
        "label_status",
    }
    for row in rows:
        question_id = str(row["question_id"])
        if set(row) != required:
            raise ValueError(f"AI-assisted draft {question_id} has an unexpected schema")
        if row["schema_version"] != P0_AI_DRAFT_SCHEMA:
            raise ValueError(f"AI-assisted draft {question_id} has an unsupported schema")
        if not isinstance(row["text"], str) or not row["text"].strip():
            raise ValueError(f"AI-assisted draft {question_id} has empty text")
        if row["corpus_id"] != "academic-rag-h0-v1":
            raise ValueError(f"AI-assisted draft {question_id} has an unknown corpus")
        if row["paper_id"] not in {f"P{index:02d}" for index in range(1, 13)}:
            raise ValueError(f"AI-assisted draft {question_id} has an invalid paper ID")
        if row["split"] != "blinded":
            raise ValueError(f"AI-assisted draft {question_id} is not blinded")
        if row["fingerprint"] != "HUMAN_REVIEW_REQUIRED":
            raise ValueError(f"AI-assisted draft {question_id} has a review fingerprint")
        if row["label_status"] != "pending_human_labeling":
            raise ValueError(f"AI-assisted draft {question_id} is not human-pending")
        for field in (
            "gold_locator",
            "bbox_target",
            "table_cell_target",
            "abstention_target",
        ):
            if row[field] is not None:
                raise ValueError(f"AI-assisted draft {question_id} contains {field}")
    return BenchmarkLabelValidation(
        status="blocked_by_human_labeling",
        question_count=len(rows),
        source_digest=hashlib.sha256(raw).hexdigest(),
        missing_gold_question_ids=expected_ids,
    )
