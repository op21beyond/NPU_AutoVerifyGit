from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from src.common.runtime import StageRun


def _split_parts(line: str) -> List[str]:
    if "|" in line:
        return [p.strip() for p in line.split("|")]
    return re.split(r"\s+", line.strip())


def load_stage5_ground_truth(path: Path) -> Dict[str, Any]:
    """
    Supported:
    - .json object with:
    - constraint_registry: array
    - mission_ontology_graph: { "nodes": [...], "edges": [...] }
    - .txt/.lst/.list line-based compact format:
      * CONSTRAINT|constraint_id
      * NODE|node_id
      * EDGE|from|rel|to
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")

    if suffix in (".txt", ".lst", ".list"):
        constraints: List[Dict[str, Any]] = []
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            parts = _split_parts(raw)
            if not parts:
                continue
            tag = parts[0].strip().upper().rstrip(":")
            vals = parts[1:]
            if tag == "CONSTRAINT":
                if not vals:
                    continue
                cid = str(vals[0]).strip()
                if not cid:
                    continue
                constraints.append({"constraint_id": cid})
            elif tag == "NODE":
                if not vals:
                    continue
                nid = str(vals[0]).strip()
                if not nid:
                    continue
                nodes.append({"id": nid})
            elif tag == "EDGE":
                if len(vals) < 3:
                    continue
                frm = str(vals[0]).strip()
                rel = str(vals[1]).strip()
                to = str(vals[2]).strip()
                if not (frm and rel and to):
                    continue
                edges.append({"from": frm, "rel": rel, "to": to})
        return {
            "constraint_registry": constraints,
            "mission_ontology_graph": {"nodes": nodes, "edges": edges},
        }

    if suffix != ".json":
        raise ValueError("Stage5 ground truth must be .json or .txt/.lst/.list")

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Stage5 GT .json must be an object")
    cr = data.get("constraint_registry")
    og = data.get("mission_ontology_graph")
    if cr is not None and not isinstance(cr, list):
        raise ValueError("constraint_registry must be an array")
    if og is not None:
        if not isinstance(og, dict):
            raise ValueError("mission_ontology_graph must be an object")
        for k in ("nodes", "edges"):
            v = og.get(k)
            if v is not None and not isinstance(v, list):
                raise ValueError(f"mission_ontology_graph.{k} must be an array")
    return {
        "constraint_registry": list(cr or []),
        "mission_ontology_graph": {
            "nodes": list((og or {}).get("nodes") or []),
            "edges": list((og or {}).get("edges") or []),
        },
    }


def _ensure_constraint_traces(rows: List[Dict[str, Any]], run: StageRun) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        r = dict(row)
        if not r.get("trace_id"):
            r["trace_id"] = f"{run.stage_run_id}:c:gt:{i}"
        if "source_refs" not in r:
            r["source_refs"] = []
        out.append(r)
    return out


def build_stage5_outputs_from_ground_truth(gt: Dict[str, Any], run: StageRun) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    constraints = _ensure_constraint_traces(list(gt.get("constraint_registry") or []), run)
    og = gt.get("mission_ontology_graph") or {}
    graph = {
        "nodes": list(og.get("nodes") or []),
        "edges": list(og.get("edges") or []),
    }
    return constraints, graph


def _constraint_ids(rows: List[Dict[str, Any]]) -> Set[str]:
    s: Set[str] = set()
    for r in rows:
        cid = str(r.get("constraint_id", "")).strip()
        if cid:
            s.add(cid)
    return s


def _node_ids(nodes: List[Dict[str, Any]]) -> Set[str]:
    s: Set[str] = set()
    for n in nodes:
        nid = str(n.get("id", "")).strip()
        if nid:
            s.add(nid)
    return s


def _edge_set(edges: List[Dict[str, Any]]) -> Set[Tuple[str, str, str]]:
    s: Set[Tuple[str, str, str]] = set()
    for e in edges:
        s.add(
            (
                str(e.get("from", "")).strip(),
                str(e.get("rel", "")).strip(),
                str(e.get("to", "")).strip(),
            )
        )
    return {x for x in s if any(x)}


def evaluate_stage5_extraction(
    pred_constraints: List[Dict[str, Any]],
    pred_graph: Dict[str, Any],
    gt: Dict[str, Any],
) -> Dict[str, Any]:
    report: Dict[str, Any] = {"sections": {}}

    gt_c = list(gt.get("constraint_registry") or [])
    if gt_c:
        gk = _constraint_ids(gt_c)
        pk = _constraint_ids(pred_constraints)
        tp = len(gk & pk)
        fp = len(pk - gk)
        fn = len(gk - pk)
        prec = tp / (tp + fp) if (tp + fp) else (1.0 if not gk else 0.0)
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 0.0 if prec + rec <= 0 else 2 * prec * rec / (prec + rec)
        report["sections"]["constraint_registry"] = {
            "metrics": {
                "true_positive_count": tp,
                "false_positive_count": fp,
                "false_negative_count": fn,
                "precision": round(prec, 6),
                "recall": round(rec, 6),
                "f1": round(f1, 6),
            },
            "true_positives": sorted(gk & pk),
            "false_positives": sorted(pk - gk),
            "false_negatives": sorted(gk - pk),
        }

    gt_g = gt.get("mission_ontology_graph") or {}
    gt_nodes = list(gt_g.get("nodes") or [])
    gt_edges = list(gt_g.get("edges") or [])
    if gt_nodes or gt_edges:
        g_nodes = _node_ids(gt_nodes)
        p_nodes = _node_ids(list((pred_graph or {}).get("nodes") or []))
        g_edges = _edge_set(gt_edges)
        p_edges = _edge_set(list((pred_graph or {}).get("edges") or []))

        tp_n = len(g_nodes & p_nodes)
        fp_n = len(p_nodes - g_nodes)
        fn_n = len(g_nodes - p_nodes)
        prec_n = tp_n / (tp_n + fp_n) if (tp_n + fp_n) else (1.0 if not g_nodes else 0.0)
        rec_n = tp_n / (tp_n + fn_n) if (tp_n + fn_n) else 1.0
        f1_n = 0.0 if prec_n + rec_n <= 0 else 2 * prec_n * rec_n / (prec_n + rec_n)

        tp_e = len(g_edges & p_edges)
        fp_e = len(p_edges - g_edges)
        fn_e = len(g_edges - p_edges)
        prec_e = tp_e / (tp_e + fp_e) if (tp_e + fp_e) else (1.0 if not g_edges else 0.0)
        rec_e = tp_e / (tp_e + fn_e) if (tp_e + fn_e) else 1.0
        f1_e = 0.0 if prec_e + rec_e <= 0 else 2 * prec_e * rec_e / (prec_e + rec_e)

        report["sections"]["mission_ontology_graph"] = {
            "nodes": {
                "metrics": {
                    "true_positive_count": tp_n,
                    "false_positive_count": fp_n,
                    "false_negative_count": fn_n,
                    "precision": round(prec_n, 6),
                    "recall": round(rec_n, 6),
                    "f1": round(f1_n, 6),
                },
                "true_positives": sorted(g_nodes & p_nodes),
                "false_positives": sorted(p_nodes - g_nodes),
                "false_negatives": sorted(g_nodes - p_nodes),
            },
            "edges": {
                "metrics": {
                    "true_positive_count": tp_e,
                    "false_positive_count": fp_e,
                    "false_negative_count": fn_e,
                    "precision": round(prec_e, 6),
                    "recall": round(rec_e, 6),
                    "f1": round(f1_e, 6),
                },
                "true_positives": sorted(list(g_edges & p_edges)),
                "false_positives": sorted(list(p_edges - g_edges)),
                "false_negatives": sorted(list(g_edges - p_edges)),
            },
        }

    return report
