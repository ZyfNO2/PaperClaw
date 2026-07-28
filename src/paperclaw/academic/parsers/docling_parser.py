"""Optional Docling PDF adapter normalized to canonical academic objects."""

from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path
from typing import Any

from ..contracts import (
    AcademicLocator,
    AcademicObject,
    AssetReference,
    BoundingBox,
    ParseResult,
)
from .pymupdf_parser import PyMuPDFParser, _RENDER_DPI, _write_png

_LABEL_TYPES = {
    "title": "section",
    "section_header": "section",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list_item": "paragraph",
    "reference": "reference",
    "caption": "caption",
    "formula": "equation",
    "picture": "figure",
    "table": "table",
    "code": "algorithm",
}


class DoclingParser:
    @property
    def fingerprint(self) -> str:
        return "docling:2"

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
            from docling.datamodel.base_models import DocumentStream
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ImportError(
                "DoclingParser requires the 'docling' package. "
                "Install with: pip install paperclaw[docling]"
            ) from exc

        base = PyMuPDFParser().parse(
            content,
            format,
            paper_id=paper_id,
            version_id=version_id,
            source_hash=source_hash,
            asset_dir=asset_dir,
        )
        fingerprint = hashlib.sha256(
            f"{self.fingerprint}:{source_hash}".encode()
        ).hexdigest()
        if base.status == "failed":
            return ParseResult(
                f"parse-{fingerprint}",
                paper_id,
                version_id,
                source_hash,
                "docling",
                "2",
                fingerprint,
                "failed",
                base.page_count,
                (),
                base.warnings,
            )

        try:
            source = DocumentStream(name="paper.pdf", stream=BytesIO(content))
            converted = DocumentConverter().convert(source)
            document = converted.document
        except Exception as exc:
            warnings = base.warnings + (
                f"docling conversion failed: {type(exc).__name__}",
            )
            return ParseResult(
                f"parse-{fingerprint}",
                paper_id,
                version_id,
                source_hash,
                "docling",
                "2",
                fingerprint,
                "partial",
                base.page_count,
                base.objects,
                warnings,
            )

        objects = [
            item for item in base.objects if item.object_type in {"document", "page"}
        ]
        page_assets = {
            item.locator.page_number: item.assets
            for item in objects
            if item.object_type == "page"
        }
        headings: list[str] = []
        warnings = list(base.warnings)
        order = max((item.reading_order for item in objects), default=0)

        pdf_document: Any | None = None
        try:
            import fitz

            pdf_document = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            warnings.append(f"docling region crops unavailable: {type(exc).__name__}")

        for item, _level in document.iterate_items():
            label = str(getattr(item, "label", "")).lower().split(".")[-1]
            object_type = _LABEL_TYPES.get(label)
            if object_type is None:
                continue
            text = self._item_text(item)
            provenance = tuple(getattr(item, "prov", ()) or ())
            if not provenance:
                warnings.append(f"docling {label} item has no page provenance")
                continue
            prov = provenance[0]
            page_number = int(getattr(prov, "page_no", 0))
            bbox = self._bbox(document, prov, page_number)
            if page_number < 1 or bbox is None:
                warnings.append(f"docling {label} item has invalid coordinates")
                continue
            if object_type == "section":
                headings = [text] if text else headings
            order += 1
            object_id = f"{version_id}:{page_number}:{object_type}:{order}"
            locator = AcademicLocator(
                paper_id,
                version_id,
                object_id,
                page_number,
                object_type,
                source_hash,
                tuple(headings),
                bbox,
            )
            assets: tuple[AssetReference, ...] = page_assets.get(page_number, ())
            if (
                pdf_document is not None
                and object_type in {"figure", "table", "equation", "algorithm"}
            ):
                try:
                    page = pdf_document[page_number - 1]
                    clip = page.get_pixmap(
                        clip=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                        dpi=_RENDER_DPI,
                        alpha=False,
                    )
                    assets += (_write_png(clip, asset_dir, kind="region"),)
                except Exception as exc:
                    warnings.append(
                        f"docling {object_type} crop unavailable: {type(exc).__name__}"
                    )
            structured: dict[str, object] = {"docling_label": label}
            if object_type == "table":
                structured.update(self._table_content(item))
            objects.append(
                AcademicObject(
                    object_id,
                    object_type,
                    order,
                    locator,
                    text=text,
                    assets=assets,
                    structured_content=structured,
                )
            )
        if pdf_document is not None:
            pdf_document.close()
        if len(objects) == sum(
            item.object_type in {"document", "page"} for item in objects
        ):
            warnings.append("docling produced no supported academic objects")
        return ParseResult(
            f"parse-{fingerprint}",
            paper_id,
            version_id,
            source_hash,
            "docling",
            "2",
            fingerprint,
            "partial" if warnings else "ready",
            base.page_count,
            tuple(objects),
            tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _item_text(item: object) -> str | None:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            return text.strip() or None
        export = getattr(item, "export_to_markdown", None)
        if callable(export):
            value = export()
            if isinstance(value, str):
                return value.strip() or None
        return None

    @staticmethod
    def _bbox(document: object, prov: object, page_number: int) -> BoundingBox | None:
        try:
            pages = getattr(document, "pages")
            page = pages[page_number]
            height = float(page.size.height)
            raw = prov.bbox.to_top_left_origin(page_height=height)
            return BoundingBox(
                float(raw.l),
                float(raw.t),
                float(raw.r),
                float(raw.b),
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _table_content(item: object) -> dict[str, object]:
        export = getattr(item, "export_to_dataframe", None)
        if not callable(export):
            return {}
        try:
            frame = export()
            return {
                "columns": [str(value) for value in frame.columns],
                "rows": [
                    [None if value is None else str(value) for value in row]
                    for row in frame.itertuples(index=False, name=None)
                ],
            }
        except Exception:
            return {}
