"""Deterministic Markdown and plain-text parsers for Phase A."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from paperclaw.retrieval.contracts import BlockLocator, ParsedBlock

_ATX_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(```+|~~~+)")


@dataclass(frozen=True)
class ParserOutput:
    parser_name: str
    parser_version: str
    blocks: tuple[ParsedBlock, ...]


class MarkdownParser:
    name = "markdown"
    version = "1"

    def parse(self, text: str, *, source_uri: str) -> ParserOutput:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        blocks: list[ParsedBlock] = []
        heading_stack: list[str] = []
        paragraph_lines: list[str] = []
        paragraph_start = 0
        paragraph_index = 0
        block_index = 0
        in_fence = False
        fence_token = ""

        def flush_paragraph(end_line: int) -> None:
            nonlocal paragraph_lines, paragraph_start, paragraph_index, block_index
            if not paragraph_lines:
                return
            content = "\n".join(paragraph_lines).strip()
            paragraph_lines = []
            if not content:
                return
            blocks.append(
                ParsedBlock(
                    kind="paragraph",
                    text=content,
                    locator=BlockLocator(
                        source_uri=source_uri,
                        start_line=paragraph_start,
                        end_line=end_line,
                        block_index=block_index,
                        block_kind="paragraph",
                        heading_path=tuple(heading_stack),
                        paragraph_index=paragraph_index,
                    ),
                )
            )
            paragraph_index += 1
            block_index += 1

        for line_number, line in enumerate(lines, start=1):
            fence_match = _FENCE.match(line)
            if fence_match:
                token = fence_match.group(1)[0]
                if not in_fence:
                    in_fence = True
                    fence_token = token
                elif token == fence_token:
                    in_fence = False
                    fence_token = ""
                if not paragraph_lines:
                    paragraph_start = line_number
                paragraph_lines.append(line.rstrip())
                continue

            heading_match = None if in_fence else _ATX_HEADING.match(line)
            if heading_match:
                flush_paragraph(line_number - 1)
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(title)
                blocks.append(
                    ParsedBlock(
                        kind="heading",
                        text=title,
                        locator=BlockLocator(
                            source_uri=source_uri,
                            start_line=line_number,
                            end_line=line_number,
                            block_index=block_index,
                            block_kind="heading",
                            heading_path=tuple(heading_stack),
                        ),
                    )
                )
                block_index += 1
                continue

            if not in_fence and not line.strip():
                flush_paragraph(line_number - 1)
                continue

            if not paragraph_lines:
                paragraph_start = line_number
            paragraph_lines.append(line.rstrip())

        flush_paragraph(len(lines))
        return ParserOutput(self.name, self.version, tuple(blocks))


class PlainTextParser:
    name = "plain_text"
    version = "1"

    def parse(self, text: str, *, source_uri: str) -> ParserOutput:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        blocks: list[ParsedBlock] = []
        paragraph_lines: list[str] = []
        paragraph_start = 0
        paragraph_index = 0

        def flush(end_line: int) -> None:
            nonlocal paragraph_lines, paragraph_start, paragraph_index
            if not paragraph_lines:
                return
            content = "\n".join(paragraph_lines).strip()
            paragraph_lines = []
            if not content:
                return
            blocks.append(
                ParsedBlock(
                    kind="paragraph",
                    text=content,
                    locator=BlockLocator(
                        source_uri=source_uri,
                        start_line=paragraph_start,
                        end_line=end_line,
                        block_index=len(blocks),
                        block_kind="paragraph",
                        paragraph_index=paragraph_index,
                    ),
                )
            )
            paragraph_index += 1

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                flush(line_number - 1)
                continue
            if not paragraph_lines:
                paragraph_start = line_number
            paragraph_lines.append(line.rstrip())
        flush(len(lines))
        return ParserOutput(self.name, self.version, tuple(blocks))


def select_parser(*, source_uri: str, media_type: str | None = None):
    """Select a deterministic Phase A parser from media type or file suffix."""

    normalized_type = (media_type or "").split(";", 1)[0].strip().lower()
    suffix = PurePosixPath(source_uri.lower()).suffix
    if normalized_type in {"text/markdown", "text/x-markdown"} or suffix in {".md", ".markdown"}:
        return MarkdownParser()
    if normalized_type in {"", "text/plain"} or suffix in {".txt", ".text"}:
        return PlainTextParser()
    raise ValueError(f"unsupported Phase A document format: {media_type or suffix or source_uri}")
