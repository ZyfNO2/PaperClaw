"""Single-file LaTeX parser normalized to canonical academic objects."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..contracts import AcademicLocator, AcademicObject, ParseResult

_PARSER_NAME = "latex"
_PARSER_VERSION = "2"
_SECTION_RE = re.compile(
    r"\\(section|subsection|subsubsection)\*?\{([^}]+)\}", re.UNICODE
)
_EQUATION_ENV_RE = re.compile(
    r"\\begin\{(equation|align|gather|multline)\*?\}(.*?)\\end\{\1\*?\}",
    re.DOTALL,
)
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_FIGURE_ENV_RE = re.compile(r"\\begin\{figure\}.*?\\end\{figure\}", re.DOTALL)
_CAPTION_RE = re.compile(r"\\caption\{([^}]+)\}")
_TABLE_ENV_RE = re.compile(r"\\begin\{table\}.*?\\end\{table\}", re.DOTALL)
_ALGORITHM_ENV_RE = re.compile(
    r"\\begin\{algorithm\}.*?\\end\{algorithm\}", re.DOTALL
)
_BIBITEM_RE = re.compile(
    r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}\s*([^\r\n]*)",
)
_CITE_RE = re.compile(r"\\cite(?:t|p|author|year)?\{([^}]+)\}")
_PAGE_BREAK_RE = re.compile(r"\\(?:newpage|clearpage|pagebreak)")


class LatexParser:
    @property
    def fingerprint(self) -> str:
        return f"{_PARSER_NAME}:{_PARSER_VERSION}"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("tex",)

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
        del format, asset_dir
        fingerprint = hashlib.sha256(
            f"{self.fingerprint}:{source_hash}".encode()
        ).hexdigest()
        text = content.decode("utf-8", errors="replace")
        warnings: list[str] = []
        if "\ufffd" in text:
            warnings.append("latex source contained invalid UTF-8 replacement characters")

        objects: list[AcademicObject] = []
        document_locator = AcademicLocator(
            paper_id,
            version_id,
            f"{version_id}:document",
            1,
            "document",
            source_hash,
        )
        objects.append(
            AcademicObject(
                document_locator.object_id,
                "document",
                0,
                document_locator,
            )
        )

        events: list[dict[str, Any]] = []
        event_serial = 0

        def add_event(
            match: re.Match[str],
            object_type: str,
            body: str | None,
            *,
            priority: int = 10,
            structured: dict[str, object] | None = None,
        ) -> int:
            nonlocal event_serial
            event_serial += 1
            events.append(
                {
                    "serial": event_serial,
                    "start": match.start(),
                    "end": match.end(),
                    "priority": priority,
                    "type": object_type,
                    "text": body,
                    "structured": structured or {},
                }
            )
            return event_serial

        for match in _SECTION_RE.finditer(text):
            add_event(
                match,
                "section",
                match.group(2).strip(),
                priority=0,
                structured={
                    "section_level": {
                        "section": 1,
                        "subsection": 2,
                        "subsubsection": 3,
                    }[match.group(1)]
                },
            )

        equation_ranges: list[tuple[int, int]] = []
        for match in _EQUATION_ENV_RE.finditer(text):
            equation_ranges.append((match.start(), match.end()))
            add_event(
                match,
                "equation",
                match.group(2).strip(),
                structured={"environment": match.group(1)},
            )
        for match in _DISPLAY_MATH_RE.finditer(text):
            if any(start <= match.start() < end for start, end in equation_ranges):
                continue
            add_event(match, "equation", match.group(1).strip())

        for match in _FIGURE_ENV_RE.finditer(text):
            caption = _CAPTION_RE.search(match.group(0))
            caption_text = caption.group(1).strip() if caption else None
            parent_serial = add_event(match, "figure", caption_text)
            if caption is not None:
                event_serial += 1
                events.append(
                    {
                        "serial": event_serial,
                        "start": match.start() + caption.start(),
                        "end": match.start() + caption.end(),
                        "priority": 11,
                        "type": "caption",
                        "text": caption_text,
                        "structured": {"parent_serial": parent_serial},
                    }
                )

        for match in _TABLE_ENV_RE.finditer(text):
            caption = _CAPTION_RE.search(match.group(0))
            caption_text = caption.group(1).strip() if caption else None
            parent_serial = add_event(
                match,
                "table",
                caption_text or match.group(0)[:500],
            )
            if caption is not None:
                event_serial += 1
                events.append(
                    {
                        "serial": event_serial,
                        "start": match.start() + caption.start(),
                        "end": match.start() + caption.end(),
                        "priority": 11,
                        "type": "caption",
                        "text": caption_text,
                        "structured": {"parent_serial": parent_serial},
                    }
                )

        for match in _ALGORITHM_ENV_RE.finditer(text):
            add_event(match, "algorithm", match.group(0)[:2000])
        for match in _BIBITEM_RE.finditer(text):
            add_event(
                match,
                "reference",
                (match.group(1) + " " + match.group(2).strip()).strip(),
                structured={"citation_key": match.group(1)},
            )
        for match in _CITE_RE.finditer(text):
            add_event(
                match,
                "citation",
                match.group(0),
                structured={
                    "citation_keys": [
                        key.strip() for key in match.group(1).split(",") if key.strip()
                    ]
                },
            )

        events.sort(key=lambda item: (item["start"], item["priority"], item["serial"]))
        headings: list[str] = []
        object_ids_by_serial: dict[int, str] = {}
        for order, event in enumerate(events, start=1):
            if event["type"] == "section":
                level = int(event["structured"]["section_level"])
                headings = headings[: level - 1]
                headings.append(str(event["text"]))
            page_number = self._page_at(text, int(event["start"]))
            object_id = (
                f"{version_id}:{page_number}:{event['type']}:{order}"
            )
            object_ids_by_serial[int(event["serial"])] = object_id
            line_start = text[: int(event["start"])].count("\n")
            line_end = line_start + text[
                int(event["start"]) : int(event["end"])
            ].count("\n")
            structured = dict(event["structured"])
            parent_serial = structured.pop("parent_serial", None)
            if isinstance(parent_serial, int):
                parent_id = object_ids_by_serial.get(parent_serial)
                if parent_id is not None:
                    structured["parent_object_id"] = parent_id
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                event["type"],
                source_hash,
                tuple(headings),
                line_range=(line_start, line_end),
            )
            objects.append(
                AcademicObject(
                    object_id,
                    event["type"],
                    order,
                    locator,
                    text=event["text"],
                    structured_content=structured,
                    provenance="inferred",
                )
            )

        total_pages = max(1, len(_PAGE_BREAK_RE.findall(text)) + 1)
        return ParseResult(
            f"parse-{fingerprint}",
            paper_id,
            version_id,
            source_hash,
            _PARSER_NAME,
            _PARSER_VERSION,
            fingerprint,
            "partial" if warnings else "ready",
            total_pages,
            tuple(objects),
            tuple(warnings),
        )

    @staticmethod
    def _page_at(text: str, pos: int) -> int:
        return len(_PAGE_BREAK_RE.findall(text[:pos])) + 1
