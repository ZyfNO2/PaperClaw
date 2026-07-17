from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from paperclaw.retrieval import (
    ChunkConfig,
    DocumentIdentity,
    IncrementalIndexer,
    MarkdownParser,
    RetrievalRequest,
    SQLiteBM25Retriever,
    SQLiteIndexMaintainer,
)

ROOT = Path(__file__).parents[2]
CONFIG = ChunkConfig(
    max_chars=256,
    min_chars=0,
    overlap_units=0,
    long_block_overlap_chars=32,
)


def _index(indexer: IncrementalIndexer, uri: str, text: str):
    return indexer.index_bytes(
        canonical_uri=uri,
        display_name=uri.rsplit("/", 1)[-1],
        media_type="text/markdown",
        content=text.encode("utf-8"),
    )


def test_windows_style_canonical_uri_with_spaces_and_cjk_is_stable() -> None:
    uris = (
        "file:///C:/Research%20Data/PaperClaw/论文.md",
        "file:///c:/research%20data/paperclaw/论文.md",
        "file:///D:/资料/agent%20runtime.md",
    )
    first = [DocumentIdentity.from_file_uri(uri, "doc.md") for uri in uris]
    second = [DocumentIdentity.from_file_uri(uri, "doc.md") for uri in uris]

    assert [item.document_id for item in first] == [item.document_id for item in second]
    assert [item.canonical_uri for item in first] == list(uris)
    assert len({item.document_id for item in first}) == len(uris)


def test_cross_process_chunk_and_corpus_hashes_ignore_python_hash_seed() -> None:
    script = r'''
import json
from paperclaw.retrieval import ChunkConfig, DocumentIdentity, DocumentVersion, MarkdownParser, SourceArtifact, build_chunks, compute_corpus_hash
uri = "file:///C:/Research%20Data/论文.md"
content = "# 标题\n\n" + "无空格中文段落" * 80
identity = DocumentIdentity.from_file_uri(uri, "论文.md")
artifact = SourceArtifact.from_bytes(document_id=identity.document_id, source_uri=uri, media_type="text/markdown", content=content.encode("utf-8"), created_at="2026-01-01T00:00:00+00:00")
parsed = MarkdownParser().parse(content, source_uri=uri)
version = DocumentVersion.create(document_id=identity.document_id, artifact=artifact, parser_name=parsed.parser_name, parser_version=parsed.parser_version, created_at="2026-01-01T00:00:00+00:00")
chunks = build_chunks(identity=identity, version=version, artifact=artifact, blocks=parsed.blocks, config=ChunkConfig(max_chars=128, min_chars=0, overlap_units=0, long_block_overlap_chars=16), created_at="2026-01-01T00:00:00+00:00")
print(json.dumps([[chunk.chunk_id for chunk in chunks], compute_corpus_hash(chunks)], ensure_ascii=False))
'''
    outputs: list[str] = []
    for seed in ("1", "7", "999"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + environment.get(
            "PYTHONPATH", ""
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        outputs.append(completed.stdout.strip())
    assert len(set(outputs)) == 1


def test_malformed_markdown_fence_and_heading_remain_bounded() -> None:
    text = (
        "# Real heading\n\n"
        "```python\n"
        "# this is code, not a trusted heading\n"
        "print('unterminated fence')\n"
        "## still inside malformed fence\n"
    )
    parsed = MarkdownParser().parse(text, source_uri="file:///docs/malformed.md")

    assert parsed.blocks
    assert all(block.locator.start_line > 0 for block in parsed.blocks)
    assert all(block.locator.end_line >= block.locator.start_line for block in parsed.blocks)
    assert all("this is code" not in block.locator.heading_path for block in parsed.blocks)


def test_cjk_no_space_long_block_always_advances_without_empty_chunks(tmp_path: Path) -> None:
    db = tmp_path / "cjk.db"
    text = "# 中文\n\n" + "这是一个没有空格的超长中文段落用于验证切分持续前进" * 120
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        result = _index(indexer, "file:///docs/中文长文.md", text)
        assert result.inserted_chunks > 1
        rows = indexer.registry.list_active_chunks(result.document_id)

    assert rows
    assert all(chunk.text.strip() for chunk in rows)
    assert all(len(chunk.text) <= CONFIG.max_chars for chunk in rows)
    assert len({chunk.chunk_id for chunk in rows}) == len(rows)
    assert [chunk.ordinal for chunk in rows] == list(range(len(rows)))


def test_interrupted_add_rolls_back_document_version_chunks_and_fts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "rollback.db"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        def fail_manifest(_manifest: object) -> None:
            raise RuntimeError("injected manifest failure")

        monkeypatch.setattr(
            indexer.registry,
            "_insert_manifest_after_count_check",
            fail_manifest,
        )
        with pytest.raises(RuntimeError, match="injected manifest failure"):
            _index(
                indexer,
                "file:///docs/rollback.md",
                "# Rollback\n\nrollbacktoken content",
            )

        assert indexer.registry.active_counts() == (0, 0, 0)
        assert indexer.registry.fts_row_count() == 0
        assert indexer.registry.latest_manifest() is None


def test_concurrent_reader_observes_only_old_or_new_committed_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "concurrent.db"
    uri = "file:///docs/concurrent.md"
    old_text = "# Snapshot\n\nsnapshottoken old-state"
    new_text = "# Snapshot\n\nsnapshottoken new-state"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        _index(indexer, uri, old_text)

    start = threading.Event()
    finished = threading.Event()
    failures: list[BaseException] = []

    def writer() -> None:
        try:
            start.wait(timeout=2)
            with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
                _index(indexer, uri, new_text)
        except BaseException as exc:
            failures.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    observed: set[str] = set()
    start.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (not finished.is_set() or not observed):
        with SQLiteBM25Retriever(db) as retriever:
            result = retriever.query(RetrievalRequest(query="snapshottoken", top_k=1))
        assert len(result.candidates) == 1
        text = result.candidates[0].text
        assert ("old-state" in text) ^ ("new-state" in text)
        observed.add("old" if "old-state" in text else "new")

    thread.join(timeout=2)
    assert not thread.is_alive()
    assert not failures
    assert observed


def test_corruption_rebuild_restores_exact_counts_and_corpus_hash(tmp_path: Path) -> None:
    db = tmp_path / "rebuild.db"
    with IncrementalIndexer(db, chunk_config=CONFIG) as indexer:
        _index(indexer, "file:///docs/a.md", "# A\n\nrebuildtoken alpha")
        _index(indexer, "file:///docs/b.md", "# B\n\nrebuildtoken beta")

    with SQLiteIndexMaintainer(db, chunk_config=CONFIG) as maintainer:
        healthy = maintainer.inspect()
        assert not healthy.is_broken

    connection = sqlite3.connect(db)
    connection.execute("DELETE FROM chunk_fts WHERE rowid = (SELECT MIN(rowid) FROM chunk_fts)")
    connection.execute(
        "INSERT INTO chunk_fts(chunk_id, document_id, version_id, heading, text) "
        "VALUES ('ghost', 'ghost-doc', 'ghost-version', 'Ghost', 'rebuildtoken ghost')"
    )
    connection.commit()
    connection.close()

    with SQLiteIndexMaintainer(db, chunk_config=CONFIG) as maintainer:
        broken = maintainer.inspect()
        assert broken.is_broken
        rebuilt = maintainer.rebuild()
        assert rebuilt.rebuilt is True
        assert rebuilt.after.active_documents == healthy.active_documents
        assert rebuilt.after.active_versions == healthy.active_versions
        assert rebuilt.after.active_chunks == healthy.active_chunks
        assert rebuilt.after.fts_rows == healthy.active_chunks
        assert rebuilt.after.corpus_hash == healthy.corpus_hash
        assert not rebuilt.after.is_broken

    with SQLiteBM25Retriever(db) as retriever:
        result = retriever.query(RetrievalRequest(query="rebuildtoken", top_k=5))
    assert len(result.candidates) == 2
    assert all(candidate.document_id != "ghost-doc" for candidate in result.candidates)
