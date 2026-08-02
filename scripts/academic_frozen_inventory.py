"""Build a local-only locator inventory for the frozen real-paper benchmark."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from paperclaw.academic import AcademicObjectIndex, AcademicRuntime
from paperclaw.papers import PaperImportRequest, PaperService
from paperclaw.projects import ProjectManifestStore


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def resolve_frozen_sources(
    corpus: Path,
    manifest_entries: list[dict[str, Any]],
    frozen: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any], Path]]:
    """Resolve frozen papers by content hash and reject corpus identity drift."""

    by_entry = {item["entry_id"]: item for item in manifest_entries}
    by_hash: dict[str, list[Path]] = {}
    for source in corpus.rglob("*.pdf"):
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        by_hash.setdefault(digest, []).append(source)
    resolved = []
    for paper in frozen["papers"]:
        entry = by_entry.get(paper["entry_id"])
        if entry is None or entry["file_sha256"] != paper["file_sha256"]:
            raise ValueError(f"frozen manifest identity drift: {paper['blind_id']}")
        matches = by_hash.get(paper["file_sha256"], [])
        filename_matches = [
            source for source in matches if source.name == entry.get("logical_filename")
        ]
        category_matches = [
            source
            for source in (filename_matches or matches)
            if source.relative_to(corpus).parts[0] == entry.get("category")
        ]
        if len(category_matches) == 1:
            source = category_matches[0]
        elif len(filename_matches) == 1:
            source = filename_matches[0]
        elif len(matches) == 1:
            source = matches[0]
        elif not matches:
            raise FileNotFoundError(f"frozen source missing: {paper['blind_id']}")
        else:
            raise ValueError(f"ambiguous frozen source: {paper['blind_id']}")
        resolved.append((paper, entry, source))
    return resolved


def _candidate(obj: Any, blind_id: str) -> dict[str, Any]:
    locator = obj.locator
    return {
        "blind_id": blind_id,
        "paper_id": locator.paper_id,
        "version_id": locator.version_id,
        "source_hash": locator.source_hash,
        "object_id": obj.object_id,
        "object_type": obj.object_type,
        "reading_order": obj.reading_order,
        "page_number": locator.page_number,
        "section_path": list(locator.section_path),
        "table_row": locator.table_row,
        "table_column": locator.table_column,
        "bbox": (
            [
                locator.bounding_box.x0,
                locator.bounding_box.y0,
                locator.bounding_box.x1,
                locator.bounding_box.y1,
            ]
            if locator.bounding_box
            else None
        ),
        "text_preview": (obj.text or "").replace("\n", " ")[:240],
        "text_sha256": hashlib.sha256((obj.text or "").encode()).hexdigest(),
        "provenance": obj.provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--frozen-set", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-candidates-per-paper", type=int, default=80)
    args = parser.parse_args()
    corpus = args.corpus.resolve(strict=True)
    workspace = args.workspace.resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(args.frozen_set.read_text(encoding="utf-8"))
    entries = _load_jsonl(args.manifest)
    sources = resolve_frozen_sources(corpus, entries, frozen)

    project = ProjectManifestStore(workspace).initialize("Frozen real-paper inventory")
    papers = PaperService.for_workspace(workspace, project_id=project.project_id)
    runtime = AcademicRuntime.for_workspace(workspace, project.project_id)
    inventory = []
    total_counts: Counter[str] = Counter()
    for frozen_paper, entry, source in sources:
        imported = papers.import_paper(PaperImportRequest(project.project_id, source))
        parsed = runtime.parse_paper(imported.paper.paper_id)
        AcademicObjectIndex(runtime).sync_version(
            imported.paper.paper_id, parsed.version_id
        )
        counts = Counter(obj.object_type for obj in parsed.objects)
        total_counts.update(counts)
        eligible = [
            obj
            for obj in parsed.objects
            if obj.object_type
            in {
                "paragraph",
                "figure",
                "section",
                "caption",
                "table",
                "table_cell",
                "equation",
                "algorithm",
            }
            and (obj.text or "").strip()
        ]
        eligible.sort(
            key=lambda obj: (
                obj.object_type not in {"table_cell", "equation", "algorithm"},
                obj.reading_order,
            )
        )
        inventory.append(
            {
                "blind_id": frozen_paper["blind_id"],
                "entry_id": entry["entry_id"],
                "source_hash": parsed.source_hash,
                "parse_status": parsed.status,
                "object_counts": dict(sorted(counts.items())),
                "label_candidates": [
                    _candidate(obj, frozen_paper["blind_id"])
                    for obj in eligible[: args.max_candidates_per_paper]
                ],
                "warning_count": len(parsed.warnings),
            }
        )

    snapshot = AcademicObjectIndex(runtime).snapshot()
    report = {
        "schema_version": "academic-frozen-inventory.v1",
        "frozen_set_id": frozen["frozen_set_id"],
        "paper_count": len(inventory),
        "index_generation_id": snapshot.generation_id,
        "index_content_hash": snapshot.content_hash,
        "total_object_counts": dict(sorted(total_counts.items())),
        "papers": inventory,
        "contains_text_previews": True,
        "local_only": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "paper_count": report["paper_count"],
                "index_generation_id": report["index_generation_id"],
                "total_object_counts": report["total_object_counts"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
