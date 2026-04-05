from __future__ import annotations

import importlib.metadata
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import fitz

from src.common.page_range import resolve_page_range
from src.common.runtime import StageRun
from src.stage1_ingestion.table_merge import expand_bbox_to_page_width, merge_table_bboxes
from src.stage1_ingestion.heading_preservation import (
    apply_heading_tags_to_rows,
    build_size_to_role,
    collect_font_sizes_from_document,
)
from src.stage1_ingestion.page_cross_table_merge import apply_cross_page_table_merge
from src.stage1_ingestion.text_span_scripts import merge_lines_with_span_scripts

_LOGGED_IMPORT_MODULES: Set[str] = set()
_PADDLE_OCR_CACHE: Dict[Tuple[Any, ...], Any] = {}


def _log_except(func_name: str, e: BaseException) -> None:
    print(f"[{func_name}] {type(e).__name__}: {e}", file=sys.stderr)


def _log_import_once(module: str, e: BaseException) -> None:
    if module not in _LOGGED_IMPORT_MODULES:
        _LOGGED_IMPORT_MODULES.add(module)
        _log_except(f"import:{module}", e)


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


@dataclass
class HeaderFooterFilterStats:
    mode: str
    removed_count: int = 0
    removed_text_count: int = 0
    removed_equation_count: int = 0
    removed_pages: Set[int] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "removed_count": self.removed_count,
            "removed_text_count": self.removed_text_count,
            "removed_equation_count": self.removed_equation_count,
            "removed_pages": sorted(self.removed_pages),
        }


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


def _sort_tabs_reading_order(tabs: List[Any]) -> List[Any]:
    def key(t: Any) -> Tuple[float, float]:
        bb = tuple(float(x) for x in t.bbox)
        return (bb[1], bb[0])

    return sorted(tabs, key=key)


def _concat_pymupdf_tab_extracts(tabs_sorted: List[Any]) -> str:
    parts: List[str] = []
    for tab in tabs_sorted:
        try:
            data = tab.extract()
        except Exception as e:
            _log_except("_extract_tables.tab.extract", e)
            data = None
        if data:
            lines = ["\t".join(cell or "" for cell in row) for row in data]
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _table_clip_text_fallback(page: fitz.Page, bbox: Tuple[float, float, float, float]) -> str:
    try:
        r = fitz.Rect(bbox)
        return page.get_text("text", clip=r) or ""
    except Exception as e:
        _log_except("_extract_tables.clip_text", e)
        return ""


def _extract_tables(
    pdf_path: Path,
    page: fitz.Page,
    page_number: int,
    run: StageRun,
    document_id: str,
    block_counter: int,
    table_bboxes: List[Tuple[float, float, float, float]],
    *,
    table_text_engine: str = "pymupdf",
    table_ocr_route: str = "empty_only",
    table_ocr_dpi: int = 200,
    table_ocr_min_chars: int = 8,
    paddle_device: str = "auto",
    paddle_gpu_id: int = 0,
    paddle_model_dir: str = "",
    table_merge_bypass: bool = False,
    table_merge_gap: float = 5.0,
    table_merge_horizontal: bool = False,
    table_merge_vertical_overlap: float = 0.5,
    table_merge_horizontal_overlap: float = 0.5,
    table_expand_x: bool = False,
    table_page_margin_left: float = 0.0,
    table_page_margin_right: float = 0.0,
) -> Tuple[List[Dict[str, Any]], int, int, int, int]:
    rows: List[Dict[str, Any]] = []
    table_ocr_attempted = 0
    table_ocr_success = 0
    t_engine = (table_text_engine or "pymupdf").lower().strip()
    ocr_route = (table_ocr_route or "empty_only").lower().strip()
    try:
        page_height = float(page.rect.height)
        page_width = float(page.rect.width)
        finder = page.find_tables()
        tables = getattr(finder, "tables", None) or []
    except (AttributeError, RuntimeError) as e:
        _log_except("_extract_tables.find_tables", e)
        return rows, block_counter, table_ocr_attempted, table_ocr_success, 0

    detector_raw = len(tables)
    if detector_raw == 0:
        return rows, block_counter, table_ocr_attempted, table_ocr_success, 0

    def _emit_one_row(bbox: Tuple[float, float, float, float], raw: str, method: str) -> None:
        nonlocal block_counter, table_ocr_attempted, table_ocr_success
        if t_engine == "pdflumber":
            pl_text = try_extract_table_text_pdfplumber(pdf_path, page_number, bbox)
            if pl_text and pl_text.strip():
                raw = pl_text.strip()
                method = "pdflumber_table_extract"

        if t_engine in ("tesseract", "paddleocr"):
            run_ocr = ocr_route == "always" or (ocr_route == "empty_only" and len(raw.strip()) < table_ocr_min_chars)
            if run_ocr:
                table_ocr_attempted += 1
                ocr_text = try_ocr_image_bbox(
                    page,
                    bbox,
                    engine=t_engine,
                    dpi=table_ocr_dpi,
                    paddle_device=paddle_device,
                    paddle_gpu_id=paddle_gpu_id,
                    paddle_model_dir=paddle_model_dir,
                )
                if ocr_text and ocr_text.strip() and len(ocr_text.strip()) >= table_ocr_min_chars:
                    raw = ocr_text.strip()
                    method = f"table_ocr_{t_engine}"
                    table_ocr_success += 1
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
                "extraction_method": method,
                "confidence_score": _confidence_ocr_image(raw) if method.startswith("table_ocr_") else _confidence_table(char_count),
                "source_refs": [
                    {
                        "page": page_number,
                        "bbox": list(bbox),
                        "method": method,
                        "page_height": page_height,
                    }
                ],
            }
        )
        block_counter += 1

    if table_merge_bypass:
        for tab in tables:
            bbox = tuple(float(x) for x in tab.bbox)
            if table_expand_x:
                bbox = expand_bbox_to_page_width(bbox, page_width, table_page_margin_left, table_page_margin_right)
            table_bboxes.append(bbox)
            try:
                data = tab.extract()
            except Exception as e:
                _log_except("_extract_tables.tab.extract", e)
                data = None
            if data:
                lines = ["\t".join(cell or "" for cell in row) for row in data]
                raw = "\n".join(lines)
            else:
                raw = ""
            method = "pymupdf_find_tables"
            if not raw.strip():
                raw = _table_clip_text_fallback(page, bbox)
            _emit_one_row(bbox, raw, method)
        return rows, block_counter, table_ocr_attempted, table_ocr_success, detector_raw

    bboxes = [tuple(float(x) for x in tab.bbox) for tab in tables]
    merged_bboxes, groups = merge_table_bboxes(
        bboxes,
        gap_px=table_merge_gap,
        vertical_min_width_overlap=table_merge_vertical_overlap,
        horizontal_min_height_overlap=table_merge_horizontal_overlap,
        horizontal_merge=table_merge_horizontal,
        page_width=page_width,
    )
    for mb, gidx in zip(merged_bboxes, groups):
        group_tabs = _sort_tabs_reading_order([tables[i] for i in gidx])
        bbox = mb
        if table_expand_x:
            bbox = expand_bbox_to_page_width(bbox, page_width, table_page_margin_left, table_page_margin_right)
        table_bboxes.append(bbox)
        raw = _concat_pymupdf_tab_extracts(group_tabs)
        if not raw.strip():
            raw = _table_clip_text_fallback(page, bbox)
        method = "table_merged_pymupdf" if len(gidx) > 1 else "pymupdf_find_tables"
        _emit_one_row(bbox, raw, method)
    return rows, block_counter, table_ocr_attempted, table_ocr_success, detector_raw


def _text_blocks_from_dict(
    page: fitz.Page,
    page_number: int,
    run: StageRun,
    document_id: str,
    block_counter: int,
    table_bboxes: List[Tuple[float, float, float, float]],
    page_char_count: List[int],
    *,
    text_span_script_bypass: bool = False,
    text_span_max_subsup_length: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    td = page.get_text("dict")
    page_height = float(page.rect.height)
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
            if text_span_script_bypass:
                raw = _merge_span_text(lines)
                tex_method = "text_layer"
            else:
                raw = merge_lines_with_span_scripts(lines, max_subsup_length=text_span_max_subsup_length)
                tex_method = "text_layer+span_scripts"
            char_count = len(raw)
            if table_bboxes and any(_center_inside(bbox, tb) and _rect_overlap(bbox, tb) > 0.35 for tb in table_bboxes):
                continue
            text_items.append((bbox, raw, char_count, tex_method))
        elif btype == 1:
            image_items.append((bbox,))

    total_text_chars = sum(t[2] for t in text_items)
    page_char_count[0] = total_text_chars

    for bbox, raw, char_count, tex_method in text_items:
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
                "extraction_method": tex_method,
                "confidence_score": _confidence_text_layer(total_text_chars, char_count),
                "source_refs": [
                    {
                        "page": page_number,
                        "bbox": list(bbox),
                        "method": tex_method,
                        "page_height": page_height,
                    }
                ],
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
                "source_refs": [
                    {
                        "page": page_number,
                        "bbox": list(bbox),
                        "method": "image_raster",
                        "page_height": page_height,
                    }
                ],
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
            base_m = row.get("extraction_method") or "text_layer"
            row["extraction_method"] = f"{base_m}+heuristic_equation"
            row["source_refs"] = [
                {**(row["source_refs"][0] if row["source_refs"] else {}), "method": row["extraction_method"]}
            ]


def _normalize_repeat_text(s: str) -> str:
    x = re.sub(r"\d+", "#", s.strip().lower())
    x = re.sub(r"\s+", " ", x)
    return x


def _drop_header_footer_by_position(
    rows: List[Dict[str, Any]],
    top_ratio: float,
    bottom_ratio: float,
) -> Tuple[List[Dict[str, Any]], HeaderFooterFilterStats]:
    stats = HeaderFooterFilterStats(mode="position")
    kept: List[Dict[str, Any]] = []
    tr = max(0.0, min(0.3, top_ratio))
    br = max(0.0, min(0.3, bottom_ratio))
    for row in rows:
        btype = row.get("block_type", "")
        if btype not in ("text", "equation"):
            kept.append(row)
            continue
        bbox = row.get("bbox", [])
        if not isinstance(bbox, list) or len(bbox) < 4:
            kept.append(row)
            continue
        y0 = float(bbox[1])
        y1 = float(bbox[3])
        refs = row.get("source_refs") or []
        page_h = None
        if refs and isinstance(refs[0], dict):
            page_h = refs[0].get("page_height")
        if page_h is None:
            # Fallback: no page height metadata, skip filtering for this row.
            kept.append(row)
            continue
        ph = float(page_h)
        if ph <= 0:
            kept.append(row)
            continue
        is_top = y1 <= (ph * tr)
        is_bottom = y0 >= (ph * (1.0 - br))
        if is_top or is_bottom:
            stats.removed_count += 1
            if btype == "text":
                stats.removed_text_count += 1
            elif btype == "equation":
                stats.removed_equation_count += 1
            stats.removed_pages.add(int(row.get("page", 1)))
            continue
        kept.append(row)
    return kept, stats


def _drop_header_footer_by_repetition(
    rows: List[Dict[str, Any]],
    min_repeat_pages: int,
    max_chars: int,
) -> Tuple[List[Dict[str, Any]], HeaderFooterFilterStats]:
    stats = HeaderFooterFilterStats(mode="repeat")
    min_pages = max(2, min_repeat_pages)
    max_len = max(1, max_chars)
    page_map: Dict[str, Set[int]] = {}
    for row in rows:
        btype = row.get("block_type", "")
        if btype not in ("text", "equation"):
            continue
        raw = (row.get("raw_text") or "").strip()
        if not raw or len(raw) > max_len:
            continue
        norm = _normalize_repeat_text(raw)
        if not norm:
            continue
        page = int(row.get("page", 1))
        page_map.setdefault(norm, set()).add(page)
    repeated = {k for k, pages in page_map.items() if len(pages) >= min_pages}

    kept: List[Dict[str, Any]] = []
    for row in rows:
        btype = row.get("block_type", "")
        if btype not in ("text", "equation"):
            kept.append(row)
            continue
        raw = (row.get("raw_text") or "").strip()
        norm = _normalize_repeat_text(raw)
        if raw and len(raw) <= max_len and norm in repeated:
            stats.removed_count += 1
            if btype == "text":
                stats.removed_text_count += 1
            elif btype == "equation":
                stats.removed_equation_count += 1
            stats.removed_pages.add(int(row.get("page", 1)))
            continue
        kept.append(row)
    return kept, stats


def try_full_page_ocr(page: fitz.Page, dpi: int = 150) -> Optional[str]:
    """Optional Tesseract full-page OCR; returns None if unavailable or on failure."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        _log_import_once("pytesseract", e)
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
    except Exception as e:
        _log_except("try_full_page_ocr", e)
        return None


def _confidence_ocr_image(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0
    # Heuristic: more characters => higher confidence, capped.
    return round(min(0.9, 0.45 + 0.005 * len(t)), 4)


def _paddleocr_major_version() -> Optional[int]:
    try:
        v = importlib.metadata.version("paddleocr")
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception as e:
        _log_except("_paddleocr_major_version", e)
        return None
    try:
        m = re.match(r"^(\d+)", v.strip())
        return int(m.group(1)) if m else None
    except Exception as e:
        _log_except("_paddleocr_major_version.parse", e)
        return None


def _resolve_paddle_use_gpu(paddle_device: str = "auto") -> bool:
    pref = (paddle_device or "auto").lower().strip()
    if pref == "cpu":
        return False
    try:
        import paddle
    except ImportError as e:
        _log_import_once("paddle", e)
        return False
    try:
        compiled_cuda = bool(paddle.device.is_compiled_with_cuda())
        gpu_count = int(paddle.device.cuda.device_count()) if compiled_cuda else 0
        if pref == "gpu":
            return compiled_cuda and gpu_count > 0
        return compiled_cuda and gpu_count > 0
    except Exception as e:
        _log_except("_resolve_paddle_use_gpu", e)
        return False


def _resolve_paddle_device_string(paddle_device: str, gpu_id: int) -> str:
    """PaddleOCR 3.x `device` argument: cpu, gpu, or gpu:N."""
    pref = (paddle_device or "auto").lower().strip()
    gid = max(0, int(gpu_id))
    if pref == "cpu":
        return "cpu"
    if pref == "gpu":
        return f"gpu:{gid}" if _resolve_paddle_use_gpu("gpu") else "cpu"
    if pref == "auto":
        return f"gpu:{gid}" if _resolve_paddle_use_gpu("auto") else "cpu"
    return "cpu"


def _build_paddle_model_dirs(model_root: str) -> Dict[str, str]:
    root = (model_root or "").strip()
    if not root:
        return {}
    p = Path(root)
    if not p.exists():
        return {}
    dirs: Dict[str, str] = {}
    det = p / "det"
    rec = p / "rec"
    cls = p / "cls"
    if det.is_dir():
        dirs["det_model_dir"] = str(det)
    if rec.is_dir():
        dirs["rec_model_dir"] = str(rec)
    if cls.is_dir():
        dirs["cls_model_dir"] = str(cls)
    return dirs


def _get_paddle_ocr_instance(
    paddle_device: str,
    paddle_gpu_id: int,
    model_root: str,
) -> Optional[Any]:
    try:
        from paddleocr import PaddleOCR
    except ImportError as e:
        _log_import_once("paddleocr", e)
        return None

    major = _paddleocr_major_version()
    model_key = (model_root or "").strip()
    if major is not None and major >= 3:
        dev = _resolve_paddle_device_string(paddle_device, paddle_gpu_id)
        key = ("v3", major, dev, model_key)
    else:
        use_gpu = _resolve_paddle_use_gpu(paddle_device)
        key = ("v2", major or 0, use_gpu, model_key)
    if key in _PADDLE_OCR_CACHE:
        return _PADDLE_OCR_CACHE[key]

    model_dirs = _build_paddle_model_dirs(model_root)
    kwargs: Dict[str, Any] = {"use_angle_cls": True, "lang": "en"}
    kwargs.update(model_dirs)

    if major is not None and major >= 3:
        kwargs["device"] = _resolve_paddle_device_string(paddle_device, paddle_gpu_id)
    else:
        kwargs["show_log"] = False
        kwargs["use_gpu"] = _resolve_paddle_use_gpu(paddle_device)

    try:
        ocr = PaddleOCR(**kwargs)
    except Exception as e:
        _log_except("_get_paddle_ocr_instance.PaddleOCR", e)
        return None
    _PADDLE_OCR_CACHE[key] = ocr
    return ocr


def _extract_paddleocr_text_lines(result: Any) -> List[str]:
    """Normalize PaddleOCR 2.x list output and 3.x result objects to text lines."""
    if result is None:
        return []
    lines: List[str] = []

    if isinstance(result, list) and result and isinstance(result[0], dict):
        d0 = result[0]
        for k in ("rec_texts", "texts", "text"):
            v = d0.get(k)
            if isinstance(v, list) and v:
                return [str(x) for x in v if x]

    if isinstance(result, list) and result:
        page0 = result[0]
        if isinstance(page0, list) and page0:
            first = page0[0]
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                for line in page0:
                    if not line or len(line) < 2:
                        continue
                    second = line[1]
                    if isinstance(second, (list, tuple)) and second and second[0]:
                        lines.append(str(second[0]))
                    elif isinstance(second, str) and second:
                        lines.append(second)
                if lines:
                    return [x for x in lines if str(x).strip()]

    if hasattr(result, "json") and callable(getattr(result, "json")):
        try:
            j = result.json()
            if isinstance(j, dict):
                for k in ("rec_texts", "texts", "text"):
                    v = j.get(k)
                    if isinstance(v, list):
                        return [str(x) for x in v if x]
            if isinstance(j, list):
                return _extract_paddleocr_text_lines(j)
        except Exception as e:
            _log_except("_extract_paddleocr_text_lines.json", e)

    if isinstance(result, list):
        for item in result:
            if item is None:
                continue
            if isinstance(item, dict):
                t = item.get("rec_text") or item.get("text")
                if t:
                    lines.append(str(t))
            elif hasattr(item, "rec_text"):
                rt = getattr(item, "rec_text", None)
                if rt is not None:
                    lines.append(str(rt))

    return [x for x in lines if str(x).strip()]


def _run_paddleocr_inference(ocr: Any, arr: Any) -> Any:
    try:
        return ocr.ocr(arr, cls=True)
    except Exception as e:
        _log_except("_run_paddleocr_inference.ocr", e)
        predict = getattr(ocr, "predict", None)
        if callable(predict):
            try:
                return predict(arr)
            except Exception as e2:
                _log_except("_run_paddleocr_inference.predict", e2)
        return None


def try_ocr_image_bbox(
    page: fitz.Page,
    bbox: Tuple[float, float, float, float],
    *,
    engine: str = "tesseract",
    dpi: int = 200,
    paddle_device: str = "auto",
    paddle_gpu_id: int = 0,
    paddle_model_dir: str = "",
) -> Optional[str]:
    """
    OCR text from a page region cropped by `bbox`.

    Supported engines:
    - tesseract: requires `pytesseract` available and Tesseract binary on PATH
    - paddleocr: requires `paddleocr` + dependencies
    """
    eng = (engine or "none").lower().strip()
    if not eng or eng == "none":
        return None

    try:
        rect = fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        if rect.is_empty or rect.width < 2 or rect.height < 2:
            return None

        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)

        if pix.n == 4:
            mode = "RGBA"
        elif pix.n == 3:
            mode = "RGB"
        else:
            mode = "L"

        from PIL import Image

        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        if eng == "tesseract":
            try:
                import pytesseract
            except ImportError as e:
                _log_import_once("pytesseract", e)
                return None
            return pytesseract.image_to_string(img)

        if eng == "paddleocr":
            try:
                import numpy as np
            except ImportError as e:
                _log_import_once("numpy", e)
                return None
            ocr = _get_paddle_ocr_instance(paddle_device, paddle_gpu_id, paddle_model_dir)
            if ocr is None:
                return None
            arr = np.array(img)
            result = _run_paddleocr_inference(ocr, arr)
            lines = _extract_paddleocr_text_lines(result)
            return "\n".join(lines) if lines else None

        return None
    except Exception as e:
        _log_except("try_ocr_image_bbox", e)
        return None


# Hard toggles for pdfplumber debugging / table-settings experiments (edit in source).
_PDFPLUMBER_DEBUG_DRAW_RECTS = False
_PDFPLUMBER_DEBUG_DRAW_WORDS = False
_PDFPLUMBER_USE_CUSTOM_TABLE_SETTINGS = False


def try_extract_table_text_pdfplumber(
    pdf_path: Path,
    page_number: int,
    bbox: Tuple[float, float, float, float],
) -> Optional[str]:
    """Extract table text from a bbox using pdfplumber (optional dependency)."""
    try:
        import pdfplumber
    except ImportError as e:
        _log_import_once("pdfplumber", e)
        return None
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return None
            p = pdf.pages[page_number - 1]
            x0, y0, x1, y1 = [float(v) for v in bbox]
            crop = p.crop((x0, y0, x1, y1))

            if _PDFPLUMBER_DEBUG_DRAW_RECTS or _PDFPLUMBER_DEBUG_DRAW_WORDS:
                try:
                    img = crop.to_image(resolution=150)
                    if _PDFPLUMBER_DEBUG_DRAW_RECTS:
                        rects = getattr(crop, "rects", None)
                        if rects:
                            img.draw_rects(rects)
                    if _PDFPLUMBER_DEBUG_DRAW_WORDS:
                        words = crop.extract_words()
                        if words:
                            img.draw_words(words)
                    dbg = Path(tempfile.gettempdir()) / "pdfplumber_table_debug.png"
                    img.save(str(dbg))
                except Exception as e:
                    _log_except("try_extract_table_text_pdfplumber.debug_image", e)

            if _PDFPLUMBER_USE_CUSTOM_TABLE_SETTINGS:
                tables = crop.extract_tables(
                    table_settings={
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                        "edge_min_length": 3,
                        "min_words_vertical": 1,
                        "min_words_horizontal": 1,
                        "intersection_tolerance": 3,
                    }
                )
            else:
                tables = crop.extract_tables()
            if not tables:
                return None
            table = tables[0] or []
            lines = ["\t".join((cell or "").strip() for cell in row) for row in table if row]
            txt = "\n".join(lines).strip()
            return txt or None
    except Exception as e:
        _log_except("try_extract_table_text_pdfplumber", e)
        return None


def extract_pymupdf4llm_corpus(
    pdf_path: Path,
    max_chars_per_chunk: int = 6000,
    *,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build a lightweight supplemental text corpus using pymupdf4llm.
    This is intended for Stage2 recall boost, not bbox-accurate extraction.
    """
    try:
        import pymupdf4llm  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "pymupdf4llm is required for text-backend modes that include pymupdf4llm. "
            "Install it with: pip install pymupdf4llm"
        ) from e

    first: int
    last: int
    doc = fitz.open(pdf_path)
    try:
        total = doc.page_count
        first, last = resolve_page_range(total, page_start, page_end)
        if first == 1 and last == total:
            markdown = pymupdf4llm.to_markdown(str(pdf_path))
        else:
            subset = fitz.open()
            try:
                subset.insert_pdf(doc, from_page=first - 1, to_page=last - 1)
                tmp_path = ""
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(subset.tobytes())
                    tmp_path = tmp.name
                try:
                    markdown = pymupdf4llm.to_markdown(tmp_path)
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
            finally:
                subset.close()
    finally:
        doc.close()
    if not isinstance(markdown, str):
        markdown = str(markdown)

    chunks: List[Dict[str, Any]] = []
    text = markdown.strip()
    if text:
        for i in range(0, len(text), max_chars_per_chunk):
            chunk = text[i : i + max_chars_per_chunk]
            chunks.append(
                {
                    "chunk_id": f"md_{i // max_chars_per_chunk}",
                    "text": chunk,
                    "source": "pymupdf4llm_markdown",
                }
            )

    return {
        "backend": "pymupdf4llm",
        "document_id": pdf_path.stem,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def extract_page_blocks(
    pdf_path: Path,
    run: StageRun,
    *,
    min_chars_for_no_ocr: int = 40,
    run_full_page_ocr: bool = False,
    image_ocr_engine: str = "none",
    image_ocr_route: str = "needs_ocr",
    image_ocr_dpi: int = 200,
    image_ocr_min_chars: int = 5,
    table_text_engine: str = "pymupdf",
    table_ocr_route: str = "empty_only",
    table_ocr_dpi: int = 200,
    table_ocr_min_chars: int = 8,
    paddle_device: str = "auto",
    paddle_gpu_id: int = 0,
    paddle_model_dir: str = "",
    header_footer_mode: str = "none",
    header_top_ratio: float = 0.08,
    footer_bottom_ratio: float = 0.08,
    repeat_min_pages: int = 3,
    repeat_max_chars: int = 120,
    table_merge_bypass: bool = False,
    table_merge_gap: float = 5.0,
    table_merge_horizontal: bool = False,
    table_merge_vertical_overlap: float = 0.5,
    table_merge_horizontal_overlap: float = 0.5,
    table_expand_x: bool = False,
    table_page_margin_left: float = 0.0,
    table_page_margin_right: float = 0.0,
    text_span_script_bypass: bool = False,
    text_span_max_subsup_length: int = 50,
    cross_page_table_merge: bool = True,
    cross_page_bottom_ratio: float = 0.08,
    cross_page_top_ratio: float = 0.08,
    cross_page_min_width_overlap: float = 0.5,
    preserve_heading: bool = False,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[PageMetrics], Dict[str, Any]]:
    document_id = pdf_path.stem
    all_rows: List[Dict[str, Any]] = []
    metrics_list: List[PageMetrics] = []
    image_ocr_attempted_total = 0
    image_ocr_success_total = 0
    table_ocr_attempted_total = 0
    table_ocr_success_total = 0
    table_detector_raw_total = 0
    table_output_total = 0

    doc = fitz.open(pdf_path)
    try:
        size_to_role_fn = None
        if preserve_heading:
            _sizes = collect_font_sizes_from_document(doc)
            size_to_role_fn = build_size_to_role(_sizes)

        total_pages = doc.page_count
        range_first, range_last = resolve_page_range(total_pages, page_start, page_end)
        processed_pages = range_last - range_first + 1
        pages_ok = 0
        for page_index in range(range_first - 1, range_last):
            page = doc[page_index]
            page_number = page_index + 1
            block_counter = 0
            table_bboxes: List[Tuple[float, float, float, float]] = []
            page_char_count = [0]

            table_rows, block_counter, table_ocr_attempted, table_ocr_success, table_raw_n = _extract_tables(
                pdf_path,
                page,
                page_number,
                run,
                document_id,
                block_counter,
                table_bboxes,
                table_text_engine=table_text_engine,
                table_ocr_route=table_ocr_route,
                table_ocr_dpi=table_ocr_dpi,
                table_ocr_min_chars=table_ocr_min_chars,
                paddle_device=paddle_device,
                paddle_gpu_id=paddle_gpu_id,
                paddle_model_dir=paddle_model_dir,
                table_merge_bypass=table_merge_bypass,
                table_merge_gap=table_merge_gap,
                table_merge_horizontal=table_merge_horizontal,
                table_merge_vertical_overlap=table_merge_vertical_overlap,
                table_merge_horizontal_overlap=table_merge_horizontal_overlap,
                table_expand_x=table_expand_x,
                table_page_margin_left=table_page_margin_left,
                table_page_margin_right=table_page_margin_right,
            )
            table_detector_raw_total += table_raw_n
            table_output_total += len(table_rows)
            table_ocr_attempted_total += table_ocr_attempted
            table_ocr_success_total += table_ocr_success
            text_img_rows, block_counter = _text_blocks_from_dict(
                page,
                page_number,
                run,
                document_id,
                block_counter,
                table_bboxes,
                page_char_count,
                text_span_script_bypass=text_span_script_bypass or preserve_heading,
                text_span_max_subsup_length=text_span_max_subsup_length,
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

            do_image_ocr = (image_ocr_engine or "none").lower().strip() != "none" and (
                image_ocr_route == "always" or (image_ocr_route == "needs_ocr" and m.needs_ocr)
            )
            if do_image_ocr:
                for row in page_rows:
                    if row.get("block_type") != "image":
                        continue
                    raw_text = (row.get("raw_text") or "").strip()
                    if raw_text:
                        continue
                    bbox = row.get("bbox") or []
                    if not isinstance(bbox, list) or len(bbox) < 4:
                        continue
                    image_ocr_attempted_total += 1
                    bbox_t = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                    ocr_text = try_ocr_image_bbox(
                        page,
                        bbox_t,
                        engine=image_ocr_engine,
                        dpi=image_ocr_dpi,
                        paddle_device=paddle_device,
                        paddle_gpu_id=paddle_gpu_id,
                        paddle_model_dir=paddle_model_dir,
                    )
                    if ocr_text and ocr_text.strip() and len(ocr_text.strip()) >= image_ocr_min_chars:
                        txt = ocr_text.strip()
                        row["raw_text"] = txt
                        row["block_type"] = "text"
                        row["extraction_method"] = f"image_ocr_{image_ocr_engine}"
                        row["confidence_score"] = _confidence_ocr_image(txt)
                        prev_refs = row.get("source_refs") or []
                        if prev_refs and isinstance(prev_refs[0], dict):
                            row["source_refs"] = [
                                {**prev_refs[0], "method": f"image_ocr_{image_ocr_engine}"},
                            ]
                        else:
                            row["source_refs"] = [
                                {
                                    "page": page_number,
                                    "bbox": list(bbox),
                                    "method": f"image_ocr_{image_ocr_engine}",
                                }
                            ]
                        image_ocr_success_total += 1

                # Update m's counts after block_type conversion for OCR success.
                text_n = sum(1 for r in page_rows if r.get("block_type") == "text")
                img_n = sum(1 for r in page_rows if r.get("block_type") == "image")
                tbl_n = sum(1 for r in page_rows if r.get("block_type") == "table")
                eq_n = sum(1 for r in page_rows if r.get("block_type") == "equation")
                m.text_blocks = text_n + eq_n
                m.image_blocks = img_n
                m.table_blocks = tbl_n

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
                            "source_refs": [
                                {
                                    "page": page_number,
                                    "bbox": "full_page",
                                    "method": "tesseract_full_page",
                                    "page_height": float(page.rect.height),
                                }
                            ],
                        }
                    )

            metrics_list.append(m)

            if page_rows:
                pages_ok += 1
            all_rows.extend(page_rows)

        if preserve_heading and size_to_role_fn is not None:
            apply_heading_tags_to_rows(all_rows, doc, size_to_role_fn)

        all_rows, cross_page_table_rows_removed = apply_cross_page_table_merge(
            all_rows,
            doc,
            enabled=cross_page_table_merge,
            bottom_margin_ratio=cross_page_bottom_ratio,
            top_margin_ratio=cross_page_top_ratio,
            min_width_overlap=cross_page_min_width_overlap,
        )

        filter_stats = HeaderFooterFilterStats(mode=header_footer_mode)
        if header_footer_mode == "position":
            all_rows, filter_stats = _drop_header_footer_by_position(
                all_rows,
                top_ratio=header_top_ratio,
                bottom_ratio=footer_bottom_ratio,
            )
        elif header_footer_mode == "repeat":
            all_rows, filter_stats = _drop_header_footer_by_repetition(
                all_rows,
                min_repeat_pages=repeat_min_pages,
                max_chars=repeat_max_chars,
            )

        parse_success_rate = pages_ok / processed_pages if processed_pages else 1.0
        summary = {
            "document_id": document_id,
            "total_pages": total_pages,
            "page_range_first": range_first,
            "page_range_last": range_last,
            "processed_pages": processed_pages,
            "pages_with_blocks": pages_ok,
            "parse_success_rate": round(parse_success_rate, 4),
            "total_blocks": len(all_rows),
            "header_footer_filter": filter_stats.to_dict(),
            "image_ocr_engine": image_ocr_engine,
            "image_ocr_route": image_ocr_route,
            "image_ocr_attempted": image_ocr_attempted_total,
            "image_ocr_success": image_ocr_success_total,
            "table_text_engine": table_text_engine,
            "table_ocr_route": table_ocr_route,
            "table_ocr_attempted": table_ocr_attempted_total,
            "table_ocr_success": table_ocr_success_total,
            "table_merge_enabled": not table_merge_bypass,
            "table_expand_x_enabled": table_expand_x,
            "table_detector_raw_count": table_detector_raw_total,
            "table_output_count": table_output_total,
            "table_merge_gap": table_merge_gap,
            "table_merge_horizontal": table_merge_horizontal,
            "text_span_script_enabled": not (text_span_script_bypass or preserve_heading),
            "text_span_max_subsup_length": text_span_max_subsup_length,
            "cross_page_table_merge": cross_page_table_merge,
            "cross_page_table_rows_removed": cross_page_table_rows_removed,
            "preserve_heading": preserve_heading,
            "paddle_device": paddle_device,
            "paddle_gpu_id": int(paddle_gpu_id),
            "paddle_model_dir": (paddle_model_dir or "").strip() or None,
        }
    finally:
        doc.close()

    paddle_used = image_ocr_engine == "paddleocr" or table_text_engine == "paddleocr"
    maj = _paddleocr_major_version() if paddle_used else None
    summary["paddleocr_major_version"] = maj
    if paddle_used:
        if maj is not None and maj >= 3:
            dev_res = _resolve_paddle_device_string(paddle_device, paddle_gpu_id)
            summary["paddle_device_resolved"] = dev_res
            summary["paddle_use_gpu"] = dev_res.startswith("gpu")
        else:
            summary["paddle_device_resolved"] = None
            summary["paddle_use_gpu"] = _resolve_paddle_use_gpu(paddle_device)
    else:
        summary["paddle_device_resolved"] = None
        summary["paddle_use_gpu"] = None

    return all_rows, metrics_list, summary
