"""CLI adapter for the paper import and versioning module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from paperclaw.projects import ProjectManifestStore

from .contracts import MetadataPatch, PaperImportRequest
from .repository import PaperConflictError, PaperNotFoundError
from .service import PaperService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperclaw papers")
    parser.add_argument("--workspace", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    import_parser = commands.add_parser("import")
    import_parser.add_argument("source")
    import_parser.add_argument("--paper-id")
    commands.add_parser("list").add_argument("--limit", type=int, default=50)
    commands.add_parser("show").add_argument("paper_id")
    commands.add_parser("versions").add_argument("paper_id")
    confirm = commands.add_parser("confirm-metadata")
    confirm.add_argument("paper_id")
    confirm.add_argument("--expected-revision", type=int, required=True)
    confirm.add_argument("--title")
    confirm.add_argument("--authors", nargs="*")
    confirm.add_argument("--year", type=int)
    confirm.add_argument("--doi")
    confirm.add_argument("--arxiv-id")
    confirm.add_argument("--language")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace = Path(args.workspace).resolve(strict=True)
        manifest = ProjectManifestStore(workspace).load()
        service = PaperService.for_workspace(workspace, project_id=manifest.project_id)
        if args.command == "import":
            payload = service.import_paper(
                PaperImportRequest(manifest.project_id, args.source, paper_id=args.paper_id)
            ).to_public_dict()
        elif args.command == "list":
            payload = {
                "papers": [
                    paper.to_public_dict()
                    for paper in service.list_papers(manifest.project_id, limit=args.limit)
                ]
            }
        elif args.command == "show":
            payload = service.get_paper(manifest.project_id, args.paper_id).to_public_dict()
        elif args.command == "versions":
            payload = {
                "versions": [
                    version.to_public_dict()
                    for version in service.list_versions(manifest.project_id, args.paper_id)
                ]
            }
        else:
            patch = MetadataPatch(
                title=args.title,
                authors=tuple(args.authors) if args.authors is not None else None,
                year=args.year,
                doi=args.doi,
                arxiv_id=args.arxiv_id,
                language=args.language,
            )
            payload = service.confirm_metadata(
                manifest.project_id, args.paper_id, patch, args.expected_revision
            ).to_public_dict()
    except (FileNotFoundError, ValueError, PaperNotFoundError, PaperConflictError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)[:500]}))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
