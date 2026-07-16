from __future__ import annotations

import pytest

from paperclaw.retrieval import (
    ChunkConfig,
    DocumentIdentity,
    DocumentVersion,
    IndexManifest,
    MarkdownParser,
    SQLiteDocumentRegistry,
    SourceArtifact,
    build_chunks,
    compute_corpus_hash,
)


def _document(text: str, config: ChunkConfig, *, source_uri: str):
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


def _manifest(config: ChunkConfig, docs: int, versions: int, chunks) -> IndexManifest:
    return IndexManifest.create(
        chunk_config_hash=config.config_hash,
        parser_versions=("markdown:1",) if versions else (),
        document_count=docs,
        version_count=versions,
        chunk_count=len(chunks),
        corpus_hash=compute_corpus_hash(chunks),
        created_at="2026-01-01T00:00:20+00:00",
    )


def test_manifest_rejects_mixed_active_chunk_configs_and_rolls_back(tmp_path) -> None:
    config_a = ChunkConfig(max_chars=120, min_chars=0, long_block_overlap_chars=10)
    config_b = ChunkConfig(max_chars=90, min_chars=0, long_block_overlap_chars=10)
    first = _document("# A\n\nalpha\n", config_a, source_uri="file:///docs/a.md")
    second = _document("# B\n\nbeta\n", config_b, source_uri="file:///docs/b.md")
    identity_a, artifact_a, version_a, chunks_a = first
    identity_b, artifact_b, version_b, chunks_b = second

    with SQLiteDocumentRegistry(tmp_path / "rag.db") as registry:
        registry.add_document(
            identity=identity_a,
            version=version_a,
            artifact=artifact_a,
            chunks=chunks_a,
            manifest=_manifest(config_a, 1, 1, chunks_a),
        )
        all_chunks = tuple(chunks_a) + tuple(chunks_b)
        mixed_manifest = _manifest(config_b, 2, 2, all_chunks)
        with pytest.raises(ValueError, match="active chunk configs"):
            registry.add_document(
                identity=identity_b,
                version=version_b,
                artifact=artifact_b,
                chunks=chunks_b,
                manifest=mixed_manifest,
            )
        assert registry.active_counts() == (1, 1, len(chunks_a))
        assert registry.fts_row_count() == len(chunks_a)


def test_delete_rejects_wrong_manifest_schema_and_rolls_back(tmp_path) -> None:
    config = ChunkConfig(max_chars=120, min_chars=0, long_block_overlap_chars=10)
    identity, artifact, version, chunks = _document(
        "# A\n\nalpha\n", config, source_uri="file:///docs/a.md"
    )
    with SQLiteDocumentRegistry(tmp_path / "rag.db") as registry:
        registry.add_document(
            identity=identity,
            version=version,
            artifact=artifact,
            chunks=chunks,
            manifest=_manifest(config, 1, 1, chunks),
        )
        wrong_schema = IndexManifest.create(
            chunk_config_hash=config.config_hash,
            parser_versions=(),
            document_count=0,
            version_count=0,
            chunk_count=0,
            corpus_hash=compute_corpus_hash(()),
            schema_version=2,
            created_at="2026-01-01T00:00:30+00:00",
        )
        with pytest.raises(ValueError, match="schema_version"):
            registry.delete_document(
                document_id=identity.document_id,
                manifest=wrong_schema,
            )
        assert registry.active_counts() == (1, 1, len(chunks))
        assert registry.fts_row_count() == len(chunks)
