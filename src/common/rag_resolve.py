"""Optional RAG path: narrow page_blocks before LLM serialization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.common.rag_index_faiss import (
    FaissRagIndex,
    filter_page_blocks_by_block_ids,
    load_block_ids_from_rag_hits,
)

# Default retrieval queries per pipeline stage (tunable for recall vs token cost).
DEFAULT_RAG_QUERIES: Dict[str, str] = {
    "stage2_instruction_extraction": (
        "NPU ISA instruction opcode mnemonic encoding execution unit architecture"
    ),
    "stage4_domain_typing": "data type format bit width quantization enum typedef",
    "stage4b_field_datatype_catalog": "field datatype mapping instruction operand encoding",
    "stage4c_field_domain_catalog": "allowed values range enum domain field constraint",
    "stage5_constraint_extract": (
        "constraint encoding rule alignment reserved invalid combination dependency"
    ),
    "stage5_ontology_values": "opcode operand field value attribute parameter",
}


def resolve_page_blocks_for_llm(
    page_blocks: List[Dict[str, Any]],
    *,
    use_rag: bool,
    rag_index_dir: Optional[Path],
    rag_top_k: int,
    rag_query: Optional[str],
    default_rag_query: str,
    embedding_model: Optional[str] = None,
    openai_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    If use_rag is False, returns page_blocks unchanged and None stats.
    If use_rag is True, loads FAISS index from rag_index_dir, retrieves top-k blocks,
    and returns only matching rows (order preserved as in page_blocks).
    Falls back to full page_blocks if index missing or retrieval empty.
    """
    if not use_rag:
        return page_blocks, None

    if not rag_index_dir:
        raise ValueError("use_rag requires rag_index_dir")

    idx_path = Path(rag_index_dir)
    if not (idx_path / "rag_manifest.json").exists():
        raise FileNotFoundError(f"RAG manifest not found under {idx_path}")

    query = (rag_query or "").strip() or default_rag_query
    index = FaissRagIndex(idx_path)
    hits = index.search(
        query,
        max(1, rag_top_k),
        embedding_model=embedding_model,
        api_key=api_key,
        base_url=openai_base_url,
    )
    block_ids = load_block_ids_from_rag_hits(hits)
    if not block_ids:
        return page_blocks, {
            "rag_applied": False,
            "rag_fallback": "empty_hits",
            "rag_query": query,
            "rag_top_k": rag_top_k,
        }

    filtered = filter_page_blocks_by_block_ids(page_blocks, block_ids)
    if not filtered:
        return page_blocks, {
            "rag_applied": False,
            "rag_fallback": "no_matching_block_ids_in_current_page_blocks",
            "rag_query": query,
            "rag_top_k": rag_top_k,
            "rag_hit_block_ids": block_ids[:20],
        }

    stats: Dict[str, Any] = {
        "rag_applied": True,
        "rag_query": query,
        "rag_top_k": rag_top_k,
        "rag_blocks_before": len(page_blocks),
        "rag_blocks_after": len(filtered),
        "rag_index_dir": str(idx_path.resolve()),
        "embedding_model": embedding_model or index.manifest.embedding_model,
    }
    return filtered, stats


def narrow_page_blocks_with_optional_rag(
    page_blocks: List[Dict[str, Any]],
    args: Any,
    *,
    default_rag_query: str,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    If args.use_rag is set, run FAISS retrieval; otherwise return page_blocks and None.
    On retrieval failure, falls back to full blocks and returns error stats.
    """
    from src.common.rag_cli import rag_index_dir_from_args

    rag_dir = rag_index_dir_from_args(args)
    if not rag_dir:
        return page_blocks, None
    try:
        return resolve_page_blocks_for_llm(
            page_blocks,
            use_rag=True,
            rag_index_dir=rag_dir,
            rag_top_k=int(getattr(args, "rag_top_k", 48)),
            rag_query=getattr(args, "rag_query", None),
            default_rag_query=default_rag_query,
            embedding_model=getattr(args, "rag_embedding_model", None),
            openai_base_url=getattr(args, "openai_base_url", None),
        )
    except Exception as ex:
        return page_blocks, {"rag_applied": False, "rag_error": str(ex)}
