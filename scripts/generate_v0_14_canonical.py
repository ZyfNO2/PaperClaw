"""Generate deterministic recorded v0.14 research-evaluation artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from paperclaw.research_eval import (
    EvaluationRunner,
    JsonReportRenderer,
    MarkdownReportRenderer,
    RecordedVariant,
    load_dataset,
    load_recorded_results,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="artifacts/v0_14",
        help="Directory for canonical_results.json and canonical_report.md",
    )
    return parser


def generate(output_dir: str | Path) -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[1]
    fixture_dir = root / "tests" / "fixtures" / "research_eval"
    cases, dataset_digest = load_dataset(
        fixture_dir / "canonical_dataset.jsonl"
    )
    baseline = load_recorded_results(
        fixture_dir / "canonical_results_baseline_no_retrieval.jsonl",
        variant_id="baseline_no_retrieval",
    )
    strong = load_recorded_results(
        fixture_dir / "canonical_results_bm25_mcp_verify.jsonl",
        variant_id="bm25_mcp_verify",
    )
    report = EvaluationRunner(
        [
            RecordedVariant("baseline_no_retrieval", baseline),
            RecordedVariant("bm25_mcp_verify", strong),
        ]
    ).run(
        cases,
        dataset_digest=dataset_digest,
        metadata={
            "generator": "scripts/generate_v0_14_canonical.py",
            "mode": "recorded-canonical",
        },
    )
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "canonical_results.json"
    markdown_path = target / "canonical_report.md"
    write_report(report, json_path, renderer=JsonReportRenderer())
    write_report(report, markdown_path, renderer=MarkdownReportRenderer())
    return json_path, markdown_path


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    json_path, markdown_path = generate(args.output_dir)
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
