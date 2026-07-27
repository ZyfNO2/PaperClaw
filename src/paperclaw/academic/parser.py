"""Paper parser protocol and registry for the Academic runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .contracts import ParseResult


@runtime_checkable
class PaperParser(Protocol):
    @property
    def fingerprint(self) -> str: ...

    @property
    def supported_formats(self) -> tuple[str, ...]: ...

    def parse(
        self,
        content: bytes,
        format: str,
        *,
        paper_id: str,
        version_id: str,
        source_hash: str,
        asset_dir: Path,
    ) -> ParseResult: ...
