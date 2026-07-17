"""Deterministic heading-aware chunking for Markdown and plain text."""

from __future__ import annotations

from dataclasses import dataclass

from paperclaw.retrieval.contracts import (
    Chunk,
    ChunkConfig,
    ChunkLocator,
    DocumentIdentity,
    DocumentVersion,
    ParsedBlock,
    SourceArtifact,
    sha256_text,
    stable_id,
    utc_now_iso,
)


@dataclass(frozen=True)
class _Unit:
    text: str
    source_uri: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    paragraph_index: int
    fragment_index: int


def _heading_prefix(block: ParsedBlock, config: ChunkConfig) -> str:
    if config.include_heading_path and block.locator.heading_path:
        return " > ".join(block.locator.heading_path) + "\n\n"
    return ""


def _split_long_block(block: ParsedBlock, config: ChunkConfig) -> list[_Unit]:
    text = block.text
    max_payload = config.max_chars - len(_heading_prefix(block, config))
    if max_payload <= 0:
        raise ValueError("heading path leaves no room for chunk content")
    if len(text) <= max_payload:
        return [
            _Unit(
                text=text,
                source_uri=block.locator.source_uri,
                heading_path=block.locator.heading_path,
                start_line=block.locator.start_line,
                end_line=block.locator.end_line,
                paragraph_index=block.locator.paragraph_index or 0,
                fragment_index=0,
            )
        ]

    units: list[_Unit] = []
    start = 0
    fragment = 0
    while start < len(text):
        hard_end = min(len(text), start + max_payload)
        end = hard_end
        if hard_end < len(text):
            search_floor = start + max(1, min(config.min_chars, max_payload - 1))
            split_at = max(text.rfind("\n", search_floor, hard_end), text.rfind(" ", search_floor, hard_end))
            if split_at > start:
                end = split_at
        fragment_text = text[start:end].strip()
        if not fragment_text:
            end = hard_end
            fragment_text = text[start:end]
        units.append(
            _Unit(
                text=fragment_text,
                source_uri=block.locator.source_uri,
                heading_path=block.locator.heading_path,
                start_line=block.locator.start_line,
                end_line=block.locator.end_line,
                paragraph_index=block.locator.paragraph_index or 0,
                fragment_index=fragment,
            )
        )
        if end >= len(text):
            break
        overlap = min(config.long_block_overlap_chars, max_payload - 1)
        start = max(end - overlap, start + 1)
        fragment += 1
    return units


def _render(units: list[_Unit], config: ChunkConfig) -> str:
    body = "\n\n".join(unit.text for unit in units).strip()
    if config.include_heading_path and units and units[0].heading_path:
        heading = " > ".join(units[0].heading_path)
        return f"{heading}\n\n{body}"
    return body


def build_chunks(
    *,
    identity: DocumentIdentity,
    version: DocumentVersion,
    artifact: SourceArtifact,
    blocks: tuple[ParsedBlock, ...],
    config: ChunkConfig,
    created_at: str | None = None,
) -> tuple[Chunk, ...]:
    """Build deterministic chunks with exact version, hash and locator bindings."""

    if version.document_id != identity.document_id:
        raise ValueError("version document_id does not match identity")
    if artifact.document_id != identity.document_id:
        raise ValueError("artifact document_id does not match identity")
    if version.source_artifact_id != artifact.artifact_id:
        raise ValueError("version source_artifact_id does not match artifact")
    if version.source_hash != artifact.source_hash:
        raise ValueError("version source_hash does not match artifact")

    units: list[_Unit] = []
    for block in blocks:
        if block.kind == "paragraph":
            units.extend(_split_long_block(block, config))

    if not units:
        return ()

    emitted: list[tuple[list[_Unit], bool]] = []
    current: list[_Unit] = []
    current_overlap = False

    def flush() -> None:
        nonlocal current, current_overlap
        if current:
            emitted.append((current, current_overlap))
            current = []
            current_overlap = False

    for unit in units:
        if current and unit.heading_path != current[-1].heading_path:
            flush()
        candidate = current + [unit]
        if current and len(_render(candidate, config)) > config.max_chars:
            previous = current
            flush()
            if config.overlap_units:
                carry = previous[-config.overlap_units :]
                while carry and len(_render(carry + [unit], config)) > config.max_chars:
                    carry = carry[1:]
                if carry:
                    current = list(carry)
                    current_overlap = True
        current.append(unit)
    flush()

    chunks: list[Chunk] = []
    timestamp = created_at or utc_now_iso()
    for ordinal, (chunk_units, overlap) in enumerate(emitted):
        text = _render(chunk_units, config)
        content_hash = sha256_text(text)
        locator = ChunkLocator(
            source_uri=chunk_units[0].source_uri,
            heading_path=chunk_units[0].heading_path,
            start_line=min(unit.start_line for unit in chunk_units),
            end_line=max(unit.end_line for unit in chunk_units),
            start_paragraph=min(unit.paragraph_index for unit in chunk_units),
            end_paragraph=max(unit.paragraph_index for unit in chunk_units),
            start_fragment=chunk_units[0].fragment_index,
            end_fragment=chunk_units[-1].fragment_index,
            overlap_from_previous=overlap,
        )
        chunks.append(
            Chunk(
                chunk_id=stable_id(
                    "chunk",
                    version.version_id,
                    str(ordinal),
                    content_hash,
                    config.config_hash,
                ),
                document_id=identity.document_id,
                version_id=version.version_id,
                ordinal=ordinal,
                text=text,
                content_hash=content_hash,
                source_hash=artifact.source_hash,
                chunk_config_hash=config.config_hash,
                locator=locator,
                created_at=timestamp,
            )
        )
    return tuple(chunks)
