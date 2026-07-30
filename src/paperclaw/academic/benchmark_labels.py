"""Validation for blinded benchmark authoring without fabricated human gold."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BenchmarkLabelValidation:
    status: Literal["blocked_by_human_labeling", "ready"]
    question_count: int
    source_digest: str
    missing_gold_question_ids: tuple[str, ...]


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
