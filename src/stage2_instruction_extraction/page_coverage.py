from __future__ import annotations

from typing import Any, Dict, List

AGGREGATION_LABEL = "max_confidence_and_count_per_page"


def _pages_from_source_refs(row: Dict[str, Any]) -> List[int]:
    refs = row.get("source_refs") or []
    if not isinstance(refs, list):
        return []
    out: List[int] = []
    for ref in refs:
        if isinstance(ref, dict) and ref.get("page") is not None:
            try:
                out.append(int(ref["page"]))
            except (TypeError, ValueError):
                continue
    return out


def build_page_coverage_payload(
    catalog_rows: List[Dict[str, Any]],
    first_page: int,
    last_page: int,
    *,
    stage_run_id: str | None = None,
) -> Dict[str, Any]:
    """
    One scalar row per page in [first_page, last_page] inclusive.

    - instruction_count: number of catalog rows citing this page (same row citing twice counts once per page ref if multi-ref — we count per row per page)
    - max_confidence: max confidence_score among rows citing this page
    - binary: 1 if instruction_count > 0 else 0
    """
    if first_page > last_page or first_page < 1:
        raise ValueError("invalid page range")

    count: Dict[int, int] = {}
    max_conf: Dict[int, float] = {}

    for row in catalog_rows:
        conf = row.get("confidence_score")
        try:
            c = float(conf) if conf is not None else 0.0
        except (TypeError, ValueError):
            c = 0.0
        pages = _pages_from_source_refs(row)
        if not pages:
            continue
        seen: set[int] = set()
        for p in pages:
            if p < first_page or p > last_page:
                continue
            if p in seen:
                continue
            seen.add(p)
            count[p] = count.get(p, 0) + 1
            prev = max_conf.get(p)
            if prev is None or c > prev:
                max_conf[p] = c

    pages_out: List[Dict[str, Any]] = []
    for p in range(first_page, last_page + 1):
        ic = int(count.get(p, 0))
        mc = float(max_conf.get(p, 0.0))
        pages_out.append(
            {
                "page": p,
                "binary": 1 if ic > 0 else 0,
                "instruction_count": ic,
                "max_confidence": round(mc, 4),
            }
        )

    return {
        "schema_version": "page_coverage@1",
        "stage_run_id": stage_run_id,
        "first_page": first_page,
        "last_page": last_page,
        "aggregation": AGGREGATION_LABEL,
        "pages": pages_out,
    }


def write_page_coverage_png(
    path: str,
    payload: Dict[str, Any],
    *,
    metric: str = "max_confidence",
) -> None:
    """
    Single wide figure: one bar per page (readable at a glance; detail is for the React tool).
    metric: 'max_confidence' | 'instruction_count' | 'binary'
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import MaxNLocator
    except ImportError as e:
        raise RuntimeError(
            "matplotlib is required for page coverage PNG. Install: pip install matplotlib"
        ) from e

    pages = payload.get("pages") or []
    if not pages:
        raise ValueError("empty page_coverage payload")

    xs = [int(x["page"]) for x in pages]
    if metric == "instruction_count":
        ys = [float(x.get("instruction_count", 0)) for x in pages]
        ylabel = "Instruction count"
    elif metric == "binary":
        ys = [float(x.get("binary", 0)) for x in pages]
        ylabel = "Covered (0/1)"
    else:
        ys = [float(x.get("max_confidence", 0.0)) for x in pages]
        ylabel = "Max confidence"

    n = len(xs)
    w_in = min(48.0, max(10.0, n * 0.12))
    fig, ax = plt.subplots(figsize=(w_in, 4.5))
    ax.bar(xs, ys, width=0.85, color="#2d6cdf", edgecolor="none")
    ax.set_xlabel("Page")
    ax.set_ylabel(ylabel)
    fp = payload.get("first_page")
    lp = payload.get("last_page")
    ax.set_title(f"Instruction catalog page coverage (pages {fp}–{lp})")
    ax.set_xlim(fp - 0.5, lp + 0.5)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=8))
    if metric != "binary":
        ax.set_ylim(0, max(1.0, max(ys) * 1.05) if ys else 1.0)

    step = max(1, n // 25)
    tick_pages = list(range(fp, lp + 1, step))
    if tick_pages[-1] != lp:
        tick_pages.append(lp)
    ax.set_xticks(tick_pages)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def resolve_coverage_page_range(
    page_blocks_path: str | None,
    page_blocks_in_memory: List[Dict[str, Any]] | None,
    page_range_applied: Tuple[int, int] | None,
) -> Tuple[int, int]:
    """
    Prefer explicit CLI page range; else infer max page from page_blocks (excluding supplemental).
    """
    from pathlib import Path

    from src.common.contracts import load_jsonl
    from src.common.page_range import infer_document_total_pages_from_blocks, resolve_page_range

    if page_range_applied is not None:
        return page_range_applied[0], page_range_applied[1]

    blocks: List[Dict[str, Any]] = []
    if page_blocks_in_memory is not None:
        blocks = page_blocks_in_memory
    if not blocks and page_blocks_path:
        p = Path(page_blocks_path)
        if p.is_file():
            blocks = load_jsonl(p)

    if not blocks:
        return 1, 1
    total = infer_document_total_pages_from_blocks(blocks)
    return resolve_page_range(total, None, None)
