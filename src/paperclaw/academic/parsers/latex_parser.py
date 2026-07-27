"""Single-file LaTeX parser for the Academic runtime."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..contracts import (
    AcademicLocator,
    AcademicObject,
    ParseResult,
)

_PARSER_NAME = "latex"
_PARSER_VERSION = "1"

_SECTION_RE = re.compile(
    r"\\(?:sub)?(?:sub)?section\*?\{([^}]+)\}", re.UNICODE
)
_EQUATION_ENV_RE = re.compile(
    r"\\begin\{(equation|align|gather|multline)\*?\}(.*?)\\end\{\1\*?\}",
    re.DOTALL,
)
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_FIGURE_ENV_RE = re.compile(
    r"\\begin\{figure\}.*?\\end\{figure\}", re.DOTALL
)
_CAPTION_RE = re.compile(r"\\caption\{([^}]+)\}")
_TABLE_ENV_RE = re.compile(
    r"\\begin\{table\}.*?\\end\{table\}", re.DOTALL
)
_ALGORITHM_ENV_RE = re.compile(
    r"\\begin\{algorithm\}.*?\\end\{algorithm\}", re.DOTALL
)
_BIBITEM_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}")
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
        fingerprint = hashlib.sha256(
            f"{self.fingerprint}:{source_hash}".encode()
        ).hexdigest()
        text = content.decode("utf-8", errors="replace")
        objects: list[AcademicObject] = []
        warnings: list[str] = []
        order = 0
        doc_locator = AcademicLocator(
            paper_id, version_id, f"{version_id}:document", 1, "document", source_hash
        )
        objects.append(
            AcademicObject(doc_locator.object_id, "document", order, doc_locator)
        )

        page_number = 1
        headings: list[str] = []

        for m in _SECTION_RE.finditer(text):
            page_number = self._page_at(text, m.start())
            heading_text = m.group(1).strip()
            headings = [heading_text]
            order += 1
            object_id = f"{version_id}:{page_number}:section:{order}"
            line_no = text[:m.start()].count("\n")
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                "section",
                source_hash,
                tuple(headings),
                line_range=(line_no, line_no),
            )
            objects.append(
                AcademicObject(object_id, "section", order, locator, text=heading_text)
            )

        for m in _EQUATION_ENV_RE.finditer(text):
            page_number = self._page_at(text, m.start())
            eq_text = m.group(2).strip()
            order += 1
            object_id = f"{version_id}:{page_number}:equation:{order}"
            line_no = text[:m.start()].count("\n")
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                "equation",
                source_hash,
                tuple(headings),
                line_range=(line_no, line_no + m.group(0).count("\n")),
            )
            objects.append(
                AcademicObject(object_id, "equation", order, locator, text=eq_text)
            )

        for m in _DISPLAY_MATH_RE.finditer(text):
            page_number = self._page_at(text, m.start())
            eq_text = m.group(1).strip()
            order += 1
            object_id = f"{version_id}:{page_number}:equation:{order}"
            line_no = text[:m.start()].count("\n")
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                "equation",
                source_hash,
                tuple(headings),
                line_range=(line_no, line_no + m.group(0).count("\n")),
            )
            objects.append(
                AcademicObject(object_id, "equation", order, locator, text=eq_text)
            )

        for m in _FIGURE_ENV_RE.finditer(text):
            page_number = self._page_at(text, m.start())
            caption_m = _CAPTION_RE.search(m.group(0))
            caption_text = caption_m.group(1).strip() if caption_m else None
            order += 1
            object_id = f"{version_id}:{page_number}:figure:{order}"
            line_no = text[:m.start()].count("\n")
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                "figure",
                source_hash,
                tuple(headings),
                line_range=(line_no, line_no + m.group(0).count("\n")),
            )
            objects.append(
                AcademicObject(
                    object_id, "figure", order, locator, text=caption_text
                )
            )
            if caption_text:
                order += 1
                cap_id = f"{version_id}:{page_number}:caption:{order}"
                cap_locator = AcademicLocator(
                    paper_id,
                    version_id,
                    cap_id,
                    page_number,
                    "caption",
                    source_hash,
                    tuple(headings),
                    line_range=(line_no, line_no),
                )
                objects.append(
                    AcademicObject(
                        cap_id, "caption", order, cap_locator, text=caption_text
                    )
                )

        for m in _TABLE_ENV_RE.finditer(text):
            page_number = self._page_at(text, m.start())
            caption_m = _CAPTION_RE.search(m.group(0))
            table_text = caption_m.group(1).strip() if caption_m else m.group(0)[:200]
            order += 1
            object_id = f"{version_id}:{page_number}:table:{order}"
            line_no = text[:m.start()].count("\n")
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                "table",
                source_hash,
                tuple(headings),
                line_range=(line_no, line_no + m.group(0).count("\n")),
            )
            objects.append(
                AcademicObject(object_id, "table", order, locator, text=table_text)
            )

        for m in _ALGORITHM_ENV_RE.finditer(text):
            page_number = self._page_at(text, m.start())
            order += 1
            object_id = f"{version_id}:{page_number}:algorithm:{order}"
            line_no = text[:m.start()].count("\n")
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                "algorithm",
                source_hash,
                tuple(headings),
                line_range=(line_no, line_no + m.group(0).count("\n")),
            )
            objects.append(
                AcademicObject(
                    object_id, "algorithm", order, locator, text=m.group(0)[:500]
                )
            )

        for m in _BIBITEM_RE.finditer(text):
            page_number = self._page_at(text, m.start())
            order += 1
            object_id = f"{version_id}:{page_number}:reference:{order}"
            line_no = text[:m.start()].count("\n")
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                "reference",
                source_hash,
                tuple(headings),
                line_range=(line_no, line_no),
            )
            objects.append(
                AcademicObject(
                    object_id, "reference", order, locator, text=m.group(1)
                )
            )

        objects.sort(key=lambda o: o.reading_order)
        total_pages = max(
            1, len(_PAGE_BREAK_RE.findall(text)) + 1
        )
        return ParseResult(
            f"parse-{fingerprint}",
            paper_id,
            version_id,
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
