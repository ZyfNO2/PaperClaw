"""PyMuPDF-based PDF parser — default Academic parser."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ..contracts import (
    AcademicLocator,
    AcademicObject,
    AssetReference,
    BoundingBox,
    ParseResult,
)

_PARSER_NAME = "pymupdf"
_PARSER_VERSION = "1"
_RENDER_DPI = 120


def _write_png(
    pixmap, asset_dir: Path, *, kind: Literal["page", "region"]
) -> AssetReference:
    content = pixmap.tobytes("png")
    asset_hash = hashlib.sha256(content).hexdigest()
    asset_path = asset_dir / asset_hash[:2] / f"{asset_hash}.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    if asset_path.exists():
        if (
            not asset_path.is_file()
            or hashlib.sha256(asset_path.read_bytes()).hexdigest() != asset_hash
        ):
            raise RuntimeError(f"academic asset integrity failure: {asset_hash}")
    else:
        temporary = asset_path.with_name(f".{asset_hash}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, asset_path)
            except FileExistsError:
                if hashlib.sha256(asset_path.read_bytes()).hexdigest() != asset_hash:
                    raise RuntimeError(
                        f"academic asset integrity failure: {asset_hash}"
                    )
        finally:
            temporary.unlink(missing_ok=True)
    return AssetReference(
        asset_hash,
        kind,
        width_px=pixmap.width,
        height_px=pixmap.height,
        dpi=_RENDER_DPI,
    )


def _safe_bbox(
    values: tuple[float, float, float, float], page_width: float, page_height: float
) -> BoundingBox:
    x0, y0, x1, y1 = values
    width = max(0.0, float(page_width))
    height = max(0.0, float(page_height))
    left = min(width, max(0.0, min(x0, x1)))
    right = min(width, max(left, max(x0, x1)))
    top = min(height, max(0.0, min(y0, y1)))
    bottom = min(height, max(top, max(y0, y1)))
    return BoundingBox(left, top, right, bottom)


def _appears_multi_column(
    blocks: list[tuple], page_width: float
) -> bool:
    """Conservatively detect disjoint, vertically overlapping text columns."""

    midpoint = float(page_width) / 2.0
    margin = max(12.0, float(page_width) * 0.04)
    left = [
        block
        for block in blocks
        if float(block[2]) <= midpoint + margin and str(block[4]).strip()
    ]
    right = [
        block
        for block in blocks
        if float(block[0]) >= midpoint - margin and str(block[4]).strip()
    ]
    return any(
        max(float(left_block[1]), float(right_block[1]))
        < min(float(left_block[3]), float(right_block[3]))
        for left_block in left
        for right_block in right
    )


class PyMuPDFParser:
    @property
    def fingerprint(self) -> str:
        return f"{_PARSER_NAME}:{_PARSER_VERSION}"

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
        import fitz

        fingerprint = hashlib.sha256(
            f"{self.fingerprint}:{source_hash}".encode()
        ).hexdigest()
        try:
            document = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            return ParseResult(
                f"parse-{fingerprint}",
                paper_id,
                version_id,
                source_hash,
                _PARSER_NAME,
                _PARSER_VERSION,
                fingerprint,
                "failed",
                0,
                (),
                (f"corrupt_pdf: {type(exc).__name__}: {exc}",),
            )
        if document.is_encrypted:
            document.close()
            return ParseResult(
                f"parse-{fingerprint}",
                paper_id,
                version_id,
                source_hash,
                _PARSER_NAME,
                _PARSER_VERSION,
                fingerprint,
                "failed",
                0,
                (),
                ("encrypted_pdf: cannot parse encrypted document",),
            )
        objects: list[AcademicObject] = []
        warnings: list[str] = []
        order = 0
        doc_locator = AcademicLocator(
            paper_id, version_id, f"{version_id}:document", 1, "document", source_hash
        )
        objects.append(
            AcademicObject(doc_locator.object_id, "document", order, doc_locator)
        )
        headings: list[str] = []
        scanned_pages = 0
        for page_index, page in enumerate(document):
            page_number = page_index + 1
            paragraph_index = 0
            page_assets: tuple[AssetReference, ...] = ()
            try:
                pix = page.get_pixmap(dpi=_RENDER_DPI, alpha=False)
                page_assets = (_write_png(pix, asset_dir, kind="page"),)
            except Exception as exc:
                warnings.append(
                    f"page {page_number} image unavailable: {type(exc).__name__}"
                )
            order += 1
            page_locator = AcademicLocator(
                paper_id,
                version_id,
                f"{version_id}:page:{page_number}",
                page_number,
                "page",
                source_hash,
                bounding_box=BoundingBox(0, 0, page.rect.width, page.rect.height),
            )
            objects.append(
                AcademicObject(
                    page_locator.object_id,
                    "page",
                    order,
                    page_locator,
                    assets=page_assets,
                    structured_content={
                        "coordinate_space": "pdf_points_top_left",
                        "page_width_points": float(page.rect.width),
                        "page_height_points": float(page.rect.height),
                        "render_dpi": _RENDER_DPI,
                    },
                )
            )
            blocks = page.get_text("blocks", sort=True)
            text_blocks = [b for b in blocks if str(b[4]).strip()]
            if _appears_multi_column(text_blocks, page.rect.width):
                warnings.append(
                    f"double_column_reading_order_uncertain: page {page_number}"
                )
            if not text_blocks and page.get_images():
                scanned_pages += 1
                warnings.append(
                    f"page {page_number} appears scanned (no text layer)"
                )
                continue
            for block_index, block in enumerate(blocks):
                text = str(block[4]).strip()
                if not text:
                    continue
                bbox = _safe_bbox(
                    (float(block[0]), float(block[1]), float(block[2]), float(block[3])),
                    page.rect.width,
                    page.rect.height,
                )
                is_heading = len(text) < 160 and (
                    block_index == 0 or re.match(r"^\d+(\.\d+)*\s+\S+", text)
                )
                normalized = text.lower().strip()
                object_type = "section" if is_heading else "paragraph"
                if normalized.startswith(("figure ", "fig. ", "图 ")):
                    object_type = "caption"
                elif normalized.startswith(("algorithm ", "算法 ")):
                    object_type = "algorithm"
                elif normalized.startswith(("references", "参考文献")):
                    object_type = "reference"
                elif re.search(r"[=∑∫√]|\b(?:argmin|argmax)\b", text):
                    object_type = "equation"
                if is_heading:
                    headings = [text.replace("\n", " ").strip()]
                if object_type == "paragraph":
                    paragraph_index += 1
                order += 1
                object_id = f"{version_id}:{page_number}:{block_index}:{object_type}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    page_number,
                    object_type,
                    source_hash,
                    tuple(headings),
                    bbox,
                    paragraph_index if object_type == "paragraph" else None,
                )
                region_assets: tuple[AssetReference, ...] = ()
                if object_type in {"equation", "algorithm"}:
                    try:
                        region_assets = (
                            _write_png(
                                page.get_pixmap(
                                    clip=fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                                    dpi=_RENDER_DPI,
                                    alpha=False,
                                ),
                                asset_dir,
                                kind="region",
                            ),
                        )
                    except Exception as exc:
                        warnings.append(
                            f"page {page_number} {object_type} crop unavailable: "
                            f"{type(exc).__name__}"
                        )
                objects.append(
                    AcademicObject(
                        object_id,
                        object_type,
                        order,
                        locator,
                        text=text,
                        assets=page_assets + region_assets,
                    )
                )
                for citation_index, match in enumerate(
                    re.finditer(r"(?:\[[0-9,\- ]+\]|\([A-Z][A-Za-z]+ et al\.,? \d{4}\))", text)
                ):
                    order += 1
                    citation_id = f"{object_id}:citation:{citation_index}"
                    citation_locator = AcademicLocator(
                        paper_id,
                        version_id,
                        citation_id,
                        page_number,
                        "citation",
                        source_hash,
                        tuple(headings),
                        bbox,
                    )
                    objects.append(
                        AcademicObject(
                            citation_id,
                            "citation",
                            order,
                            citation_locator,
                            text=match.group(0),
                            assets=page_assets,
                            structured_content={"parent_object_id": object_id},
                            provenance="inferred",
                        )
                    )
            for drawing_index, drawing in enumerate(page.get_drawings()):
                rect = drawing.get("rect")
                if rect is None or rect.width < 10 or rect.height < 10:
                    continue
                figure_assets: tuple[AssetReference, ...] = ()
                try:
                    figure_assets = (
                        _write_png(
                            page.get_pixmap(
                                clip=rect, dpi=_RENDER_DPI, alpha=False
                            ),
                            asset_dir,
                            kind="region",
                        ),
                    )
                except Exception as exc:
                    warnings.append(
                        f"page {page_number} drawing {drawing_index} image unavailable: "
                        f"{type(exc).__name__}"
                    )
                order += 1
                object_id = f"{version_id}:{page_number}:drawing:{drawing_index}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    page_number,
                    "figure",
                    source_hash,
                    tuple(headings),
                    _safe_bbox(
                        (rect.x0, rect.y0, rect.x1, rect.y1),
                        page.rect.width,
                        page.rect.height,
                    ),
                )
                objects.append(
                    AcademicObject(
                        object_id,
                        "figure",
                        order,
                        locator,
                        assets=page_assets + figure_assets,
                    )
                )
            try:
                tables = page.find_tables().tables
            except Exception as exc:
                tables = ()
                warnings.append(
                    f"page {page_number} table extraction unavailable: "
                    f"{type(exc).__name__}"
                )
            for table_index, table in enumerate(tables):
                bbox = table.bbox
                order += 1
                object_id = f"{version_id}:{page_number}:table:{table_index}"
                locator = AcademicLocator(
                    paper_id,
                    version_id,
                    object_id,
                    page_number,
                    "table",
                    source_hash,
                    tuple(headings),
                    _safe_bbox(
                        tuple(map(float, bbox)),
                        page.rect.width,
                        page.rect.height,
                    ),
                )
                table_text = "\n".join(
                    " | ".join(str(cell or "") for cell in row)
                    for row in table.extract()
                )
                table_assets: tuple[AssetReference, ...] = ()
                try:
                    table_assets = (
                        _write_png(
                            page.get_pixmap(
                                clip=fitz.Rect(*bbox),
                                dpi=_RENDER_DPI,
                                alpha=False,
                            ),
                            asset_dir,
                            kind="region",
                        ),
                    )
                except Exception as exc:
                    warnings.append(
                        f"page {page_number} table {table_index} crop unavailable: "
                        f"{type(exc).__name__}"
                    )
                objects.append(
                    AcademicObject(
                        object_id,
                        "table",
                        order,
                        locator,
                        text=table_text,
                        assets=page_assets + table_assets,
                        structured_content={"rows": table.extract()},
                    )
                )
                rows = table.extract()
                cells = list(table.cells)
                cell_index = 0
                for row_index, row in enumerate(rows):
                    for column_index, value in enumerate(row):
                        if cell_index >= len(cells):
                            break
                        cell_bbox = cells[cell_index]
                        cell_index += 1
                        if cell_bbox is None:
                            continue
                        order += 1
                        cell_id = (
                            f"{version_id}:{page_number}:table:{table_index}:"
                            f"cell:{row_index}:{column_index}"
                        )
                        cell_locator = AcademicLocator(
                            paper_id,
                            version_id,
                            cell_id,
                            page_number,
                            "table_cell",
                            source_hash,
                            tuple(headings),
                            _safe_bbox(
                                tuple(map(float, cell_bbox)),
                                page.rect.width,
                                page.rect.height,
                            ),
                            table_row=row_index,
                            table_column=column_index,
                        )
                        objects.append(
                            AcademicObject(
                                cell_id,
                                "table_cell",
                                order,
                                cell_locator,
                                text=str(value or ""),
                                assets=page_assets,
                                structured_content={
                                    "parent_object_id": object_id
                                },
                            )
                        )
        document.close()
        return ParseResult(
            f"parse-{fingerprint}",
            paper_id,
            version_id,
            source_hash,
            _PARSER_NAME,
            _PARSER_VERSION,
            fingerprint,
            "partial" if warnings else "ready",
            len([o for o in objects if o.object_type == "page"]),
            tuple(objects),
            tuple(warnings),
        )
