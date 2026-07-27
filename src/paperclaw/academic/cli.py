"""CLI adapter for academic parsing and retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from paperclaw.projects import ProjectManifestStore
from .contracts import AcademicQuery
from .runtime import AcademicRuntime


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="paperclaw academic")
    parser.add_argument("--workspace", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("parse").add_argument("paper_id")
    commands.add_parser("index")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--paper-id", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        root = Path(args.workspace).resolve(strict=True)
        manifest = ProjectManifestStore(root).load()
        runtime = AcademicRuntime.for_workspace(root, manifest.project_id)
        if args.command == "parse":
            result = runtime.parse_paper(args.paper_id)
            payload = {
                "manifest_id": result.manifest_id, "status": result.status,
                "paper_id": result.paper_id, "version_id": result.version_id,
                "page_count": result.page_count, "object_count": len(result.objects),
                "warnings": list(result.warnings),
            }
        elif args.command == "index":
            payload = as_public(runtime.build_index())
        else:
            result = runtime.retrieve(AcademicQuery(args.query, tuple(args.paper_id)))
            payload = {
                "query": result.query, "sufficiency": result.sufficiency,
                "should_abstain": result.should_abstain,
                "reasons": list(result.reasons),
                "candidates": [
                    {
                        "locator": item.locator.to_dict(), "text": item.text,
                        "scores": {"lexical": item.lexical_score, "dense": item.dense_score,
                                   "visual": item.visual_score, "fused": item.fused_score},
                        "explanation": list(item.explanation),
                    }
                    for item in result.candidates
                ],
            }
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)[:500]}))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def as_public(value):
    return {
        "generation_id": value.generation_id, "corpus_hash": value.corpus_hash,
        "model_fingerprint": value.model_fingerprint, "state": value.state,
        "object_count": value.object_count,
    }
