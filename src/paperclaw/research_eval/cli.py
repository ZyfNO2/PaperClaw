"""CLI for scoring recorded research results and comparing reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .contracts import load_dataset, load_recorded_results
from .runner import (
    EvaluationRunner,
    JsonReportRenderer,
    MarkdownReportRenderer,
    RecordedVariant,
    compare_reports,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw research-eval")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run")
    run.add_argument("--dataset", required=True)
    run.add_argument("--results", required=True)
    run.add_argument("--variant", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--markdown")

    compare = commands.add_parser("compare")
    compare.add_argument("--input", action="append", required=True)
    compare.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        cases, dataset_digest = load_dataset(args.dataset)
        recorded = load_recorded_results(
            args.results, variant_id=args.variant
        )
        variant = RecordedVariant(args.variant, recorded)
        report = EvaluationRunner([variant]).run(
            cases,
            dataset_digest=dataset_digest,
            metadata={
                "mode": "recorded",
                "dataset": str(Path(args.dataset)),
                "results": str(Path(args.results)),
            },
        )
        write_report(report, args.output, renderer=JsonReportRenderer())
        if args.markdown:
            write_report(
                report,
                args.markdown,
                renderer=MarkdownReportRenderer(),
            )
        return 0

    reports = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in args.input
    ]
    comparison = compare_reports(reports)
    Path(args.output).write_text(
        json.dumps(comparison, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
