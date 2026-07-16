"""PaperClaw v0.09.1 RAG document and index foundation."""

from paperclaw.retrieval.chunking import build_chunks
from paperclaw.retrieval.contracts import (
    BlockLocator,
    Chunk,
    ChunkConfig,
    ChunkLocator,
    DocumentIdentity,
    DocumentVersion,
    IndexManifest,
    ParsedBlock,
    RegistryMutationResult,
    SourceArtifact,
    canonical_json,
    compute_corpus_hash,
    sha256_bytes,
    sha256_text,
    stable_id,
)
from paperclaw.retrieval.parsers import MarkdownParser, ParserOutput, PlainTextParser, select_parser
from paperclaw.retrieval.registry import SQLiteDocumentRegistry

__all__ = [
    "BlockLocator",
    "Chunk",
    "ChunkConfig",
    "ChunkLocator",
    "DocumentIdentity",
    "DocumentVersion",
    "IndexManifest",
    "MarkdownParser",
    "ParsedBlock",
    "ParserOutput",
    "PlainTextParser",
    "RegistryMutationResult",
    "SQLiteDocumentRegistry",
    "SourceArtifact",
    "build_chunks",
    "canonical_json",
    "compute_corpus_hash",
    "select_parser",
    "sha256_bytes",
    "sha256_text",
    "stable_id",
]
