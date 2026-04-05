from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def resolve_page_range(
    total_pages: int,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> Tuple[int, int]:
    """
    1-based inclusive (first_page, last_page).

    - Neither arg: full document [1, total_pages].
    - Start only: [page_start, total_pages].
    - End only: [1, page_end].
    - Both: inclusive range, clamped to [1, total_pages].
    """
    if total_pages < 1:
        raise ValueError("total_pages must be >= 1")
    if page_start is None and page_end is None:
        first, last = 1, total_pages
    elif page_start is None:
        first, last = 1, int(page_end)
    elif page_end is None:
        first, last = int(page_start), total_pages
    else:
        first, last = int(page_start), int(page_end)
    first = max(1, min(first, total_pages))
    last = max(1, min(last, total_pages))
    if first > last:
        raise ValueError(
            f"Invalid page range: resolved {first}-{last} for a document with {total_pages} page(s)"
        )
    return first, last


def infer_document_total_pages_from_blocks(page_blocks: List[Dict[str, Any]]) -> int:
    """Best-effort max page from page_blocks; ignores supplemental pseudo-blocks when possible."""
    best = 0
    for b in page_blocks:
        if b.get("extraction_method") == "supplemental_pymupdf4llm":
            continue
        p = b.get("page")
        if isinstance(p, int) and p >= 1:
            best = max(best, p)
    if best == 0:
        for b in page_blocks:
            p = b.get("page")
            if isinstance(p, int) and p >= 1:
                best = max(best, p)
    return max(best, 1)


def filter_page_blocks_by_page_range(
    page_blocks: List[Dict[str, Any]],
    first_page: int,
    last_page: int,
) -> List[Dict[str, Any]]:
    """Keep blocks whose `page` is in [first_page, last_page] (1-based inclusive)."""
    out: List[Dict[str, Any]] = []
    for b in page_blocks:
        p = b.get("page")
        if p is None:
            continue
        if not isinstance(p, int):
            try:
                p = int(p)
            except (TypeError, ValueError):
                continue
        if first_page <= p <= last_page:
            out.append(b)
    return out
