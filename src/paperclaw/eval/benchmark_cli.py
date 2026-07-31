"""CLI for the repeatable runtime evaluation harness."""

from __future__ import annotations

import argparse
from importlib.metadata import version
from pathlib import Path
import sys

from .case_loader import load_cases
from .case_runner import run_cases
from .runtime_adapter import DurableTraceAdapter, RecordedTraceAdapter
from .unified_report import write_unified_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-eval-run")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("offline", "local", "live", "distributed"), default="offline")
    parser.add_argument("--trace-database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-report", type=Path)
    parser.add_argument("--retrieval-report", type=Path)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--category", action="append")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--enable-llm-judge", action="store_true", help="reserved; deterministic safety rules remain authoritative")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.enable_llm_judge:
        raise ValueError("LLM Judge is not implemented in the deterministic MVP")
    cases = [case for case in load_cases(args.dataset) if case.mode == args.mode]
    if args.case_id:
        cases = [case for case in cases if case.case_id in args.case_id]
    if args.category:
        cases = [case for case in cases if case.category in args.category]
    if not cases:
        raise ValueError("no evaluation cases matched the filters")
    if args.mode == "offline":
        adapter = RecordedTraceAdapter(args.workspace)
    else:
        if args.trace_database is None:
            raise ValueError("--trace-database is required outside offline mode")
        adapter = DurableTraceAdapter(args.trace_database)
    results = run_cases(cases, adapter, fail_fast=args.fail_fast)
    target = write_unified_report(
        args.output,
        cases,
        results,
        dataset=args.dataset,
        paperclaw_version=version("paperclaw"),
        mode=args.mode,
        research_report=args.research_report,
        retrieval_report=args.retrieval_report,
    )
    sys.stdout.write(f"evaluation report: {target}\n")
    return 1 if any(result.status.value == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
