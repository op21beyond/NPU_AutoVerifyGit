from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from src.common.instruction_key import catalog_row_key, normalize_variation
from src.common.runtime import StageRun


def _norm_field_id(name: str) -> str:
    x = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").upper()).strip("_")
    return x or "FIELD"


def instruction_node_id(inst: Dict[str, Any]) -> str:
    """Stable ID without '|' so pipe-delimited Stage5 text GT lines stay unambiguous."""
    opc = inst.get("opcode_value")
    name = str(inst.get("instruction_name", "UNKNOWN")).strip().upper()
    var = normalize_variation(inst.get("variation"))
    if opc is not None:
        try:
            base = f"Instr:{int(opc)}"
        except (TypeError, ValueError):
            base = f"Instr:{name}"
    else:
        base = f"Instr:{name}"
    if var:
        return f"{base}_{var}"
    return base


def _normalize_allowed_value_form(raw: str) -> str:
    s = (raw or "range").strip().lower()
    if s in ("enum", "range", "mask", "set", "other"):
        return s
    return "range"


def domain_expression_and_meta(
    field_name: str,
    allowed_value_form: str,
    allowed_values_or_range: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Build a readable constraint expression and optional structured_domain metadata.
    - enum + non-empty av: FIELD IN (a, b, c)
    - range + parsable bounds: lo <= FIELD <= hi (supports a..b, a-b, 0x0..0xF)
    - empty av: explicit placeholder (no fake ∈ empty)
    """
    fn = (field_name or "UNKNOWN").strip() or "UNKNOWN"
    avf = _normalize_allowed_value_form(allowed_value_form)
    av = (allowed_values_or_range or "").strip()
    meta: Dict[str, Any] = {"allowed_value_form": avf}

    if not av:
        meta["domain_value_unspecified"] = True
        if avf == "enum":
            expr = f"{fn} IN (/* unspecified — fill allowed_values_or_range in field_domain_catalog */)"
        elif avf == "range":
            expr = f"{fn} RANGE (/* unspecified — fill allowed_values_or_range in field_domain_catalog */)"
        elif avf == "mask":
            expr = f"{fn} MASK (/* unspecified */)"
        elif avf == "set":
            expr = f"{fn} SET (/* unspecified */)"
        else:
            expr = f"{fn} ({avf}, values unspecified)"
        return expr, meta

    if avf == "enum":
        parts = re.split(r"[|,;]+", av)
        tokens = [p.strip() for p in parts if p.strip()]
        if not tokens:
            tokens = [av]
        meta["structured_domain"] = {"form": "enum", "values": tokens}
        inner = ", ".join(tokens)
        return f"{fn} IN ({inner})", meta

    if avf == "range":
        # a..b or a..b with hex
        m = re.search(
            r"(0x[0-9a-fA-F]+|\d+)\s*\.\.\s*(0x[0-9a-fA-F]+|\d+)",
            av,
        )
        if m:
            lo, hi = m.group(1), m.group(2)
            meta["structured_domain"] = {"form": "range", "lo_raw": lo, "hi_raw": hi}
            return f"{lo} <= {fn} <= {hi}", meta
        m2 = re.search(r"(\d+)\s*-\s*(\d+)", av)
        if m2:
            lo, hi = m2.group(1), m2.group(2)
            meta["structured_domain"] = {"form": "range", "lo_raw": lo, "hi_raw": hi}
            return f"{lo} <= {fn} <= {hi}", meta
        meta["structured_domain"] = {"form": "range", "raw": av}
        return f"{fn} RANGE {av}", meta

    if avf in ("mask", "set", "other"):
        meta["structured_domain"] = {"form": avf, "raw": av}
        return f"{fn} ({avf}) {av}", meta

    meta["structured_domain"] = {"form": avf, "raw": av}
    return f"{fn} {avf} {av}", meta


def build_constraint_pruning_index(
    constraints: List[Dict[str, Any]],
    category_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Bridge file for Stage6+: ties constraint_type_catalog canonical labels to registry rows
    (via constraint_type_level1 on each row).
    """
    by_l1: Counter = Counter()
    by_l2: Counter = Counter()
    for c in constraints:
        by_l1[str(c.get("constraint_type_level1") or "")] += 1
        by_l2[str(c.get("constraint_type_level2") or "")] += 1

    cp = category_payload or {}
    return {
        "schema_version": "constraint_pruning_index@1",
        "canonical_categories": list(cp.get("canonical_categories") or []),
        "category_mapping": dict(cp.get("mapping") or {}),
        "merge_rationale": cp.get("merge_rationale"),
        "constraint_counts_by_level1": dict(by_l1),
        "constraint_counts_by_level2": dict(by_l2),
        "stage6_integration": {
            "constraint_registry_field_for_pruning": "constraint_type_level1",
            "description": "LLM rows use normalized canonical categories in level1; field-domain rows use allowed_value_form (enum/range/...). Join with canonical_categories for pruning groups.",
            "artifact_files": ["constraint_type_catalog.json", "constraint_registry.jsonl"],
        },
    }


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
        expr, dom_meta = domain_expression_and_meta(fn, avf, av)
        row: Dict[str, Any] = {
            "trace_id": f"{run.stage_run_id}:c:{i}",
            "constraint_id": cid,
            "constraint_type_level1": _normalize_allowed_value_form(avf),
            "constraint_type_level2": "field-domain",
            "expression": expr,
            "classification_rationale": "derived from field_domain_catalog",
            "source_refs": d.get("source_refs") or [],
            "applies_to": {"entity_type": "Field", "entity_name": fn},
        }
        if dom_meta:
            row["domain_constraint_meta"] = dom_meta
        out.append(row)
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
                "variation": normalize_variation(inst.get("variation")),
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
        et = str(ap.get("entity_type", "Field")).strip()
        en = str(ap.get("entity_name", "")).strip()
        if not en:
            continue
        if et == "Field":
            add_edge(cnode_id, "APPLIES_TO", f"Field:{en.upper()}")
        elif et == "Instruction":
            for inst in instructions:
                if str(inst.get("instruction_name", "")).strip().upper() == en.upper():
                    add_edge(cnode_id, "APPLIES_TO", instruction_node_id(inst))
                    break
        elif et == "Document":
            add_edge(cnode_id, "APPLIES_TO", "IP:sample")

    inst_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for inst in instructions:
        k = catalog_row_key(inst.get("instruction_name"), inst.get("variation"))
        if k[0] and k not in inst_by_key:
            inst_by_key[k] = inst

    for r in datatype_catalog:
        ins = str(r.get("instruction_name", "")).strip().upper()
        fn = str(r.get("field_name", "")).strip()
        if not fn:
            continue
        rk = catalog_row_key(ins, r.get("variation"))
        inst = inst_by_key.get(rk)
        if inst:
            iid = instruction_node_id(inst)
            add_edge(iid, "HAS_FIELD", f"Field:{fn.upper()}")
        dt_ref = str(r.get("data_type_ref", "")).strip()
        if dt_ref:
            add_edge(f"Field:{fn.upper()}", "HAS_DATATYPE", f"DT:{dt_ref}")

    edges = [{"from": a, "rel": b, "to": c} for a, b, c in sorted(edge_tuples)]
    return {"nodes": list(node_by_id.values()), "edges": edges}
