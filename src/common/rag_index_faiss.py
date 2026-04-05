"""FAISS vector index over page_blocks with hierarchical metadata (page → blocks)."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

MANIFEST_NAME = "rag_manifest.json"
INDEX_NAME = "faiss.index"
METADATA_NAME = "metadata.jsonl"


def _openai_embed_texts(
    texts: List[str],
    *,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> np.ndarray:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai package required for RAG embeddings") from e

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY required to build or query RAG index")

    client_kwargs: Dict[str, Any] = {"api_key": key, "timeout": 120.0}
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")
    client = OpenAI(**client_kwargs)

    batch_size = 64
    all_vecs: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        resp = client.embeddings.create(model=model, input=chunk)
        for j, item in enumerate(resp.data):
            all_vecs.append(list(item.embedding))
    arr = np.array(all_vecs, dtype=np.float32)
    # Cosine similarity with inner product: L2-normalize
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    arr = arr / norms
    return arr


@dataclass
class RagManifest:
    embedding_model: str
    embedding_dim: int
    vector_count: int
    index_type: str
    stage_run_id: str
    page_hierarchy: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "vector_count": self.vector_count,
            "index_type": self.index_type,
            "stage_run_id": self.stage_run_id,
            "page_hierarchy": self.page_hierarchy,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RagManifest":
        return RagManifest(
            embedding_model=str(d.get("embedding_model", "")),
            embedding_dim=int(d.get("embedding_dim", 0)),
            vector_count=int(d.get("vector_count", 0)),
            index_type=str(d.get("index_type", "FlatIP")),
            stage_run_id=str(d.get("stage_run_id", "")),
            page_hierarchy=d.get("page_hierarchy") or {},
        )


def _build_page_hierarchy(page_blocks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_page: Dict[int, List[str]] = {}
    for b in page_blocks:
        try:
            p = int(b.get("page", 0))
        except (TypeError, ValueError):
            p = 0
        bid = str(b.get("block_id", ""))
        by_page.setdefault(p, []).append(bid)
    pages_out = []
    for p in sorted(by_page.keys()):
        bids = by_page[p]
        pages_out.append({"page": p, "block_count": len(bids), "block_ids": bids})
    return {"pages": pages_out, "total_pages": len(pages_out)}


def build_faiss_rag_index(
    page_blocks: List[Dict[str, Any]],
    out_dir: Path,
    *,
    stage_run_id: str,
    embedding_model: str = "text-embedding-3-small",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> RagManifest:
    """Embed each non-empty block, build FAISS IndexFlatIP, save index + metadata.jsonl + manifest."""
    try:
        import faiss  # type: ignore
    except ImportError as e:
        raise RuntimeError("faiss-cpu (or faiss) is required. pip install faiss-cpu") from e

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    nonempty_per_page: Counter = Counter()
    for b in page_blocks:
        if not (b.get("raw_text") or "").strip():
            continue
        try:
            nonempty_per_page[int(b.get("page") or 0)] += 1
        except (TypeError, ValueError):
            nonempty_per_page[0] += 1

    texts: List[str] = []
    meta_rows: List[Dict[str, Any]] = []

    # Per-page block order for hierarchy
    page_order: Dict[int, int] = {}
    for b in sorted(
        page_blocks,
        key=lambda x: (
            int(x.get("page") or 0),
            str(x.get("block_id", "")),
            str(x.get("block_type", "")),
        ),
    ):
        raw = (b.get("raw_text") or "").strip()
        if not raw:
            continue
        try:
            page = int(b.get("page", 0))
        except (TypeError, ValueError):
            page = 0
        bid = str(b.get("block_id", ""))
        btype = str(b.get("block_type", "text"))
        idx_on_page = page_order.get(page, 0)
        page_order[page] = idx_on_page + 1

        same_page = int(nonempty_per_page.get(page, 0))
        header = f"[page={page} block_id={bid} type={btype} index_on_page={idx_on_page}]\n"
        texts.append(header + raw[:12000])
        meta_rows.append(
            {
                "faiss_id": len(texts) - 1,
                "page": page,
                "block_id": bid,
                "block_type": btype,
                "block_index_on_page": idx_on_page,
                "blocks_on_page": same_page,
                "parent_page": page,
                "text_preview": raw[:500],
            }
        )

    if not texts:
        raise RuntimeError("No non-empty page_blocks to index for RAG")

    vectors = _openai_embed_texts(texts, model=embedding_model, api_key=api_key, base_url=base_url)
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    faiss.write_index(index, str(out_dir / INDEX_NAME))

    with (out_dir / METADATA_NAME).open("w", encoding="utf-8") as fp:
        for row in meta_rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    hierarchy = _build_page_hierarchy(page_blocks)
    manifest = RagManifest(
        embedding_model=embedding_model,
        embedding_dim=dim,
        vector_count=len(texts),
        index_type="FlatIP",
        stage_run_id=stage_run_id,
        page_hierarchy=hierarchy,
    )
    with (out_dir / MANIFEST_NAME).open("w", encoding="utf-8") as fp:
        json.dump(manifest.to_dict(), fp, indent=2, ensure_ascii=False)
    return manifest


class FaissRagIndex:
    """Load FAISS index + metadata; run similarity search for a query string."""

    def __init__(self, index_dir: Path):
        try:
            import faiss  # type: ignore
        except ImportError as e:
            raise RuntimeError("faiss-cpu required") from e
        self._index_dir = Path(index_dir)
        self._faiss = faiss
        with (self._index_dir / MANIFEST_NAME).open(encoding="utf-8") as fp:
            self.manifest = RagManifest.from_dict(json.load(fp))
        self._index = faiss.read_index(str(self._index_dir / INDEX_NAME))
        self._metadata: List[Dict[str, Any]] = []
        with (self._index_dir / METADATA_NAME).open(encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if line:
                    self._metadata.append(json.loads(line))

    def search(
        self,
        query: str,
        k: int,
        *,
        embedding_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Return (metadata_row, score) sorted by score descending."""
        model = embedding_model or self.manifest.embedding_model
        qv = _openai_embed_texts([query], model=model, api_key=api_key, base_url=base_url)
        scores, indices = self._index.search(qv, min(k, self._index.ntotal))
        out: List[Tuple[Dict[str, Any], float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            if 0 <= idx < len(self._metadata):
                out.append((self._metadata[idx], float(score)))
        return out


def load_block_ids_from_rag_hits(
    hits: Sequence[Tuple[Dict[str, Any], float]],
) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for m, _ in hits:
        bid = str(m.get("block_id", ""))
        if bid and bid not in seen:
            seen.add(bid)
            ordered.append(bid)
    return ordered


def filter_page_blocks_by_block_ids(
    page_blocks: List[Dict[str, Any]],
    block_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    want = set(block_ids)
    return [b for b in page_blocks if str(b.get("block_id", "")) in want]
