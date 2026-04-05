"""Serialize page_blocks for LLM prompts (aligned with Stage2)."""

from __future__ import annotations

from typing import Any, Dict, List


def sort_page_blocks_by_page(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _key(b: Dict[str, Any]) -> tuple:
        p = b.get("page")
        try:
            pi = int(p) if p is not None else 0
        except (TypeError, ValueError):
            pi = 0
        return (pi, str(b.get("block_id", "")), str(b.get("block_type", "")))

    return sorted(blocks, key=_key)


def serialize_page_blocks_for_prompt(
    page_blocks: List[Dict[str, Any]],
    max_total_chars: int = 100_000,
) -> str:
    chunks: List[str] = []
    used = 0
    for b in sort_page_blocks_by_page(page_blocks):
        page = b.get("page", "?")
        bid = b.get("block_id", "?")
        btype = b.get("block_type", "?")
        raw = (b.get("raw_text") or "").strip()
        if not raw:
            continue
        if used + len(raw) > max_total_chars:
            cap = max(0, max_total_chars - used)
            raw = raw[:cap] + ("\n...[truncated]" if len(raw) > cap else "")
        header = f"--- page={page} block_id={bid} type={btype} ---\n"
        piece = header + raw + "\n"
        if used + len(piece) > max_total_chars:
            break
        chunks.append(piece)
        used += len(piece)
    return "\n".join(chunks) if chunks else "(no text blocks)"
