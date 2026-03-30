from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

from src.common.runtime import StageRun


def _norm_field_id(name: str) -> str:
    x = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").upper()).strip("_")
    return x or "FIELD"


def instruction_node_id(inst: Dict[str, Any]) -> str:
    opc = inst.get("opcode_value")
    name = str(inst.get("instruction_name", "UNKNOWN")).strip().upper()
    if opc is not None:
        try:
            return f"Instr:{int(opc)}"
        except (TypeError, ValueError):
            pass
    return f"Instr:{name}"


def build_constraint_registry(
    domains: List[Dict[str, Any]],
    instructions: List[Dict[str, Any]],
    run: StageRun,
) -> List[Dict[str, Any]]:
    if not domains:
        inst0 = instructions[0] if instructions else {}
        fn = "OPCODE"
        return [
            {
                "trace_id": f"{run.stage_run_id}:c:0",
                "constraint_id": "C_PLACEHOLDER_001",
                "constraint_type_level1": "range",
                "constraint_type_level2": "instruction-specific",
                "expression": f"0 <= {fn} <= 15",
                "classification_rationale": "placeholder when field_domain_catalog is empty",
                "source_refs": [],
                "applies_to": {"entity_type": "Field", "entity_name": fn},
            }
        ]

    out: List[Dict[str, Any]] = []
    for i, d in enumerate(domains):
        fn = str(d.get("field_name", "UNKNOWN")).strip()
        avf = str(d.get("allowed_value_form", "range")).strip() or "range"
        av = str(d.get("allowed_values_or_range", "")).strip()
        cid = f"C_{_norm_field_id(fn)}_{i:04d}"
        out.append(
            {
                "trace_id": f"{run.stage_run_id}:c:{i}",
                "constraint_id": cid,
                "constraint_type_level1": avf,
                "constraint_type_level2": "field-domain",
                "expression": f"{fn} ∈ {av}" if av else f"{fn} domain ({avf})",
                "classification_rationale": "derived from field_domain_catalog",
                "source_refs": d.get("source_refs") or [],
                "applies_to": {"entity_type": "Field", "entity_name": fn},
            }
        )
    return out


def build_mission_ontology_graph(
    constraints: List[Dict[str, Any]],
    instructions: List[Dict[str, Any]],
    datatype_catalog: List[Dict[str, Any]],
    registry: List[Dict[str, Any]],
) -> Dict[str, Any]:
    node_by_id: Dict[str, Dict[str, Any]] = {}
    edge_tuples: Set[Tuple[str, str, str]] = set()

    def add_node(n: Dict[str, Any]) -> None:
        node_by_id[n["id"]] = n

    def add_edge(frm: str, rel: str, to: str) -> None:
        edge_tuples.add((frm, rel, to))

    add_node({"type": "IP", "id": "IP:sample", "ip_name": "sample", "ip_type": "npu", "ip_version": "v0"})

    eu_names = sorted(
        {str(i.get("execution_unit", "UNKNOWN_UNIT")).strip() or "UNKNOWN_UNIT" for i in instructions}
    )
    for eu in eu_names:
        add_node({"type": "ExecutionUnit", "id": f"EU:{eu}", "name": eu})

    for inst in instructions:
        iid = instruction_node_id(inst)
        eu = str(inst.get("execution_unit", "UNKNOWN_UNIT")).strip() or "UNKNOWN_UNIT"
        add_node(
            {
                "type": "Instruction",
                "id": iid,
                "instruction_name": str(inst.get("instruction_name", "")).strip().upper(),
                "instruction_kind": str(inst.get("instruction_kind", "unknown")),
                "opcode_raw": inst.get("opcode_raw"),
                "opcode_radix": inst.get("opcode_radix"),
                "opcode_value": inst.get("opcode_value"),
            }
        )
        add_edge(iid, "EXECUTES_ON", f"EU:{eu}")
        add_edge("IP:sample", "HAS_INSTRUCTION", iid)

    field_names = sorted(
        {str(r.get("field_name", "")).strip() for r in datatype_catalog if r.get("field_name")}
    )
    for fn in field_names:
        add_node({"type": "Field", "id": f"Field:{fn.upper()}", "name": fn})

    type_ids = sorted({str(r.get("type_id", "")).strip() for r in registry if r.get("type_id")})
    for tid in type_ids:
        add_node({"type": "DataType", "id": f"DT:{tid}", "type_id": tid})

    for c in constraints:
        cid = str(c.get("constraint_id", "")).strip()
        if not cid:
            continue
        cnode_id = f"Constraint:{cid}"
        add_node({"type": "Constraint", "id": cnode_id, "constraint_id": cid})
        ap = c.get("applies_to") or {}
        en = str(ap.get("entity_name", "")).strip()
        if en:
            add_edge(cnode_id, "APPLIES_TO", f"Field:{en.upper()}")

    inst_by_name: Dict[str, Dict[str, Any]] = {}
    for inst in instructions:
        n = str(inst.get("instruction_name", "")).strip().upper()
        if n and n not in inst_by_name:
            inst_by_name[n] = inst

    for r in datatype_catalog:
        ins = str(r.get("instruction_name", "")).strip().upper()
        fn = str(r.get("field_name", "")).strip()
        if not fn:
            continue
        inst = inst_by_name.get(ins)
        if inst:
            iid = instruction_node_id(inst)
            add_edge(iid, "HAS_FIELD", f"Field:{fn.upper()}")
        dt_ref = str(r.get("data_type_ref", "")).strip()
        if dt_ref:
            add_edge(f"Field:{fn.upper()}", "HAS_DATATYPE", f"DT:{dt_ref}")

    edges = [{"from": a, "rel": b, "to": c} for a, b, c in sorted(edge_tuples)]
    return {"nodes": list(node_by_id.values()), "edges": edges}
