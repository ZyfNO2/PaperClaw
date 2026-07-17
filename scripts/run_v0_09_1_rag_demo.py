"""Run the v0.09.1 local BM25/Context/Citation demo without a Provider."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Any

from paperclaw.context import ContextOrchestrator, ContextRequest, ContextSourceRegistry
from paperclaw.retrieval import (
    ChunkConfig,
    GroundingClaimJudgment,
    IncrementalIndexer,
    RetrievalContextSource,
    RetrievalGroundingPolicy,
    SQLiteBM25Retriever,
    cited_anchor_ids,
    evaluate_grounding,
    register_retrieval_context_source,
)

FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "rag_grounding_fixture.json"


def run_demo(output_path: Path | None = None) -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    task = fixture["queries"][1]["task"]
    with tempfile.TemporaryDirectory(prefix="paperclaw-rag-demo-") as temporary:
        db = Path(temporary) / "rag.db"
        config = ChunkConfig(
            max_chars=800,
            min_chars=0,
            overlap_units=0,
            long_block_overlap_chars=40,
        )
        with IncrementalIndexer(db, chunk_config=config) as indexer:
            for document in fixture["documents"]:
                indexer.index_bytes(
                    canonical_uri=document["uri"],
                    display_name=document["name"],
                    media_type="text/markdown",
                    content=document["text"].encode("utf-8"),
                )

        retriever = SQLiteBM25Retriever(db)
        source = RetrievalContextSource(
            retriever,
            policy=RetrievalGroundingPolicy(top_k=3, candidate_pool_size=10),
        )
        sources = ContextSourceRegistry()
        register_retrieval_context_source(sources, source)
        sources.freeze()
        request = ContextRequest(
            run_id="run-rag-demo",
            conversation_id="conv-rag-demo",
            step_id="model-1",
            raw_prompt=f"[Task]\n{task}\n[History]\n[]",
            workspace="/workspace",
        )
        try:
            assembly = ContextOrchestrator(sources=(sources,)).assemble(request)
        finally:
            retriever.close()

    anchor = source.last_anchors[0]
    answer = f"The verified launch code is cobalt-42 {anchor.label}."
    cited = cited_anchor_ids(answer, source.last_anchors)
    metrics = evaluate_grounding(
        (
            GroundingClaimJudgment(
                claim_id="launch-code",
                cited_anchor_ids=cited,
                supporting_anchor_ids=(anchor.anchor_id,),
                answerable=True,
                abstained=False,
            ),
        ),
        known_anchor_ids=(anchor.anchor_id,),
    )
    runtime_section = next(
        section.content for section in assembly.sections if section.name == "RUNTIME PROTOCOL"
    )
    untrusted_section = next(
        section.content for section in assembly.sections if section.name == "UNTRUSTED DATA"
    )
    payload = {
        "schema_version": 1,
        "task": task,
        "answer": answer,
        "decision": source.last_decision.to_dict() if source.last_decision else None,
        "anchors": [item.to_dict() for item in source.last_anchors],
        "assembly": {
            "fingerprint": assembly.fingerprint,
            "section_names": [section.name for section in assembly.sections],
            "retrieval_candidate_ids": list(
                assembly.sections[-1].candidate_ids
                if assembly.sections[-1].name == "UNTRUSTED DATA"
                else ()
            ),
            "injection_in_runtime_protocol": "IGNORE ALL PRIOR INSTRUCTIONS"
            in runtime_section,
            "injection_contained_in_untrusted_data": "IGNORE ALL PRIOR INSTRUCTIONS"
            in untrusted_section,
        },
        "grounding_metrics": metrics.to_dict(),
    }
    # The public demo contract is JSON, so normalize tuples and other JSON-compatible
    # containers before both returning and persisting the payload. This guarantees
    # replay equality between the in-memory result and the saved artifact.
    payload = json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run_demo(args.output)
    if args.output is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
