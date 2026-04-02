"""Tag superscript/subscript spans in PyMuPDF text dict lines using flags + geometry heuristics."""

from __future__ import annotations

import html
from typing import Any, Dict, List

import fitz

# PyMuPDF exposes superscript; subscript often has no separate flag — use heuristics.
_TEXT_FONT_SUPERSCRIPT = int(getattr(fitz, "TEXT_FONT_SUPERSCRIPT", 1))


def merge_lines_with_span_scripts(lines: List[Dict[str, Any]]) -> str:
    """
    Build block text from dict lines, wrapping <sup>/<sub> around detected script spans.
    Lines are joined with newlines.
    """
    if not lines:
        return ""
    out: List[str] = []
    for line in lines:
        out.append(_line_to_tagged_text(line))
    return "\n".join(out)


def _line_to_tagged_text(line: Dict[str, Any]) -> str:
    spans_in = line.get("spans") or []
    spans: List[Dict[str, Any]] = [s for s in spans_in if s.get("text") is not None and str(s.get("text", "")) != ""]
    if not spans:
        return ""
    spans.sort(key=lambda s: float((s.get("bbox") or [0, 0, 0, 0])[0]))

    sizes: List[float] = []
    for s in spans:
        try:
            sizes.append(float(s.get("size", 0)))
        except (TypeError, ValueError):
            sizes.append(0.0)
    ref_size = max(sizes) if sizes else 12.0
    if ref_size <= 0:
        ref_size = 12.0

    body_cys: List[float] = []
    for s in spans:
        sz = float(s.get("size", 0) or 0)
        bbox = s.get("bbox") or [0, 0, 0, 0]
        if len(bbox) < 4:
            continue
        y0, y1 = float(bbox[1]), float(bbox[3])
        cy = (y0 + y1) / 2
        if sz >= ref_size * 0.91:
            body_cys.append(cy)
    if body_cys:
        body_cy = sum(body_cys) / len(body_cys)
    else:
        ys: List[float] = []
        for s in spans:
            bbox = s.get("bbox") or [0, 0, 0, 0]
            if len(bbox) < 4:
                continue
            y0, y1 = float(bbox[1]), float(bbox[3])
            ys.append((y0 + y1) / 2)
        body_cy = sum(ys) / len(ys) if ys else 0.0

    parts: List[str] = []
    for s in spans:
        raw_t = str(s.get("text", ""))
        if not raw_t:
            continue
        safe = html.escape(raw_t, quote=False)
        role = _classify_span(s, ref_size, body_cy)
        if role == "sup":
            parts.append(f"<sup>{safe}</sup>")
        elif role == "sub":
            parts.append(f"<sub>{safe}</sub>")
        else:
            parts.append(safe)
    return "".join(parts)


def _classify_span(span: Dict[str, Any], ref_size: float, body_cy: float) -> str:
    try:
        flags = int(span.get("flags", 0))
    except (TypeError, ValueError):
        flags = 0
    if flags & _TEXT_FONT_SUPERSCRIPT:
        return "sup"

    try:
        size = float(span.get("size", 0) or 0)
    except (TypeError, ValueError):
        size = 0.0
    bbox = span.get("bbox") or [0, 0, 0, 0]
    if len(bbox) < 4:
        return "normal"
    y0, y1 = float(bbox[1]), float(bbox[3])
    cy = (y0 + y1) / 2

    if ref_size <= 0:
        return "normal"
    if size >= ref_size * 0.92:
        return "normal"

    thresh = 0.2 * ref_size
    if cy < body_cy - thresh * 0.35:
        return "sup"
    if cy > body_cy + thresh * 0.25:
        return "sub"
    return "normal"
