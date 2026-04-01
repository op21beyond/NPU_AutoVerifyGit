from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import fitz

from src.common.runtime import StageRun

_PADDLE_OCR_CACHE: Dict[Tuple[bool, str], Any] = {}


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
    paddle_model_dir: str = "",
) -> Tuple[List[Dict[str, Any]], int, int, int]:
    rows: List[Dict[str, Any]] = []
    table_ocr_attempted = 0
    table_ocr_success = 0
    t_engine = (table_text_engine or "pymupdf").lower().strip()
    ocr_route = (table_ocr_route or "empty_only").lower().strip()
    try:
        page_height = float(page.rect.height)
        finder = page.find_tables()
        tables = getattr(finder, "tables", None) or []
    except (AttributeError, RuntimeError):
        return rows, block_counter, table_ocr_attempted, table_ocr_success

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
        method = "pymupdf_find_tables"

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
    return rows, block_counter, table_ocr_attempted, table_ocr_success


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
                "source_refs": [
                    {
                        "page": page_number,
                        "bbox": list(bbox),
                        "method": "text_layer",
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
            row["extraction_method"] = "text_layer+heuristic_equation"
            row["source_refs"] = [
                {**(row["source_refs"][0] if row["source_refs"] else {}), "method": "text_layer+heuristic_equation"}
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


def _confidence_ocr_image(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0
    # Heuristic: more characters => higher confidence, capped.
    return round(min(0.9, 0.45 + 0.005 * len(t)), 4)


def _resolve_paddle_use_gpu(paddle_device: str = "auto") -> bool:
    pref = (paddle_device or "auto").lower().strip()
    if pref == "cpu":
        return False
    try:
        import paddle
    except ImportError:
        return False
    try:
        compiled_cuda = bool(paddle.device.is_compiled_with_cuda())
        gpu_count = int(paddle.device.cuda.device_count()) if compiled_cuda else 0
        if pref == "gpu":
            return compiled_cuda and gpu_count > 0
        return compiled_cuda and gpu_count > 0
    except Exception:
        return False


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


def _get_paddle_ocr_instance(use_gpu: bool, model_root: str) -> Optional[Any]:
    key = (use_gpu, (model_root or "").strip())
    if key in _PADDLE_OCR_CACHE:
        return _PADDLE_OCR_CACHE[key]
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    kwargs: Dict[str, Any] = {
        "use_angle_cls": True,
        "lang": "en",
        "show_log": False,
        "use_gpu": use_gpu,
    }
    kwargs.update(_build_paddle_model_dirs(model_root))
    try:
        ocr = PaddleOCR(**kwargs)
    except Exception:
        return None
    _PADDLE_OCR_CACHE[key] = ocr
    return ocr


def try_ocr_image_bbox(
    page: fitz.Page,
    bbox: Tuple[float, float, float, float],
    *,
    engine: str = "tesseract",
    dpi: int = 200,
    paddle_device: str = "auto",
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
            except ImportError:
                return None
            return pytesseract.image_to_string(img)

        if eng == "paddleocr":
            try:
                import numpy as np
            except ImportError:
                return None
            use_gpu = _resolve_paddle_use_gpu(paddle_device)
            ocr = _get_paddle_ocr_instance(use_gpu, paddle_model_dir)
            if ocr is None:
                return None
            arr = np.array(img)
            result = ocr.ocr(arr, cls=True)
            lines: List[str] = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2 and line[1] and line[1][0]:
                        txt = line[1][0]
                        if txt:
                            lines.append(str(txt))
            return "\n".join(lines) if lines else None

        return None
    except Exception:
        return None


def try_extract_table_text_pdfplumber(
    pdf_path: Path,
    page_number: int,
    bbox: Tuple[float, float, float, float],
) -> Optional[str]:
    """Extract table text from a bbox using pdfplumber (optional dependency)."""
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return None
            p = pdf.pages[page_number - 1]
            x0, y0, x1, y1 = [float(v) for v in bbox]
            crop = p.crop((x0, y0, x1, y1))
            tables = crop.extract_tables()
            if not tables:
                return None
            table = tables[0] or []
            lines = ["\t".join((cell or "").strip() for cell in row) for row in table if row]
            txt = "\n".join(lines).strip()
            return txt or None
    except Exception:
        return None


def extract_pymupdf4llm_corpus(pdf_path: Path, max_chars_per_chunk: int = 6000) -> Dict[str, Any]:
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

    markdown = pymupdf4llm.to_markdown(str(pdf_path))
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
    paddle_model_dir: str = "",
    header_footer_mode: str = "none",
    header_top_ratio: float = 0.08,
    footer_bottom_ratio: float = 0.08,
    repeat_min_pages: int = 3,
    repeat_max_chars: int = 120,
) -> Tuple[List[Dict[str, Any]], List[PageMetrics], Dict[str, Any]]:
    document_id = pdf_path.stem
    all_rows: List[Dict[str, Any]] = []
    metrics_list: List[PageMetrics] = []
    image_ocr_attempted_total = 0
    image_ocr_success_total = 0
    table_ocr_attempted_total = 0
    table_ocr_success_total = 0

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

            table_rows, block_counter, table_ocr_attempted, table_ocr_success = _extract_tables(
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
                paddle_model_dir=paddle_model_dir,
            )
            table_ocr_attempted_total += table_ocr_attempted
            table_ocr_success_total += table_ocr_success
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

        parse_success_rate = pages_ok / total_pages if total_pages else 1.0
        summary = {
            "document_id": document_id,
            "total_pages": total_pages,
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
            "paddle_device": paddle_device,
            "paddle_use_gpu": _resolve_paddle_use_gpu(paddle_device)
            if (image_ocr_engine == "paddleocr" or table_text_engine == "paddleocr")
            else None,
            "paddle_model_dir": (paddle_model_dir or "").strip() or None,
        }
    finally:
        doc.close()

    return all_rows, metrics_list, summary
