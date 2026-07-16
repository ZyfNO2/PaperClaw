from __future__ import annotations

import json
from pathlib import Path

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

FIXTURE = Path(__file__).parents[1] / "fixtures" / "rag_grounding_fixture.json"
CONFIG = ChunkConfig(
    max_chars=800,
    min_chars=0,
    overlap_units=0,
    long_block_overlap_chars=40,
)


def _prompt(task: str) -> str:
    return f"[Identity]\nAgent\n\n[Task]\n{task}\n[History]\n[]"


def _request(task: str) -> ContextRequest:
    return ContextRequest(
        run_id="run-rag",
        conversation_id="conv-rag",
        step_id="model-1",
        raw_prompt=_prompt(task),
        workspace="/workspace",
    )


def _build_fixture_db(tmp_path: Path) -> tuple[Path, dict]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    db = tmp_path / "rag.db"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        for document in fixture["documents"]:
            indexer.index_bytes(
                canonical_uri=document["uri"],
                display_name=document["name"],
                media_type="text/markdown",
                content=document["text"].encode("utf-8"),
            )
    return db, fixture


def test_retrieval_candidates_are_citation_bound_and_in_untrusted_section(
    tmp_path: Path,
) -> None:
    db, fixture = _build_fixture_db(tmp_path)
    retriever = SQLiteBM25Retriever(db)
    source = RetrievalContextSource(
        retriever,
        policy=RetrievalGroundingPolicy(top_k=3, candidate_pool_size=10),
    )
    registry = ContextSourceRegistry()
    register_retrieval_context_source(registry, source)
    registry.freeze()
    task = fixture["queries"][1]["task"]

    try:
        assembly = ContextOrchestrator(sources=(registry,)).assemble(_request(task))
    finally:
        retriever.close()

    assert source.last_decision is not None and source.last_decision.answerable
    assert source.last_anchors
    anchor = source.last_anchors[0]
    assert anchor.version_id
    assert anchor.locator.start_line > 0
    assert assembly.sections[-1].name == "UNTRUSTED DATA"
    assert assembly.sections[-1].trust == "external_untrusted"
    assert anchor.label in assembly.sections[-1].content
    assert "IGNORE ALL PRIOR INSTRUCTIONS" in assembly.sections[-1].content
    runtime_content = next(
        section.content for section in assembly.sections if section.name == "RUNTIME PROTOCOL"
    )
    assert "IGNORE ALL PRIOR INSTRUCTIONS" not in runtime_content
    retrieval_tokens = dict(assembly.trace.allocation.bucket_tokens)["retrieval"]
    assert retrieval_tokens > 0


def test_unanswerable_query_returns_pinned_local_abstention_candidate(
    tmp_path: Path,
) -> None:
    db, fixture = _build_fixture_db(tmp_path)
    retriever = SQLiteBM25Retriever(db)
    source = RetrievalContextSource(retriever)
    try:
        candidates = source.collect(_request(fixture["unanswerable"]["task"]))
        assembly = ContextOrchestrator(sources=(source,)).assemble(
            _request(fixture["unanswerable"]["task"])
        )
    finally:
        retriever.close()

    assert source.last_decision is not None
    assert source.last_decision.status == "abstain"
    assert len(candidates) == 1
    assert candidates[0].trust == "trusted_local"
    assert candidates[0].pinned
    assert candidates[0].metadata["answerable"] is False
    assert "Explicitly abstain" in assembly.prompt


def test_duplicate_and_stale_results_do_not_create_citation_anchors(tmp_path: Path) -> None:
    db = tmp_path / "rag.db"
    duplicate = "# Shared\n\nduplicatecomet exact evidence text"
    uri = "file:///fixture/versioned.md"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        indexer.index_bytes(
            canonical_uri="file:///fixture/a.md",
            display_name="a.md",
            media_type="text/markdown",
            content=duplicate.encode(),
        )
        indexer.index_bytes(
            canonical_uri="file:///fixture/b.md",
            display_name="b.md",
            media_type="text/markdown",
            content=duplicate.encode(),
        )
        indexer.index_bytes(
            canonical_uri=uri,
            display_name="versioned.md",
            media_type="text/markdown",
            content=b"# Old\n\nlegacyquartz old evidence",
        )
        indexer.index_bytes(
            canonical_uri=uri,
            display_name="versioned.md",
            media_type="text/markdown",
            content=b"# New\n\nfreshcobalt current evidence",
        )

    retriever = SQLiteBM25Retriever(db)
    source = RetrievalContextSource(retriever)
    try:
        duplicate_candidates = source.collect(_request("duplicatecomet evidence"))
        assert len(duplicate_candidates) == 1
        assert len(source.last_anchors) == 1
        stale_candidates = source.collect(_request("legacyquartz"))
    finally:
        retriever.close()

    assert len(stale_candidates) == 1
    assert stale_candidates[0].metadata["answerable"] is False
    assert source.last_anchors == ()


def test_citation_correctness_unsupported_claim_rate_and_label_resolution(
    tmp_path: Path,
) -> None:
    db, fixture = _build_fixture_db(tmp_path)
    retriever = SQLiteBM25Retriever(db)
    source = RetrievalContextSource(retriever)
    try:
        source.collect(_request(fixture["queries"][0]["task"]))
    finally:
        retriever.close()
    anchor = source.last_anchors[0]
    answer = f"SQLite uses a WAL file {anchor.label}."
    assert cited_anchor_ids(answer, source.last_anchors) == (anchor.anchor_id,)

    metrics = evaluate_grounding(
        (
            GroundingClaimJudgment(
                claim_id="supported",
                cited_anchor_ids=(anchor.anchor_id,),
                supporting_anchor_ids=(anchor.anchor_id,),
            ),
            GroundingClaimJudgment(
                claim_id="fabricated-citation",
                cited_anchor_ids=("citation_unknown",),
                supporting_anchor_ids=(anchor.anchor_id,),
            ),
            GroundingClaimJudgment(
                claim_id="correct-abstention",
                cited_anchor_ids=(),
                supporting_anchor_ids=(),
                answerable=False,
                abstained=True,
            ),
        ),
        known_anchor_ids=(anchor.anchor_id,),
    )

    assert metrics.citation_correctness == 0.5
    assert metrics.unsupported_claim_rate == 0.5
    assert metrics.abstention_accuracy == 1.0
