"""Optional LightRAG path: index page_blocks and narrow via vector/KB retrieval (Stage 5).

Uses HKUDS LightRAG (https://github.com/hkuds/lightrag): insert per-block documents, then
aquery_data (no LLM answer) to collect chunk file_path → block_id mapping.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.common.lightrag_cli import lightrag_working_dir_from_args
from src.common.llm_page_blocks import sort_page_blocks_by_page
from src.common.rag_index_faiss import filter_page_blocks_by_block_ids


def _single_block_document_text(b: Dict[str, Any]) -> str:
    page = b.get("page", "?")
    bid = b.get("block_id", "?")
    btype = b.get("block_type", "?")
    raw = (b.get("raw_text") or "").strip()
    header = f"--- page={page} block_id={bid} type={btype} ---\n"
    return header + raw if raw else ""


def _lightrag_index_ready(working_dir: Path) -> bool:
    """Heuristic: vector chunk store exists after a successful insert."""
    return (working_dir / "vdb_chunks.json").exists() or (working_dir / "kv_store_full_docs.json").exists()


async def _narrow_async(
    page_blocks: List[Dict[str, Any]],
    *,
    working_dir: Path,
    rebuild: bool,
    query: str,
    query_mode: str,
    top_k: int,
    llm_model_name: str,
    embedding_model: str,
    openai_base_url: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        from lightrag import LightRAG, QueryParam
        from lightrag.llm.openai import openai_complete, openai_embed
    except ImportError as ex:
        raise ImportError(
            "lightrag-hku is not installed. Run: pip install lightrag-hku"
        ) from ex

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for LightRAG indexing and query")

    docs: List[str] = []
    ids: List[str] = []
    file_paths: List[str] = []
    for b in sort_page_blocks_by_page(page_blocks):
        text = _single_block_document_text(b)
        if not text.strip():
            continue
        bid = str(b.get("block_id", "")).strip() or f"anon-{len(ids)}"
        docs.append(text)
        ids.append(bid)
        file_paths.append(bid)

    if not docs:
        return page_blocks, {
            "lightrag_applied": False,
            "lightrag_fallback": "no_text_blocks",
            "lightrag_query": query,
        }

    working_dir = Path(working_dir)
    if rebuild and working_dir.exists():
        shutil.rmtree(working_dir)
    working_dir.mkdir(parents=True, exist_ok=True)

    prev_base = os.environ.get("OPENAI_BASE_URL")
    if openai_base_url:
        os.environ["OPENAI_BASE_URL"] = openai_base_url.strip()

    rag: Any = None
    try:
        rag = LightRAG(
            working_dir=str(working_dir),
            embedding_func=openai_embed,
            llm_model_func=openai_complete,
            llm_model_name=llm_model_name,
        )
        await rag.initialize_storages()

        need_insert = rebuild or not _lightrag_index_ready(working_dir)

        if need_insert:
            await rag.ainsert(docs, ids=ids, file_paths=file_paths)

        qp = QueryParam(
            mode=query_mode,  # type: ignore[arg-type]
            chunk_top_k=max(1, top_k),
            top_k=max(1, top_k),
            enable_rerank=False,
        )
        raw = await rag.aquery_data(query.strip(), param=qp)

        if not isinstance(raw, dict) or raw.get("status") != "success":
            msg = (raw or {}).get("message", "unknown") if isinstance(raw, dict) else "invalid_response"
            return page_blocks, {
                "lightrag_applied": False,
                "lightrag_fallback": "query_failed_or_empty",
                "lightrag_message": str(msg),
                "lightrag_query": query,
                "lightrag_working_dir": str(working_dir.resolve()),
            }

        data = raw.get("data") or {}
        chunks = data.get("chunks") if isinstance(data, dict) else None
        if not isinstance(chunks, list):
            chunks = []

        block_ids: List[str] = []
        for ch in chunks:
            if not isinstance(ch, dict):
                continue
            fp = ch.get("file_path") or ch.get("reference_id") or ""
            s = str(fp).strip()
            if s and s not in block_ids:
                block_ids.append(s)

        if not block_ids:
            return page_blocks, {
                "lightrag_applied": False,
                "lightrag_fallback": "no_chunk_file_paths",
                "lightrag_query": query,
                "lightrag_working_dir": str(working_dir.resolve()),
            }

        filtered = filter_page_blocks_by_block_ids(page_blocks, block_ids)
        if not filtered:
            return page_blocks, {
                "lightrag_applied": False,
                "lightrag_fallback": "no_matching_block_ids_in_page_blocks",
                "lightrag_query": query,
                "lightrag_hit_block_ids": block_ids[:32],
            }

        stats: Dict[str, Any] = {
            "lightrag_applied": True,
            "lightrag_query": query,
            "lightrag_query_mode": query_mode,
            "lightrag_top_k": top_k,
            "lightrag_blocks_before": len(page_blocks),
            "lightrag_blocks_after": len(filtered),
            "lightrag_working_dir": str(working_dir.resolve()),
            "lightrag_rebuild": rebuild,
            "lightrag_llm_model": llm_model_name,
            "lightrag_embedding_model": embedding_model,
        }
        return filtered, stats
    finally:
        if rag is not None:
            try:
                await rag.finalize_storages()
            except Exception:
                pass
        if openai_base_url:
            if prev_base is None:
                os.environ.pop("OPENAI_BASE_URL", None)
            else:
                os.environ["OPENAI_BASE_URL"] = prev_base


def narrow_page_blocks_with_optional_lightrag(
    page_blocks: List[Dict[str, Any]],
    args: Any,
    *,
    default_rag_query: str,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    If args.use_lightrag is set, run LightRAG insert + aquery_data retrieval.
    Otherwise returns page_blocks unchanged and None.
    """
    if not getattr(args, "use_lightrag", False):
        return page_blocks, None

    wd = lightrag_working_dir_from_args(args)
    rebuild = not getattr(args, "lightrag_no_rebuild", False)
    q = (getattr(args, "rag_query", None) or "").strip() or default_rag_query
    mode = getattr(args, "lightrag_query_mode", "naive") or "naive"
    top_k = int(getattr(args, "rag_top_k", 48))
    llm_model = getattr(args, "openai_model", None) or "gpt-4o-mini"
    emb = getattr(args, "lightrag_embedding_model", None) or "text-embedding-3-small"
    base_url = getattr(args, "openai_base_url", None)

    try:
        coro = _narrow_async(
            page_blocks,
            working_dir=wd,
            rebuild=rebuild,
            query=q,
            query_mode=mode,
            top_k=top_k,
            llm_model_name=str(llm_model),
            embedding_model=str(emb),
            openai_base_url=str(base_url).strip() if base_url else None,
        )
        return asyncio.run(coro)
    except Exception as ex:
        return page_blocks, {"lightrag_applied": False, "lightrag_error": str(ex)}


def narrow_page_blocks_for_stage5_llm(
    page_blocks: List[Dict[str, Any]],
    args: Any,
    *,
    default_rag_query: str,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Dispatch: LightRAG (--use-lightrag), else FAISS (--use-rag), else full blocks.
    """
    if getattr(args, "use_lightrag", False):
        return narrow_page_blocks_with_optional_lightrag(
            page_blocks, args, default_rag_query=default_rag_query
        )
    from src.common.rag_resolve import narrow_page_blocks_with_optional_rag

    return narrow_page_blocks_with_optional_rag(page_blocks, args, default_rag_query=default_rag_query)
