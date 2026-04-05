from __future__ import annotations

from typing import Any, Dict, List


def augment_page_blocks_with_supplemental_corpus(
    page_blocks: List[Dict[str, Any]],
    supplemental_corpus: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Convert supplemental corpus chunks into pseudo page_blocks so the LLM path
    can use the same merged input without changing downstream format.
    """
    chunks = supplemental_corpus.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        return page_blocks

    augmented = list(page_blocks)
    next_idx = len(page_blocks)
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        augmented.append(
            {
                "page": 1,
                "block_id": f"supp_{next_idx}",
                "block_type": "text",
                "bbox": [0.0, 0.0, 0.0, 0.0],
                "raw_text": text,
                "extraction_method": "supplemental_pymupdf4llm",
                "source_refs": [
                    {
                        "page": 1,
                        "method": "supplemental_pymupdf4llm",
                        "chunk_id": chunk.get("chunk_id"),
                    }
                ],
            }
        )
        next_idx += 1
    return augmented
