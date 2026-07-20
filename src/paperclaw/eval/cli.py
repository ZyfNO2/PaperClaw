"""Aggregate latency, reliability, token, and cost reports over durable traces."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from paperclaw.eval.aggregate import PricingTable, aggregate_runs, render_aggregate_eval_text
from paperclaw.trace import SQLiteTraceReader, TraceRedactor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw-observe")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--pricing", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pricing = PricingTable()
    if args.pricing is not None:
        payload = json.loads(args.pricing.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("pricing file must contain a JSON object")
        pricing = PricingTable.from_mapping(payload)
    reader = SQLiteTraceReader(
        args.database,
        redactor=TraceRedactor(secret_values=[os.environ.get("PAPERCLAW_API_KEY", "")]),
    )
    report = aggregate_runs(
        reader,
        args.run_id,
        pricing=pricing,
        require_terminal=not args.allow_partial,
    )
    rendered = (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_aggregate_eval_text(report)
    ) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
