"""Academic retrieval benchmark framework.

Runs retrieval queries against the frozen 12 corpus and reports
Recall@K, locator accuracy, and abstention metrics.

Usage:
    python scripts/academic_retrieval_benchmark.py \
        --corpus data/paper_corpus \
        --queries benchmarks/academic_rag/v1/eval/queries.jsonl \
        --output artifacts/v0_43/retrieval_benchmark.json

Requires local data/paper_corpus (not run in CI).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from paperclaw.academic import AcademicRuntime, RetrievalRequest, RetrievalBudget
from paperclaw.papers import PaperImportRequest, PaperService
from paperclaw.projects import ProjectManifestStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    corpus = args.corpus.resolve(strict=True)
    queries_path = args.queries.resolve(strict=True)
    if not queries_path.exists():
        print(f"queries file not found: {queries_path}")
        print("Create benchmarks/academic_rag/v1/eval/queries.jsonl first (H5).")
        return 1

    workspace = Path("build/retrieval-benchmark")
    if workspace.exists():
        import shutil
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    manifest = ProjectManifestStore(workspace).initialize("Retrieval benchmark")
    papers = PaperService.for_workspace(workspace, project_id=manifest.project_id)
    runtime = AcademicRuntime(workspace, manifest.project_id)

    pdfs = sorted(corpus.rglob("*.pdf"), key=lambda p: p.as_posix().casefold())
    paper_ids = []
    for pdf in pdfs:
        try:
            imported = papers.import_paper(
                PaperImportRequest(manifest.project_id, pdf)
            )
            paper_ids.append(imported.paper.paper_id)
            runtime.parse_paper(imported.paper.paper_id)
        except Exception:
            pass

    runtime.build_index()

    queries = [
        json.loads(line)
        for line in queries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results = []
    started = time.perf_counter()
    for q in queries:
        request = RetrievalRequest(
            text=q["text"],
            channels=tuple(q.get("channels", ("lexical", "dense"))),
            budget=RetrievalBudget(max_candidates=args.top_k),
        )
        result = runtime.retrieve(request)
        hit = any(
            c.locator.object_id == q.get("expected_object_id")
            for c in result.candidates
        ) if q.get("expected_object_id") else None
        results.append({
            "query_id": q.get("query_id", ""),
            "text": q["text"],
            "sufficiency": result.sufficiency,
            "candidate_count": len(result.candidates),
            "top_score": result.candidates[0].fused_score if result.candidates else 0.0,
            "hit_at_k": hit,
        })

    elapsed = time.perf_counter() - started
    total = len(results)
    hits = sum(1 for r in results if r["hit_at_k"] is True)
    misses = sum(1 for r in results if r["hit_at_k"] is False)
    abstentions = sum(1 for r in results if r["sufficiency"] == "insufficient")

    report = {
        "schema_version": "academic-retrieval-benchmark.v1",
        "corpus_pdf_count": len(pdfs),
        "indexed_paper_count": len(paper_ids),
        "query_count": total,
        "top_k": args.top_k,
        "recall_at_k": hits / max(1, hits + misses) if (hits + misses) > 0 else None,
        "abstention_count": abstentions,
        "elapsed_seconds": round(elapsed, 3),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
