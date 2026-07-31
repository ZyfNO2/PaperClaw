"""Plain text parser for the Academic runtime."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..contracts import (
    AcademicLocator,
    AcademicObject,
    ParseResult,
)

_PARSER_NAME = "plaintext"
_PARSER_VERSION = "1"
_HEADING_RE = re.compile(
    r"^(?:\d+(\.\d+)*\s+\S.*|[A-Z][A-Z\s]{3,})$", re.UNICODE
)


class TextParser:
    @property
    def fingerprint(self) -> str:
        return f"{_PARSER_NAME}:{_PARSER_VERSION}"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("txt",)

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

        def flush_paragraph() -> None:
            nonlocal order, paragraph_lines
            if not paragraph_lines:
                return
            body = "\n".join(paragraph_lines).strip()
            start = paragraph_start
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
                line_range=(start, start + len(body.splitlines())),
            )
            objects.append(
                AcademicObject(object_id, "paragraph", order, locator, text=body)
            )

        for line_index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                flush_paragraph()
                continue
            if (
                len(stripped) < 120
                and _HEADING_RE.match(stripped)
                and not paragraph_lines
            ):
                flush_paragraph()
                headings = [stripped]
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
                        object_id, "section", order, locator, text=stripped
                    )
                )
                continue
            if not paragraph_lines:
                paragraph_start = line_index
            paragraph_lines.append(line)

        flush_paragraph()
        return ParseResult(
            f"parse-{fingerprint}",
            paper_id,
            version_id,
            source_hash,
            _PARSER_NAME,
            _PARSER_VERSION,
            fingerprint,
            "ready",
            1,
            tuple(objects),
            (),
        )
