"""CLI flags for optional LightRAG (HKUDS/LightRAG) narrowing of page_blocks — Stage5."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional


def add_lightrag_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--use-lightrag",
        action="store_true",
        help=(
            "Use LightRAG (lightrag-hku) to index page_blocks and retrieve top chunks before LLM. "
            "Requires OPENAI_API_KEY and pip install lightrag-hku. Mutually exclusive with --use-rag."
        ),
    )
    parser.add_argument(
        "--lightrag-working-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="LightRAG working directory (default: artifacts/stage5_constraint_ontology/lightrag_working).",
    )
    parser.add_argument(
        "--lightrag-no-rebuild",
        action="store_true",
        help="Reuse existing LightRAG index in the working dir if present (skip delete + re-insert).",
    )
    parser.add_argument(
        "--lightrag-query-mode",
        type=str,
        default="naive",
        choices=("naive", "local", "global", "hybrid", "mix"),
        help="LightRAG aquery_data mode (default: naive = vector chunks only).",
    )
    parser.add_argument(
        "--lightrag-embedding-model",
        type=str,
        default="text-embedding-3-small",
        metavar="MODEL",
        help="OpenAI embedding model id for LightRAG (must stay consistent for a given working dir).",
    )


def default_lightrag_working_dir() -> Path:
    from src.common.runtime import artifact_path

    return artifact_path("stage5_constraint_ontology", "lightrag_working")


def lightrag_working_dir_from_args(args: Any) -> Path:
    d = getattr(args, "lightrag_working_dir", None)
    if d:
        return Path(d).resolve()
    return default_lightrag_working_dir().resolve()
