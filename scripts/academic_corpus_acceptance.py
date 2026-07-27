"""Run bounded Academic RAG acceptance over a local PDF corpus without exporting text."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

from paperclaw.academic import AcademicRuntime, RetrievalRequest
from paperclaw.papers import PaperImportRequest, PaperService
from paperclaw.projects import ProjectManifestStore

_IDENTIFIER = re.compile(
    r"\b(?:10\.\d{4,9}/[-._;()/:A-Za-z0-9]+|arXiv:\d{4}\.\d{4,5})\b",
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    corpus = args.corpus.resolve(strict=True)
    workspace = args.workspace.resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=False)
    pdfs = sorted(corpus.rglob("*.pdf"), key=lambda path: path.as_posix().casefold())
    if not pdfs:
        raise SystemExit("corpus contains no PDF files")

    manifest = ProjectManifestStore(workspace).initialize("Academic corpus acceptance")
    papers = PaperService.for_workspace(workspace, project_id=manifest.project_id)
    runtime = AcademicRuntime.for_workspace(workspace, manifest.project_id)
    object_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    failures: list[dict[str, str]] = []
    digest_rows: list[str] = []
    imported_ids: list[str] = []
    identifiers: list[str] = []
    started = time.perf_counter()

    for source in pdfs:
        relative = source.relative_to(corpus).as_posix()
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        digest_rows.append(f"{relative}\0{source_hash}")
        categories[relative.split("/", 1)[0]] += 1
        try:
            imported = papers.import_paper(
                PaperImportRequest(manifest.project_id, source)
            )
            imported_ids.append(imported.paper.paper_id)
            parsed = runtime.parse_paper(imported.paper.paper_id)
            status_counts[parsed.status] += 1
            object_counts.update(item.object_type for item in parsed.objects)
            for item in parsed.objects:
                if item.text:
                    identifiers.extend(_IDENTIFIER.findall(item.text))
        except Exception as exc:  # report every structured corpus failure
            status_counts["failed"] += 1
            failures.append(
                {
                    "path": relative,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            )

    generation = runtime.build_index()
    exact_smoke: dict[str, object] | None = None
    if identifiers:
        identifier = identifiers[0]
        result = runtime.retrieve(
            RetrievalRequest(
                text=identifier,
                channels=("exact", "lexical"),
                paper_ids=tuple(imported_ids),
            )
        )
        exact_smoke = {
            "identifier_sha256": hashlib.sha256(identifier.encode("utf-8")).hexdigest(),
            "sufficiency": result.sufficiency,
            "candidate_count": len(result.candidates),
            "top_exact_score": (
                result.candidates[0].channel_scores.get("exact", 0.0)
                if result.candidates
                else 0.0
            ),
        }

    corpus_digest = hashlib.sha256(
        ("\n".join(digest_rows) + "\n").encode("utf-8")
    ).hexdigest()
    report = {
        "schema_version": 1,
        "corpus_root_name": corpus.name,
        "corpus_digest": corpus_digest,
        "pdf_count": len(pdfs),
        "category_counts": dict(sorted(categories.items())),
        "parse_status_counts": dict(sorted(status_counts.items())),
        "object_counts": dict(sorted(object_counts.items())),
        "index_generation": {
            "generation_id": generation.generation_id,
            "corpus_hash": generation.corpus_hash,
            "model_fingerprint": generation.model_fingerprint,
            "state": generation.state,
            "object_count": generation.object_count,
        },
        "exact_identifier_smoke": exact_smoke,
        "failure_count": len(failures),
        "failures": failures,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "contains_full_text": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failures and len(pdfs) == 107 else 1


if __name__ == "__main__":
    raise SystemExit(main())
