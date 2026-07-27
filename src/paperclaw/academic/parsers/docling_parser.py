"""Optional Docling-based PDF parser for enhanced table/equation extraction."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..contracts import ParseResult


class DoclingParser:
    @property
    def fingerprint(self) -> str:
        return "docling:1"

    @property
    def supported_formats(self) -> tuple[str, ...]:
        return ("pdf",)

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
        try:
            import docling  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "DoclingParser requires the 'docling' package. "
                "Install with: pip install paperclaw[docling]"
            ) from exc
        raise NotImplementedError(
            "DoclingParser is a reserved seam for H1; "
            "full implementation pending docling API stabilization"
        )
