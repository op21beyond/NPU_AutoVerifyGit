"""Shared argparse flags for optional FAISS RAG over page_blocks."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional


def add_rag_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--use-rag",
        action="store_true",
        help="Use Stage1 FAISS RAG index to narrow page_blocks before LLM (requires index from --build-rag-index).",
    )
    parser.add_argument(
        "--rag-index-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Directory with rag_manifest.json + faiss.index + metadata.jsonl (default: artifacts/stage1_ingestion/rag_index).",
    )
    parser.add_argument(
        "--rag-top-k",
        type=int,
        default=48,
        metavar="K",
        help="Max blocks to retrieve from FAISS per LLM call (default: 48).",
    )
    parser.add_argument(
        "--rag-query",
        type=str,
        default=None,
        metavar="TEXT",
        help="Override default retrieval query for this stage.",
    )
    parser.add_argument(
        "--rag-embedding-model",
        type=str,
        default="text-embedding-3-small",
        help="OpenAI embedding model id (must match index build; default: text-embedding-3-small).",
    )


def default_rag_index_path() -> Path:
    from src.common.runtime import artifact_path

    return artifact_path("stage1_ingestion", "rag_index")


def rag_index_dir_from_args(args: Any) -> Optional[Path]:
    if not getattr(args, "use_rag", False):
        return None
    d = getattr(args, "rag_index_dir", None)
    if d:
        return Path(d).resolve()
    return default_rag_index_path().resolve()
