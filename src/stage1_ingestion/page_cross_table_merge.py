"""Merge table blocks that continue across consecutive PDF pages (bottom-of-page + top-of-next)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import fitz

from src.stage1_ingestion.table_merge import _width_overlap_ratio

_EDGE_EPS_PT = 2.0


def _page_y_extrema(rows: List[Dict[str, Any]], page_num: int) -> Tuple[float, float]:
    """Min y0 and max y1 among all blocks on page (any type with bbox)."""
    y0s: List[float] = []
    y1s: List[float] = []
    for r in rows:
        if int(r.get("page", 0) or 0) != page_num:
            continue
        bb = r.get("bbox")
        if not isinstance(bb, list) or len(bb) < 4:
            continue
        y0s.append(float(bb[1]))
        y1s.append(float(bb[3]))
    if not y0s:
        return 0.0, 0.0
    return min(y0s), max(y1s)


def _one_pass_cross_page_merge(
    rows: List[Dict[str, Any]],
    doc: fitz.Document,
    *,
    bottom_margin_ratio: float,
    top_margin_ratio: float,
    min_width_overlap: float,
) -> Tuple[List[Dict[str, Any]], int]:
    table_rows = [r for r in rows if r.get("block_type") == "table"]
    if not table_rows:
        return rows, 0

    by_page: Dict[int, List[Dict[str, Any]]] = {}
    for r in table_rows:
        p = int(r.get("page", 0) or 0)
        by_page.setdefault(p, []).append(r)

    for p in by_page:
        by_page[p].sort(
            key=lambda x: (float((x.get("bbox") or [0, 0, 0, 0])[1]), float((x.get("bbox") or [0, 0, 0, 0])[0]))
        )

    pages_sorted = sorted(by_page.keys())
    to_remove: set[str] = set()

    for idx in range(len(pages_sorted) - 1):
        p = pages_sorted[idx]
        p2 = pages_sorted[idx + 1]
        if p2 != p + 1:
            continue
        t1 = [r for r in by_page[p] if str(r.get("block_id")) not in to_remove]
        t2 = [r for r in by_page[p2] if str(r.get("block_id")) not in to_remove]
        if not t1 or not t2:
            continue
        bottom_r = max(t1, key=lambda r: float((r.get("bbox") or [0, 0, 0, 0])[3]))
        top_r = min(t2, key=lambda r: float((r.get("bbox") or [0, 0, 0, 0])[1]))
        if str(bottom_r.get("block_id")) in to_remove or str(top_r.get("block_id")) in to_remove:
            continue

        if p < 1 or p > doc.page_count:
            continue
        ph = float(doc[p - 1].rect.height)
        ph2 = float(doc[p].rect.height)
        if ph <= 0 or ph2 <= 0:
            continue

        bb = bottom_r.get("bbox") or [0, 0, 0, 0]
        bt = top_r.get("bbox") or [0, 0, 0, 0]
        if len(bb) < 4 or len(bt) < 4:
            continue
        bx0, by0, bx1, by1 = (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
        tx0, ty0, tx1, ty1 = (float(bt[0]), float(bt[1]), float(bt[2]), float(bt[3]))

        br = max(0.0, min(0.25, bottom_margin_ratio))
        tr = max(0.0, min(0.25, top_margin_ratio))
        if by1 < ph * (1.0 - br):
            continue
        if ty0 > ph2 * tr:
            continue

        b_tup = (bx0, by0, bx1, by1)
        t_tup = (tx0, ty0, tx1, ty1)
        if _width_overlap_ratio(b_tup, t_tup) < min_width_overlap:
            continue

        min_y_p, max_y_p = _page_y_extrema(rows, p)
        min_y_p2, max_y_p2 = _page_y_extrema(rows, p2)
        # Bottom table must be the bottom-most block on page p; top table the top-most on p+1.
        if abs(by1 - max_y_p) > _EDGE_EPS_PT:
            continue
        if abs(ty0 - min_y_p2) > _EDGE_EPS_PT:
            continue

        merged_text = ((bottom_r.get("raw_text") or "").rstrip() + "\n\n" + (top_r.get("raw_text") or "").lstrip()).strip()
        mp = bottom_r.get("multi_page_bboxes")
        if isinstance(mp, list) and mp:
            chain = list(mp)
        else:
            chain = [{"page": p, "bbox": list(bb)}]
        chain.append({"page": p2, "bbox": list(bt)})
        bottom_r["raw_text"] = merged_text
        bottom_r["multi_page_bboxes"] = chain
        em = str(bottom_r.get("extraction_method") or "table")
        if "+cross_page_merge" not in em:
            bottom_r["extraction_method"] = em + "+cross_page_merge"
        bottom_r["cross_page_continuation"] = True
        sr = bottom_r.get("source_refs") or []
        if sr and isinstance(sr[0], dict):
            sr[0] = {**sr[0], "cross_page_merge_to": p2}
        to_remove.add(str(top_r.get("block_id")))

    if not to_remove:
        return rows, 0

    out: List[Dict[str, Any]] = []
    for r in rows:
        bid = str(r.get("block_id", ""))
        if bid in to_remove:
            continue
        out.append(r)
    return out, len(to_remove)


def apply_cross_page_table_merge(
    rows: List[Dict[str, Any]],
    doc: fitz.Document,
    *,
    enabled: bool = True,
    bottom_margin_ratio: float = 0.08,
    top_margin_ratio: float = 0.08,
    min_width_overlap: float = 0.5,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Repeatedly merge bottom-of-page / top-of-next tables until stable (supports 3+ pages).
    Returns (new_rows, total_removed_row_count).
    """
    if not enabled or len(rows) < 2:
        return rows, 0
    total_removed = 0
    cur = rows
    while True:
        cur, n = _one_pass_cross_page_merge(
            cur,
            doc,
            bottom_margin_ratio=bottom_margin_ratio,
            top_margin_ratio=top_margin_ratio,
            min_width_overlap=min_width_overlap,
        )
        total_removed += n
        if n == 0:
            break
    return cur, total_removed
