"""CLI for deterministic research retrieval and answer-quality evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from paperclaw.retrieval.quality_eval import (
    compare_quality_reports,
    evaluate_research_quality,
    load_quality_cases,
    load_quality_observations,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-retrieval-quality")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = load_quality_cases(args.benchmark)
    candidate = evaluate_research_quality(
        cases,
        load_quality_observations(args.predictions),
    )
    payload = candidate.to_dict()
    if args.baseline is not None:
        baseline = evaluate_research_quality(
            cases,
            load_quality_observations(args.baseline),
        )
        payload = compare_quality_reports(baseline, candidate).to_dict()
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if args.format == "json"
        else _render_text(payload)
    ) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


def _render_text(payload: dict) -> str:
    report = payload.get("candidate", payload)
    lines = [
        f"Cases: {report['case_count']}",
        (
            "Retrieval: "
            f"R@5={report['mean_recall_at_5']:.3f} "
            f"R@10={report['mean_recall_at_10']:.3f} "
            f"MRR={report['mean_mrr']:.3f} "
            f"nDCG@10={report['mean_ndcg_at_10']:.3f}"
        ),
        (
            "Evidence: "
            f"citation_precision={report['citation_precision']:.3f} "
            f"citation_recall={report['citation_recall']:.3f} "
            f"grounded={report['grounded_claim_rate']:.3f} "
            f"claim_coverage={report['claim_coverage']:.3f}"
        ),
        (
            "Answer: "
            f"term_coverage={report['answer_term_coverage']:.3f} "
            f"abstention_accuracy={report['abstention_accuracy']:.3f}"
        ),
        (
            "Efficiency: "
            f"mean_latency_ms={report['mean_latency_ms']:.1f} "
            f"tokens={report['total_tokens']} "
            f"cost_usd={report['total_estimated_cost_usd']:.6f} "
            f"unpriced_cases={report['unpriced_case_count']}"
        ),
    ]
    if "deltas" in payload:
        lines.append("Deltas: " + json.dumps(payload["deltas"], sort_keys=True))
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
