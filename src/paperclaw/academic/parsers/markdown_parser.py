"""Markdown parser for the Academic runtime."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..contracts import (
    AcademicLocator,
    AcademicObject,
    ParseResult,
)

_PARSER_NAME = "markdown"
_PARSER_VERSION = "1"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"^```[\w]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class MarkdownParser:
    @property
    def fingerprint(self) -> str:
        return f"{_PARSER_NAME}:{_PARSER_VERSION}"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("md",)

    def parse(
        self,
        content: bytes,
        format: str,
        *,
        paper_id: str,
        version_id: str,
        source_hash: str,
        asset_dir: Path,
    ) -> ParseResult:
        fingerprint = hashlib.sha256(
            f"{self.fingerprint}:{source_hash}".encode()
        ).hexdigest()
        text = content.decode("utf-8", errors="replace")
        lines = text.splitlines()
        objects: list[AcademicObject] = []
        order = 0
        doc_locator = AcademicLocator(
            paper_id, version_id, f"{version_id}:document", 1, "document", source_hash
        )
        objects.append(
            AcademicObject(doc_locator.object_id, "document", order, doc_locator)
        )
        headings: list[str] = []
        paragraph_lines: list[str] = []
        paragraph_start = 0
        in_code_fence = False
        code_lines: list[str] = []
        code_start = 0

        def flush_paragraph() -> None:
            nonlocal order, paragraph_lines, paragraph_start
            if not paragraph_lines:
                return
            body = "\n".join(paragraph_lines).strip()
            paragraph_lines = []
            if not body:
                return
            order += 1
            object_id = f"{version_id}:1:para:{order}"
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                1,
                "paragraph",
                source_hash,
                tuple(headings),
                line_range=(paragraph_start, paragraph_start + len(paragraph_lines)),
            )
            objects.append(
                AcademicObject(object_id, "paragraph", order, locator, text=body)
            )

        for line_index, line in enumerate(lines):
            if line.startswith("```"):
                if in_code_fence:
                    code_body = "\n".join(code_lines)
                    order += 1
                    object_id = f"{version_id}:1:code:{order}"
                    locator = AcademicLocator(
                        paper_id,
                        version_id,
                        object_id,
                        1,
                        "algorithm",
                        source_hash,
                        tuple(headings),
                        line_range=(code_start, line_index),
                    )
                    objects.append(
                        AcademicObject(
                            object_id, "algorithm", order, locator, text=code_body
                        )
                    )
                    code_lines = []
                    in_code_fence = False
                else:
                    flush_paragraph()
                    in_code_fence = True
                    code_start = line_index
                continue
            if in_code_fence:
                code_lines.append(line)
                continue
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                flush_paragraph()
                heading_text = heading_match.group(2).strip()
                headings = [heading_text]
                order += 1
                object_id = f"{version_id}:1:section:{order}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    1,
                    "section",
                    source_hash,
                    tuple(headings),
                    line_range=(line_index, line_index),
                )
                objects.append(
                    AcademicObject(
                        object_id, "section", order, locator, text=heading_text
                    )
                )
                continue
            image_match = _IMAGE_RE.search(line)
            if image_match and line.strip().startswith("!["):
                flush_paragraph()
                order += 1
                object_id = f"{version_id}:1:figure:{order}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    1,
                    "figure",
                    source_hash,
                    tuple(headings),
                    line_range=(line_index, line_index),
                )
                objects.append(
                    AcademicObject(
                        object_id,
                        "figure",
                        order,
                        locator,
                        text=image_match.group(1) or image_match.group(2),
                    )
                )
                continue
            if not line.strip():
                flush_paragraph()
                continue
            if not paragraph_lines:
                paragraph_start = line_index
            paragraph_lines.append(line)

        flush_paragraph()
        if in_code_fence and code_lines:
            code_body = "\n".join(code_lines)
            order += 1
            object_id = f"{version_id}:1:code:{order}"
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                1,
                "algorithm",
                source_hash,
                tuple(headings),
                line_range=(code_start, len(lines)),
            )
            objects.append(
                AcademicObject(object_id, "algorithm", order, locator, text=code_body)
            )

        return ParseResult(
            f"parse-{fingerprint}",
            paper_id,
            version_id,
            _PARSER_NAME,
            _PARSER_VERSION,
            fingerprint,
            "ready",
            1,
            tuple(objects),
            (),
        )
