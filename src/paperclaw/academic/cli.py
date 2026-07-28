"""CLI adapter for academic parsing and retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from paperclaw.projects import ProjectManifestStore
from .contracts import EvidenceLocator, RetrievalRequest
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
    search.add_argument(
        "--channel", action="append", choices=("lexical", "dense", "visual")
    )
    resolve = commands.add_parser("resolve")
    resolve.add_argument(
        "locator",
        help="academic.v1 EvidenceLocator JSON or path to a JSON file",
    )
    args = parser.parse_args(argv)
    try:
        root = Path(args.workspace).resolve(strict=True)
        manifest = ProjectManifestStore(root).load()
        runtime = AcademicRuntime.for_workspace(root, manifest.project_id)
        if args.command == "parse":
            result = runtime.parse_paper(args.paper_id)
            payload = result.to_public_summary()
        elif args.command == "index":
            payload = as_public(runtime.build_index())
        elif args.command == "search":
            result = runtime.retrieve(
                RetrievalRequest(
                    args.query,
                    tuple(args.channel or ("lexical", "dense", "visual")),
                    tuple(args.paper_id),
                )
            )
            payload = runtime.evidence_bundle(result).to_dict()
        else:
            locator_path = Path(args.locator)
            try:
                is_locator_file = locator_path.is_file()
            except OSError:
                is_locator_file = False
            raw_locator = locator_path.read_text(encoding="utf-8") if is_locator_file else args.locator
            payload = runtime.resolve(
                EvidenceLocator.from_dict(json.loads(raw_locator))
            ).to_dict()
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "message": str(exc)[:500]}
            )
        )
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def as_public(value):
    return {
        "generation_id": value.generation_id,
        "corpus_hash": value.corpus_hash,
        "model_fingerprint": value.model_fingerprint,
        "state": value.state,
        "object_count": value.object_count,
    }
