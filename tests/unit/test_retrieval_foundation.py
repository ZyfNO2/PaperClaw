from __future__ import annotations

import sqlite3

import pytest

from paperclaw.retrieval import (
    ChunkConfig,
    DocumentIdentity,
    DocumentVersion,
    IndexManifest,
    MarkdownParser,
    PlainTextParser,
    SQLiteDocumentRegistry,
    SourceArtifact,
    build_chunks,
    compute_corpus_hash,
    select_parser,
)


def test_identity_artifact_and_version_are_deterministic() -> None:
    identity_a = DocumentIdentity.from_file_uri("file:///docs/guide.md", "guide.md")
    identity_b = DocumentIdentity.from_file_uri("file:///docs/guide.md", "guide.md")
    assert identity_a == identity_b

    artifact_a = SourceArtifact.from_bytes(
        document_id=identity_a.document_id,
        source_uri=identity_a.canonical_uri,
        media_type="text/markdown",
        content=b"# Guide\n\nHello",
        created_at="2026-01-01T00:00:00+00:00",
    )
    artifact_b = SourceArtifact.from_bytes(
        document_id=identity_a.document_id,
        source_uri=identity_a.canonical_uri,
        media_type="text/markdown",
        content=b"# Guide\n\nHello",
        created_at="2026-01-02T00:00:00+00:00",
    )
    assert artifact_a.artifact_id == artifact_b.artifact_id
    assert artifact_a.source_hash == artifact_b.source_hash

    version_a = DocumentVersion.create(
        document_id=identity_a.document_id,
        artifact=artifact_a,
        parser_name="markdown",
        created_at="2026-01-01T00:00:00+00:00",
    )
    version_b = DocumentVersion.create(
        document_id=identity_a.document_id,
        artifact=artifact_b,
        parser_name="markdown",
        created_at="2026-01-02T00:00:00+00:00",
    )
    assert version_a.version_id == version_b.version_id


def test_chunk_config_hash_changes_only_when_config_changes() -> None:
    base = ChunkConfig(max_chars=500, min_chars=50, overlap_units=1)
    same = ChunkConfig(max_chars=500, min_chars=50, overlap_units=1)
    changed = ChunkConfig(max_chars=500, min_chars=50, overlap_units=2)
    assert base.config_hash == same.config_hash
    assert base.config_hash != changed.config_hash


def test_manifest_content_hash_detects_tampering() -> None:
    config = ChunkConfig()
    manifest = IndexManifest.create(
        chunk_config_hash=config.config_hash,
        parser_versions=("markdown:1",),
        document_count=1,
        version_count=1,
        chunk_count=2,
        corpus_hash=compute_corpus_hash(()),
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert manifest.manifest_id.startswith("manifest_")

    with pytest.raises(ValueError, match="content_hash"):
        IndexManifest(
            manifest_id=manifest.manifest_id,
            schema_version=manifest.schema_version,
            index_version=manifest.index_version,
            created_at=manifest.created_at,
            chunk_config_hash=manifest.chunk_config_hash,
            parser_versions=manifest.parser_versions,
            document_count=999,
            version_count=manifest.version_count,
            chunk_count=manifest.chunk_count,
            state=manifest.state,
            corpus_hash=manifest.corpus_hash,
            content_hash=manifest.content_hash,
        )


def test_identity_rejects_non_file_uri() -> None:
    with pytest.raises(ValueError, match="file://"):
        DocumentIdentity("doc_x", "https://example.com/doc", "doc")


def test_markdown_parser_tracks_heading_path_and_lines() -> None:
    text = "# Top\n\nFirst paragraph.\n\n## Child\n\nSecond\nline.\n"
    output = MarkdownParser().parse(text, source_uri="file:///docs/a.md")

    assert [block.kind for block in output.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "paragraph",
    ]
    first = output.blocks[1]
    second = output.blocks[3]
    assert first.locator.heading_path == ("Top",)
    assert (first.locator.start_line, first.locator.end_line) == (3, 3)
    assert second.locator.heading_path == ("Top", "Child")
    assert (second.locator.start_line, second.locator.end_line) == (7, 8)
    assert second.locator.paragraph_index == 1


def test_markdown_heading_inside_fence_is_not_a_heading() -> None:
    text = "# Real\n\n```python\n# not a heading\nprint('x')\n```\n"
    output = MarkdownParser().parse(text, source_uri="file:///docs/code.md")
    assert [block.kind for block in output.blocks] == ["heading", "paragraph"]
    assert "# not a heading" in output.blocks[1].text


def test_plain_text_parser_normalizes_newlines_and_paragraphs() -> None:
    output = PlainTextParser().parse(
        "one\r\ntwo\r\n\r\nthree\r\n",
        source_uri="file:///docs/a.txt",
    )
    assert [block.text for block in output.blocks] == ["one\ntwo", "three"]
    assert output.blocks[0].locator.start_line == 1
    assert output.blocks[1].locator.start_line == 4


def test_select_parser_is_fail_closed() -> None:
    assert isinstance(select_parser(source_uri="file:///x.md"), MarkdownParser)
    assert isinstance(select_parser(source_uri="file:///x.bin", media_type="text/plain"), PlainTextParser)
    with pytest.raises(ValueError, match="unsupported"):
        select_parser(source_uri="file:///x.pdf", media_type="application/pdf")


def _bundle(text: str):
    identity = DocumentIdentity.from_file_uri("file:///docs/a.md", "a.md")
    artifact = SourceArtifact.from_bytes(
        document_id=identity.document_id,
        source_uri=identity.canonical_uri,
        media_type="text/markdown",
        content=text.encode(),
        created_at="2026-01-01T00:00:00+00:00",
    )
    version = DocumentVersion.create(
        document_id=identity.document_id,
        artifact=artifact,
        parser_name="markdown",
        created_at="2026-01-01T00:00:00+00:00",
    )
    blocks = MarkdownParser().parse(text, source_uri=identity.canonical_uri).blocks
    return identity, artifact, version, blocks


def test_chunking_is_deterministic_and_binds_hashes() -> None:
    text = "# Intro\n\nAlpha beta gamma.\n\nDelta epsilon.\n"
    identity, artifact, version, blocks = _bundle(text)
    config = ChunkConfig(max_chars=80, min_chars=0, overlap_units=1, long_block_overlap_chars=10)

    first = build_chunks(
        identity=identity,
        version=version,
        artifact=artifact,
        blocks=blocks,
        config=config,
        created_at="2026-01-01T00:00:00+00:00",
    )
    second = build_chunks(
        identity=identity,
        version=version,
        artifact=artifact,
        blocks=blocks,
        config=config,
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert first == second
    assert all(chunk.source_hash == artifact.source_hash for chunk in first)
    assert all(chunk.chunk_config_hash == config.config_hash for chunk in first)
    assert first[0].locator.heading_path == ("Intro",)


def test_heading_change_forces_a_chunk_boundary() -> None:
    text = "# A\n\nfirst paragraph\n\n# B\n\nsecond paragraph\n"
    identity, artifact, version, blocks = _bundle(text)
    chunks = build_chunks(
        identity=identity,
        version=version,
        artifact=artifact,
        blocks=blocks,
        config=ChunkConfig(max_chars=500, min_chars=0, overlap_units=1),
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert len(chunks) == 2
    assert chunks[0].locator.heading_path == ("A",)
    assert chunks[1].locator.heading_path == ("B",)


def test_long_paragraph_splits_with_deterministic_overlap() -> None:
    text = "# Long\n\n" + ("0123456789 " * 30)
    identity, artifact, version, blocks = _bundle(text)
    chunks = build_chunks(
        identity=identity,
        version=version,
        artifact=artifact,
        blocks=blocks,
        config=ChunkConfig(
            max_chars=90,
            min_chars=0,
            overlap_units=0,
            long_block_overlap_chars=15,
            include_heading_path=False,
        ),
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 90 for chunk in chunks)
    assert chunks[0].locator.start_paragraph == chunks[-1].locator.end_paragraph == 0
    assert chunks[-1].locator.end_fragment > 0
    assert chunks[0].text[-10:] in chunks[1].text


def test_overlap_units_mark_following_chunk() -> None:
    text = "# A\n\n" + "\n\n".join(f"paragraph-{i}-" + ("x" * 25) for i in range(4))
    identity, artifact, version, blocks = _bundle(text)
    chunks = build_chunks(
        identity=identity,
        version=version,
        artifact=artifact,
        blocks=blocks,
        config=ChunkConfig(max_chars=80, min_chars=0, overlap_units=1, long_block_overlap_chars=10),
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert len(chunks) >= 2
    assert chunks[1].locator.overlap_from_previous is True
    assert "paragraph-0" in chunks[0].text
    assert any(token in chunks[1].text for token in ("paragraph-0", "paragraph-1"))


def _document(text: str, config: ChunkConfig, *, source_uri: str = "file:///docs/a.md"):
    identity = DocumentIdentity.from_file_uri(source_uri, source_uri.rsplit("/", 1)[-1])
    artifact = SourceArtifact.from_bytes(
        document_id=identity.document_id,
        source_uri=identity.canonical_uri,
        media_type="text/markdown",
        content=text.encode(),
        created_at="2026-01-01T00:00:00+00:00",
    )
    version = DocumentVersion.create(
        document_id=identity.document_id,
        artifact=artifact,
        parser_name="markdown",
        created_at="2026-01-01T00:00:00+00:00",
    )
    blocks = MarkdownParser().parse(text, source_uri=identity.canonical_uri).blocks
    chunks = build_chunks(
        identity=identity,
        version=version,
        artifact=artifact,
        blocks=blocks,
        config=config,
        created_at="2026-01-01T00:00:00+00:00",
    )
    return identity, artifact, version, chunks


def _manifest(config: ChunkConfig, docs: int, versions: int, chunks, parser_versions=("markdown:1",)) -> IndexManifest:
    return IndexManifest.create(
        chunk_config_hash=config.config_hash,
        parser_versions=parser_versions,
        document_count=docs,
        version_count=versions,
        chunk_count=len(chunks),
        corpus_hash=compute_corpus_hash(chunks),
        created_at=f"2026-01-01T00:00:0{docs + versions + len(chunks)}+00:00",
    )


def test_schema_contains_registry_and_fts5_tables(tmp_path) -> None:
    db = tmp_path / "rag.db"
    with SQLiteDocumentRegistry(db) as registry:
        assert registry.current_schema_version() == 1
    connection = sqlite3.connect(db)
    names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    connection.close()
    assert {
        "documents",
        "document_versions",
        "source_artifacts",
        "chunks",
        "chunk_fts",
        "index_manifests",
    }.issubset(names)


def test_add_update_delete_contract_keeps_fts_in_sync(tmp_path) -> None:
    config = ChunkConfig(max_chars=80, min_chars=0, overlap_units=1, long_block_overlap_chars=10)
    identity, artifact_v1, version_v1, chunks_v1 = _document(
        "# A\n\none paragraph\n\ntwo paragraph\n",
        config,
    )

    with SQLiteDocumentRegistry(tmp_path / "rag.db") as registry:
        add_manifest = _manifest(config, 1, 1, chunks_v1)
        add_result = registry.add_document(
            identity=identity,
            version=version_v1,
            artifact=artifact_v1,
            chunks=chunks_v1,
            manifest=add_manifest,
        )
        assert add_result.operation == "add"
        assert registry.active_counts() == (1, 1, len(chunks_v1))
        assert registry.fts_row_count() == len(chunks_v1)
        assert registry.latest_manifest() == add_manifest

        _, artifact_v2, version_v2, chunks_v2 = _document(
            "# A\n\nreplacement content with a different source hash\n",
            config,
        )
        update_manifest = _manifest(config, 1, 1, chunks_v2)
        update_result = registry.update_document(
            identity=identity,
            version=version_v2,
            artifact=artifact_v2,
            chunks=chunks_v2,
            manifest=update_manifest,
        )
        assert update_result.operation == "update"
        assert update_result.deactivated_versions == 1
        assert update_result.deactivated_chunks == len(chunks_v1)
        assert registry.get_active_version(identity.document_id) == version_v2
        assert registry.list_active_chunks(identity.document_id) == list(chunks_v2)
        assert registry.fts_row_count() == len(chunks_v2)

        delete_manifest = _manifest(config, 0, 0, (), parser_versions=())
        delete_result = registry.delete_document(
            document_id=identity.document_id,
            manifest=delete_manifest,
        )
        assert delete_result.operation == "delete"
        assert registry.active_counts() == (0, 0, 0)
        assert registry.fts_row_count() == 0
        assert registry.get_active_version(identity.document_id) is None


def test_manifest_mismatch_rolls_back_add(tmp_path) -> None:
    config = ChunkConfig(max_chars=100, min_chars=0, long_block_overlap_chars=10)
    identity, artifact, version, chunks = _document("# A\n\ncontent\n", config)
    wrong_manifest = IndexManifest.create(
        chunk_config_hash=config.config_hash,
        parser_versions=("markdown:1",),
        document_count=1,
        version_count=1,
        chunk_count=len(chunks) + 1,
        corpus_hash=compute_corpus_hash(chunks),
        created_at="2026-01-01T00:00:09+00:00",
    )

    with SQLiteDocumentRegistry(tmp_path / "rag.db") as registry:
        with pytest.raises(ValueError, match="manifest counts"):
            registry.add_document(
                identity=identity,
                version=version,
                artifact=artifact,
                chunks=chunks,
                manifest=wrong_manifest,
            )
        assert registry.active_counts() == (0, 0, 0)
        assert registry.fts_row_count() == 0


def test_add_rejects_non_contiguous_chunk_ordinals(tmp_path) -> None:
    config = ChunkConfig(max_chars=70, min_chars=0, long_block_overlap_chars=10)
    identity, artifact, version, chunks = _document(
        "# A\n\none longish paragraph xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n\nsecond\n",
        config,
    )
    assert chunks
    malformed = (chunks[0], chunks[-1]) if len(chunks) > 1 else (chunks[0], chunks[0])
    manifest = _manifest(config, 1, 1, malformed)
    with SQLiteDocumentRegistry(tmp_path / "rag.db") as registry:
        with pytest.raises(ValueError, match="ordinals"):
            registry.add_document(
                identity=identity,
                version=version,
                artifact=artifact,
                chunks=malformed,
                manifest=manifest,
            )


def test_update_rejects_unchanged_version_without_mutating_state(tmp_path) -> None:
    config = ChunkConfig(max_chars=100, min_chars=0, long_block_overlap_chars=10)
    identity, artifact, version, chunks = _document("# A\n\ncontent\n", config)
    with SQLiteDocumentRegistry(tmp_path / "rag.db") as registry:
        manifest = _manifest(config, 1, 1, chunks)
        registry.add_document(
            identity=identity,
            version=version,
            artifact=artifact,
            chunks=chunks,
            manifest=manifest,
        )
        with pytest.raises(ValueError, match="already exists"):
            registry.update_document(
                identity=identity,
                version=version,
                artifact=artifact,
                chunks=chunks,
                manifest=manifest,
            )
        assert registry.active_counts() == (1, 1, len(chunks))
        assert registry.fts_row_count() == len(chunks)


def test_manifest_covers_all_active_documents(tmp_path) -> None:
    config = ChunkConfig(max_chars=120, min_chars=0, long_block_overlap_chars=10)
    first = _document("# A\n\nalpha\n", config, source_uri="file:///docs/a.md")
    second = _document("# B\n\nbeta\n", config, source_uri="file:///docs/b.md")
    identity_a, artifact_a, version_a, chunks_a = first
    identity_b, artifact_b, version_b, chunks_b = second

    with SQLiteDocumentRegistry(tmp_path / "rag.db") as registry:
        registry.add_document(
            identity=identity_a,
            version=version_a,
            artifact=artifact_a,
            chunks=chunks_a,
            manifest=_manifest(config, 1, 1, chunks_a),
        )
        all_chunks = tuple(chunks_a) + tuple(chunks_b)
        registry.add_document(
            identity=identity_b,
            version=version_b,
            artifact=artifact_b,
            chunks=chunks_b,
            manifest=_manifest(config, 2, 2, all_chunks),
        )
        assert registry.active_counts() == (2, 2, len(all_chunks))
        assert registry.latest_manifest().corpus_hash == compute_corpus_hash(all_chunks)
