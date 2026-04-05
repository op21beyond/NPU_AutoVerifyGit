"""
Streamlit chatbot: FAISS RAG (Stage1) + Kuzu graph (Stage5) + OpenAI chat.
Run from repo root: streamlit run tools/rag_graph_chatbot/app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _defaults() -> Dict[str, Any]:
    return {
        "vector_index_dir": str(ROOT / "artifacts" / "stage1_ingestion" / "rag_index"),
        "graph_db_dir": str(ROOT / "artifacts" / "stage5_constraint_ontology" / "mission_graph_kuzu"),
        "openai_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "rag_top_k": 12,
        "graph_edge_limit": 40,
        "openai_base_url": "",
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "multiturn": True,
        "messages": [],
    }


def _ensure_session_state() -> None:
    import streamlit as st

    for k, v in _defaults().items():
        if k not in st.session_state:
            st.session_state[k] = v


def _rag_context(index_dir: Path, query: str, k: int, embedding_model: str, base_url: str) -> str:
    from src.common.rag_index_faiss import FaissRagIndex

    if not (index_dir / "rag_manifest.json").exists():
        return "(RAG index not found — build Stage1 with --build-rag-index.)\n"
    idx = FaissRagIndex(index_dir)
    hits = idx.search(
        query,
        max(1, k),
        embedding_model=embedding_model,
        base_url=base_url or None,
    )
    lines: List[str] = []
    for m, score in hits[:k]:
        prev = m.get("text_preview") or ""
        lines.append(
            f"score={score:.4f} page={m.get('page')} block_id={m.get('block_id')} "
            f"type={m.get('block_type')}\n{prev}\n---"
        )
    return "\n".join(lines) if lines else "(No RAG hits.)\n"


def _graph_context(db_dir: Path, edge_limit: int) -> str:
    try:
        import kuzu
    except ImportError:
        return "(kuzu package not installed. pip install kuzu)\n"

    db_file = db_dir / "graph.kuzu" if db_dir.is_dir() else db_dir
    if not db_file.exists():
        return "(Kuzu graph.kuzu not found — run Stage5 to export mission_graph_kuzu/graph.kuzu.)\n"

    try:
        db = kuzu.Database(str(db_file))
        conn = kuzu.Connection(db)
    except Exception as ex:
        return f"(Could not open Kuzu DB: {ex})\n"

    lines: List[str] = []
    try:
        r = conn.execute(
            f"MATCH (a:GraphNode)-[rel:GraphRel]->(b:GraphNode) "
            f"RETURN a.id, rel.rel, b.id LIMIT {int(edge_limit)}"
        )
        lines.append("Sample edges (GraphRel):")
        for row in r:
            lines.append(f"  {row[0]} -[{row[1]}]-> {row[2]}")
    except Exception as ex:
        lines.append(f"(Edge query failed: {ex})")

    try:
        r2 = conn.execute("MATCH (n:GraphNode) RETURN n.id, n.kind LIMIT 25")
        lines.append("\nSample nodes:")
        for row in r2:
            lines.append(f"  {row[0]} ({row[1]})")
    except Exception:
        pass

    return "\n".join(lines) + "\n"


def _chat_openai(
    messages: List[Dict[str, str]],
    *,
    model: str,
    api_key: str,
    base_url: str,
) -> str:
    from openai import OpenAI

    kwargs: Dict[str, Any] = {"api_key": api_key, "timeout": 120.0}
    if base_url:
        kwargs["base_url"] = base_url.rstrip("/")
    client = OpenAI(**kwargs)
    comp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=messages,
    )
    return (comp.choices[0].message.content or "").strip()


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="RAG + Graph chat", layout="wide")
    _ensure_session_state()

    st.title("Architecture doc chat (FAISS + Kuzu + OpenAI)")
    st.caption("Point to Stage1 `rag_index` and Stage5 `mission_graph_kuzu`; settings persist in session state.")

    with st.sidebar:
        st.subheader("Paths")
        st.text_input(
            "FAISS RAG index directory",
            key="vector_index_dir",
            help="Folder with rag_manifest.json, faiss.index, metadata.jsonl",
        )
        st.text_input(
            "Kuzu graph DB directory",
            key="graph_db_dir",
            help="Stage5 mission_graph_kuzu folder",
        )
        st.subheader("Models")
        st.text_input("Chat model", key="openai_model")
        st.text_input("Embedding model (RAG query)", key="embedding_model")
        st.number_input("RAG top-k", min_value=1, max_value=200, key="rag_top_k")
        st.number_input("Graph edge sample limit", min_value=5, max_value=500, key="graph_edge_limit")
        st.text_input("OpenAI base URL (optional)", key="openai_base_url")
        st.text_input(
            "OPENAI_API_KEY override (optional)",
            type="password",
            key="api_key",
            help="If empty, uses environment OPENAI_API_KEY",
        )
        st.checkbox("Multiturn chat", key="multiturn")
        if st.button("Clear chat history"):
            st.session_state.messages = []
            st.rerun()

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    index_dir = Path(st.session_state.vector_index_dir)
    graph_dir = Path(st.session_state.graph_db_dir)

    if prompt := st.chat_input("Ask about the document / graph…"):
        api_key = (st.session_state.api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            st.error("Set OPENAI_API_KEY in the environment or in the sidebar.")
            return

        with st.spinner("Retrieving context…"):
            rag_txt = _rag_context(
                index_dir,
                prompt,
                int(st.session_state.rag_top_k),
                st.session_state.embedding_model,
                st.session_state.openai_base_url,
            )
            graph_txt = _graph_context(graph_dir, int(st.session_state.graph_edge_limit))

        system = (
            "You are a helpful assistant answering questions about an NPU/ISA architecture document. "
            "Use the RAG excerpts and graph samples below. If information is missing, say so.\n\n"
            "### RAG excerpts\n"
            + rag_txt
            + "\n### Graph sample (Kuzu)\n"
            + graph_txt
        )

        msgs: List[Dict[str, str]] = [{"role": "system", "content": system}]
        if st.session_state.multiturn:
            msgs.extend(st.session_state.messages)
        msgs.append({"role": "user", "content": prompt})

        with st.spinner("Generating…"):
            try:
                reply = _chat_openai(
                    msgs,
                    model=st.session_state.openai_model,
                    api_key=api_key,
                    base_url=st.session_state.openai_base_url,
                )
            except Exception as ex:
                reply = f"(Error: {ex})"

        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()


if __name__ == "__main__":
    main()
