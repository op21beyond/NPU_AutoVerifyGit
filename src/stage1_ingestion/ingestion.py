from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

from src.common.runtime import StageRun


def _trace_id(run: StageRun, page: int, block_index: int) -> str:
    return f"{run.stage_run_id}:{page}:{block_index}"


def _confidence_text_layer(char_count: int, block_chars: int) -> float:
    """Higher confidence when the text layer is non-trivial; still capped at 1.0."""
    density = min(1.0, char_count / 1500.0)
    local = min(1.0, block_chars / 400.0) if block_chars else 0.0
    base = 0.72 + 0.13 * density + 0.15 * local
    return round(min(1.0, max(0.0, base)), 4)


def _confidence_table(char_count: int) -> float:
    if char_count <= 0:
        return 0.55
    return round(min(0.98, 0.78 + 0.2 * min(1.0, char_count / 800.0)), 4)


def _confidence_image_no_ocr() -> float:
    return 0.25


def _merge_span_text(lines: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for line in lines:
        for span in line.get("spans", []):
            t = span.get("text", "")
            if t:
                parts.append(t)
    return "\n".join(parts) if len(lines) > 1 else " ".join(parts)


def _rect_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    return inter / area_a if area_a > 0 else 0.0


def _center_inside(inner: Tuple[float, float, float, float], outer: Tuple[float, float, float, float]) -> bool:
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
    return ox0 <= cx <= ox1 and oy0 <= cy <= oy1


@dataclass
class PageMetrics:
    page: int
    char_count: int
    text_blocks: int = 0
    image_blocks: int = 0
    table_blocks: int = 0
    needs_ocr: bool = False
    ocr_reasons: List[str] = field(default_factory=list)


def _evaluate_ocr_routing(m: PageMetrics, min_chars: int, image_weight: int) -> None:
    reasons: List[str] = []
    if m.char_count < min_chars:
        reasons.append("low_text_char_count")
    if m.image_blocks > 0 and m.char_count < min_chars * 2:
        reasons.append("image_heavy_low_text")
    if m.text_blocks == 0 and (m.image_blocks > 0 or m.table_blocks > 0):
        reasons.append("no_text_layer_blocks")
    # scanned-like: almost no extractable text
    if m.char_count < 8 and m.image_blocks >= image_weight:
        reasons.append("scanned_or_bitmap_heavy")
    m.needs_ocr = len(reasons) > 0
    m.ocr_reasons = reasons


def _extract_tables(
    page: fitz.Page,
    page_number: int,
    run: StageRun,
    document_id: str,
    block_counter: int,
    table_bboxes: List[Tuple[float, float, float, float]],
) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    try:
        finder = page.find_tables()
        tables = getattr(finder, "tables", None) or []
    except (AttributeError, RuntimeError):
        return rows, block_counter

    for tab in tables:
        bbox = tuple(float(x) for x in tab.bbox)
        table_bboxes.append(bbox)
        try:
            data = tab.extract()
        except Exception:
            data = None
        if data:
            lines = ["\t".join(cell or "" for cell in row) for row in data]
            raw = "\n".join(lines)
        else:
            raw = ""
        char_count = len(raw.strip())
        bid = f"p{page_number}_b{block_counter}"
        rows.append(
            {
                "trace_id": _trace_id(run, page_number, block_counter),
                "stage_name": run.stage_name,
                "stage_run_id": run.stage_run_id,
                "document_id": document_id,
                "page": page_number,
                "block_id": bid,
                "block_type": "table",
                "bbox": list(bbox),
                "raw_text": raw,
                "extraction_method": "pymupdf_find_tables",
                "confidence_score": _confidence_table(char_count),
                "source_refs": [{"page": page_number, "bbox": list(bbox), "method": "pymupdf_find_tables"}],
            }
        )
        block_counter += 1
    return rows, block_counter


def _text_blocks_from_dict(
    page: fitz.Page,
    page_number: int,
    run: StageRun,
    document_id: str,
    block_counter: int,
    table_bboxes: List[Tuple[float, float, float, float]],
    page_char_count: List[int],
) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    td = page.get_text("dict")
    blocks = td.get("blocks") or []

    text_items: List[Tuple[Tuple[float, float, float, float], str, int]] = []
    image_items: List[Tuple[Tuple[float, float, float, float],]] = []

    for block in blocks:
        btype = block.get("type", 0)
        bbox_raw = block.get("bbox")
        if not bbox_raw or len(bbox_raw) < 4:
            continue
        bbox = tuple(float(x) for x in bbox_raw[:4])

        if btype == 0:
            lines = block.get("lines") or []
            raw = _merge_span_text(lines)
            char_count = len(raw)
            if table_bboxes and any(_center_inside(bbox, tb) and _rect_overlap(bbox, tb) > 0.35 for tb in table_bboxes):
                continue
            text_items.append((bbox, raw, char_count))
        elif btype == 1:
            image_items.append((bbox,))

    total_text_chars = sum(t[2] for t in text_items)
    page_char_count[0] = total_text_chars

    for bbox, raw, char_count in text_items:
        bid = f"p{page_number}_b{block_counter}"
        rows.append(
            {
                "trace_id": _trace_id(run, page_number, block_counter),
                "stage_name": run.stage_name,
                "stage_run_id": run.stage_run_id,
                "document_id": document_id,
                "page": page_number,
                "block_id": bid,
                "block_type": "text",
                "bbox": list(bbox),
                "raw_text": raw,
                "extraction_method": "text_layer",
                "confidence_score": _confidence_text_layer(total_text_chars, char_count),
                "source_refs": [{"page": page_number, "bbox": list(bbox), "method": "text_layer"}],
            }
        )
        block_counter += 1

    for (bbox,) in image_items:
        bid = f"p{page_number}_b{block_counter}"
        rows.append(
            {
                "trace_id": _trace_id(run, page_number, block_counter),
                "stage_name": run.stage_name,
                "stage_run_id": run.stage_run_id,
                "document_id": document_id,
                "page": page_number,
                "block_id": bid,
                "block_type": "image",
                "bbox": list(bbox),
                "raw_text": "",
                "extraction_method": "image_raster",
                "confidence_score": _confidence_image_no_ocr(),
                "source_refs": [{"page": page_number, "bbox": list(bbox), "method": "image_raster"}],
            }
        )
        block_counter += 1

    return rows, block_counter


def _maybe_equation_heuristic(text: str) -> bool:
    t = text.strip()
    if len(t) > 200:
        return False
    if re.search(r"\\\(|\\\[|\$.*\$", t):
        return True
    return bool(re.search(r"[∑∫≤≥±]", t))


def _split_equation_tags(rows: List[Dict[str, Any]]) -> None:
    """Turn obvious inline equation snippets from text blocks into block_type equation when short."""
    for row in rows:
        if row.get("block_type") != "text":
            continue
        raw = row.get("raw_text") or ""
        if _maybe_equation_heuristic(raw):
            row["block_type"] = "equation"
            row["extraction_method"] = "text_layer+heuristic_equation"
            row["source_refs"] = [
                {**(row["source_refs"][0] if row["source_refs"] else {}), "method": "text_layer+heuristic_equation"}
            ]


def try_full_page_ocr(page: fitz.Page, dpi: int = 150) -> Optional[str]:
    """Optional Tesseract full-page OCR; returns None if unavailable or on failure."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None

    try:
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        if pix.n == 4:
            mode = "RGBA"
        elif pix.n == 3:
            mode = "RGB"
        else:
            mode = "L"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        return pytesseract.image_to_string(img)
    except Exception:
        return None


def extract_page_blocks(
    pdf_path: Path,
    run: StageRun,
    *,
    min_chars_for_no_ocr: int = 40,
    run_full_page_ocr: bool = False,
) -> Tuple[List[Dict[str, Any]], List[PageMetrics], Dict[str, Any]]:
    document_id = pdf_path.stem
    all_rows: List[Dict[str, Any]] = []
    metrics_list: List[PageMetrics] = []

    doc = fitz.open(pdf_path)
    try:
        total_pages = doc.page_count
        pages_ok = 0
        for page_index in range(total_pages):
            page = doc[page_index]
            page_number = page_index + 1
            block_counter = 0
            table_bboxes: List[Tuple[float, float, float, float]] = []
            page_char_count = [0]

            table_rows, block_counter = _extract_tables(
                page, page_number, run, document_id, block_counter, table_bboxes
            )
            text_img_rows, block_counter = _text_blocks_from_dict(
                page, page_number, run, document_id, block_counter, table_bboxes, page_char_count
            )
            page_rows = table_rows + text_img_rows
            _split_equation_tags(page_rows)

            text_n = sum(1 for r in page_rows if r.get("block_type") == "text")
            img_n = sum(1 for r in page_rows if r.get("block_type") == "image")
            tbl_n = sum(1 for r in page_rows if r.get("block_type") == "table")
            eq_n = sum(1 for r in page_rows if r.get("block_type") == "equation")

            m = PageMetrics(
                page=page_number,
                char_count=page_char_count[0],
                text_blocks=text_n + eq_n,
                image_blocks=img_n,
                table_blocks=tbl_n,
            )
            _evaluate_ocr_routing(m, min_chars_for_no_ocr, image_weight=1)

            if run_full_page_ocr and m.needs_ocr:
                ocr_text = try_full_page_ocr(page)
                if ocr_text and ocr_text.strip():
                    bid = f"p{page_number}_b{block_counter}"
                    page_rows.append(
                        {
                            "trace_id": _trace_id(run, page_number, block_counter),
                            "stage_name": run.stage_name,
                            "stage_run_id": run.stage_run_id,
                            "document_id": document_id,
                            "page": page_number,
                            "block_id": bid,
                            "block_type": "text",
                            "bbox": [0.0, 0.0, float(page.rect.width), float(page.rect.height)],
                            "raw_text": ocr_text.strip(),
                            "extraction_method": "tesseract_full_page",
                            "confidence_score": round(min(0.92, 0.55 + 0.001 * len(ocr_text)), 4),
                            "source_refs": [{"page": page_number, "bbox": "full_page", "method": "tesseract_full_page"}],
                        }
                    )

            metrics_list.append(m)

            if page_rows:
                pages_ok += 1
            all_rows.extend(page_rows)

        parse_success_rate = pages_ok / total_pages if total_pages else 1.0
        summary = {
            "document_id": document_id,
            "total_pages": total_pages,
            "pages_with_blocks": pages_ok,
            "parse_success_rate": round(parse_success_rate, 4),
            "total_blocks": len(all_rows),
        }
    finally:
        doc.close()

    return all_rows, metrics_list, summary
