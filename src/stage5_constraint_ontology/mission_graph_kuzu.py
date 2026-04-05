"""Export mission_ontology_graph JSON to an embedded Kuzu graph database (open source)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List


def _cypher_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def export_mission_ontology_to_kuzu(
    ontology: Dict[str, Any],
    db_dir: Path,
) -> Path:
    """
    Create a folder with an embedded Kuzu database file (graph.kuzu) and GraphNode + GraphRel tables.
    Nodes come from ontology['nodes']; edges from ontology['edges'] {from, rel, to}.
    Returns path to the Kuzu database file.
    """
    import kuzu

    db_dir = Path(db_dir)
    if db_dir.exists():
        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True)
    db_file = db_dir / "graph.kuzu"

    db = kuzu.Database(str(db_file))
    conn = kuzu.Connection(db)
    conn.execute(
        "CREATE NODE TABLE GraphNode("
        "id STRING, kind STRING, props STRING, PRIMARY KEY (id)"
        ");"
    )
    conn.execute("CREATE REL TABLE GraphRel(FROM GraphNode TO GraphNode, rel STRING);")

    nodes: List[Dict[str, Any]] = list(ontology.get("nodes") or [])
    if not isinstance(nodes, list):
        nodes = []

    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", "")).strip()
        if not nid:
            continue
        kind = str(n.get("type", "node")).strip() or "node"
        props = json.dumps(n, ensure_ascii=False)
        if len(props) > 12000:
            props = props[:12000] + "…"
        q = (
            f"CREATE (:GraphNode {{id: '{_cypher_escape(nid)}', "
            f"kind: '{_cypher_escape(kind)}', "
            f"props: '{_cypher_escape(props)}'}});"
        )
        conn.execute(q)

    edges: List[Dict[str, Any]] = list(ontology.get("edges") or [])
    if not isinstance(edges, list):
        edges = []

    for e in edges:
        if not isinstance(e, dict):
            continue
        frm = str(e.get("from", "")).strip()
        to = str(e.get("to", "")).strip()
        rel = str(e.get("rel", "REL")).strip() or "REL"
        if not frm or not to:
            continue
        q = (
            "MATCH (a:GraphNode {id: '" + _cypher_escape(frm) + "'}), "
            "(b:GraphNode {id: '" + _cypher_escape(to) + "'}) "
            "CREATE (a)-[:GraphRel {rel: '" + _cypher_escape(rel) + "'}]->(b);"
        )
        try:
            conn.execute(q)
        except RuntimeError:
            # Missing endpoint (e.g. partial graph) — skip
            continue

    return db_file


def query_kuzu_sample(conn: Any, limit: int = 50) -> List[List[Any]]:
    """Run a small MATCH for chatbot context (caller supplies connection)."""
    r = conn.execute(
        f"MATCH (a:GraphNode)-[r:GraphRel]->(b:GraphNode) "
        f"RETURN a.id, r.rel, b.id LIMIT {int(limit)}"
    )
    return list(r)
