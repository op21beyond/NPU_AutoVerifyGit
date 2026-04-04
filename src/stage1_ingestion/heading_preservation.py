"""Two-phase heading/caption/body classification from font sizes (PyMuPDF spans)."""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Tuple

import fitz


def collect_font_sizes_from_document(doc: fitz.Document) -> List[float]:
    """Pass 1: gather all span font sizes from text-layer blocks across the document."""
    sizes: List[float] = []
    for pi in range(doc.page_count):
        page = doc[pi]
        td = page.get_text("dict")
        for block in td.get("blocks") or []:
            if block.get("type") != 0:
                continue
            for line in block.get("lines") or []:
                for span in line.get("spans") or []:
                    try:
                        sz = float(span.get("size", 0))
                        if sz > 0:
                            sizes.append(sz)
                    except (TypeError, ValueError):
                        continue
    return sizes


def build_size_to_role(sizes: List[float]) -> Callable[[float], str]:
    """Map font size to heading1..3, body, caption, comment."""
    rounded = [round(s * 2) / 2 for s in sizes if s > 0]
    if not rounded:
        return lambda _s: "body"
    uniq = sorted(set(rounded), reverse=True)
    labels = ["heading1", "heading2", "heading3", "body", "caption", "comment"]
    tier_to_label: Dict[float, str] = {}
    for i, u in enumerate(uniq):
        tier_to_label[u] = labels[min(i, len(labels) - 1)]

    def nearest_tier(s: float) -> float:
        rs = round(s * 2) / 2
        if rs in tier_to_label:
            return rs
        if not uniq:
            return rs
        return min(uniq, key=lambda x: abs(x - rs))

    def role(s: float) -> str:
        t = nearest_tier(s)
        return tier_to_label.get(t, "body")

    return role


def _bbox_close(a: List[float], b: Tuple[float, float, float, float], tol: float = 3.0) -> bool:
    if len(a) < 4:
        return False
    return all(abs(float(a[i]) - float(b[i])) <= tol for i in range(4))


def apply_heading_tags_to_rows(rows: List[Dict[str, Any]], doc: fitz.Document, size_to_role: Callable[[float], str]) -> None:
    """Pass 2: replace raw_text with <heading1>...</heading1> etc. per span."""
    for row in rows:
        bt = row.get("block_type")
        if bt not in ("text", "equation"):
            continue
        bbox_list = row.get("bbox")
        if not isinstance(bbox_list, list) or len(bbox_list) < 4:
            continue
        pnum = int(row.get("page", 0) or 0)
        if pnum < 1 or pnum > doc.page_count:
            continue
        page = doc[pnum - 1]
        bbox_t = (float(bbox_list[0]), float(bbox_list[1]), float(bbox_list[2]), float(bbox_list[3]))
        td = page.get_text("dict")
        parts: List[str] = []
        for block in td.get("blocks") or []:
            if block.get("type") != 0:
                continue
            br = block.get("bbox")
            if not br or len(br) < 4:
                continue
            bb = tuple(float(x) for x in br[:4])
            if not _bbox_close(list(bb), bbox_t):
                continue
            for line in block.get("lines") or []:
                for span in line.get("spans") or []:
                    t = span.get("text", "")
                    if not t:
                        continue
                    try:
                        sz = float(span.get("size", 11))
                    except (TypeError, ValueError):
                        sz = 11.0
                    role = size_to_role(sz)
                    safe = html.escape(t, quote=False)
                    parts.append(f"<{role}>{safe}</{role}>")
            break
        if parts:
            row["raw_text"] = "".join(parts)
            em = str(row.get("extraction_method") or "text_layer")
            if "+heading_preserve" not in em:
                row["extraction_method"] = em + "+heading_preserve"
            sr = row.get("source_refs") or []
            if sr and isinstance(sr[0], dict):
                sr[0] = {**sr[0], "heading_preserve": True}
