"""Generate explicitly non-gold P0 review drafts from local evidence.

This command is deliberately local-only.  It combines the committed AI
question draft with the real frozen-paper locator inventory, but it never
fills accepted answers, human identities, gold locators, or scientific
cross-paper decisions.  The generated files are ignored by Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from paperclaw.academic.benchmark_labels import validate_ai_question_draft_file


QUESTION_TYPES = {
    "text": {"paragraph", "section", "algorithm"},
    "figure": {"figure", "caption"},
    "table": {"table", "table_cell"},
    "equation": {"equation"},
}


def _jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_view(candidate: dict[str, Any], rank: int) -> dict[str, Any]:
    """Keep enough information for a human to inspect a candidate locally."""

    return {
        "rank": rank,
        "blind_id": candidate["blind_id"],
        "paper_id": candidate["paper_id"],
        "version_id": candidate["version_id"],
        "source_hash": candidate["source_hash"],
        "object_id": candidate["object_id"],
        "object_type": candidate["object_type"],
        "reading_order": candidate["reading_order"],
        "page_number": candidate["page_number"],
        "section_path": candidate["section_path"],
        "table_row": candidate["table_row"],
        "table_column": candidate["table_column"],
        "bbox": candidate["bbox"],
        "text_preview": candidate["text_preview"],
        "text_sha256": candidate["text_sha256"],
    }


def _build_label_draft(
    questions_path: Path,
    inventory_path: Path,
) -> tuple[dict[str, Any], ...]:
    validation = validate_ai_question_draft_file(questions_path)
    questions = _jsonl(questions_path)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    papers = {paper["blind_id"]: paper for paper in inventory["papers"]}
    rows: list[dict[str, Any]] = []
    for question in questions:
        paper = papers.get(question["paper_id"])
        if paper is None:
            raise ValueError(f"inventory is missing {question['paper_id']}")
        candidates = paper["label_candidates"]
        preferred = [
            item
            for item in candidates
            if item["object_type"] in QUESTION_TYPES[question["question_type"]]
        ]
        selected = preferred[:5] or candidates[:5]
        rows.append(
            {
                "schema_version": "academic-rag-p0-ai-gold-draft.v1",
                "question_id": question["question_id"],
                "question_type": question["question_type"],
                "question_text": question["text"],
                "paper_id": question["paper_id"],
                "draft_status": "AI_DRAFT_NOT_HUMAN_ANNOTATION",
                "review_status": "PENDING_INDEPENDENT_REVIEW",
                "gold_eligibility": "INELIGIBLE_UNTIL_HUMAN_LABEL_AND_REVIEW",
                "candidate_locators": [
                    _candidate_view(candidate, index)
                    for index, candidate in enumerate(selected, start=1)
                ],
                "accepted_answers": [],
                "evidence_locators": [],
                "annotator_id": None,
                "reviewer_id": None,
                "disagreement_resolution": None,
                "notes": "Candidates are parser-derived suggestions only; no locator is gold.",
            }
        )
    if len(rows) != validation.question_count:
        raise ValueError("question and draft counts diverged")
    return tuple(rows)


def _build_cross_paper_draft(frozen_path: Path) -> tuple[dict[str, Any], ...]:
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    paper_hashes = {
        paper["blind_id"]: paper["file_sha256"] for paper in frozen["papers"]
    }
    scenarios = (
        (
            "CP01",
            ("P04", "P05"),
            "Can the evidence distinguish a real-time stereo foundation model from a tunnel-face stereo reconstruction workflow without conflating their claims?",
        ),
        (
            "CP02",
            ("P07", "P09"),
            "What evidence boundary is needed before comparing SAM2-based crack segmentation with semi-supervised crack segmentation under different training assumptions?",
        ),
    )
    return tuple(
        {
            "schema_version": "academic-rag-p0-cross-paper-ai-draft.v1",
            "scenario_id": scenario_id,
            "paper_ids": list(paper_ids),
            "paper_sha256": {paper_id: paper_hashes[paper_id] for paper_id in paper_ids},
            "scenario_text": scenario_text,
            "evidence_status": "VERIFIED_FROZEN_MANIFEST_IDENTITY_ONLY",
            "scenario_status": "PROPOSED_FOR_HUMAN_REVIEW",
            "automated_interpretation_status": "UNKNOWN",
            "human_decision_status": "PENDING_INDEPENDENT_HUMAN_DECISION",
            "decision": None,
            "reviewer_id": None,
            "reviewed_at": None,
            "notes": "No cross-paper scientific conclusion is generated by this draft.",
        }
        for scenario_id, paper_ids, scenario_text in scenarios
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--frozen-set", type=Path, required=True)
    parser.add_argument("--gold-output", type=Path, required=True)
    parser.add_argument("--cross-paper-output", type=Path, required=True)
    args = parser.parse_args(argv)

    labels = _build_label_draft(args.questions, args.inventory)
    cross_paper = _build_cross_paper_draft(args.frozen_set)
    for path, rows in (
        (args.gold_output, labels),
        (args.cross_paper_output, cross_paper),
    ):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite local draft: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "gold_draft_rows": len(labels),
                "cross_paper_rows": len(cross_paper),
                "gold_output": str(args.gold_output),
                "cross_paper_output": str(args.cross_paper_output),
                "status": "LOCAL_ONLY_DRAFTS; NOT_P0_GOLD",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
