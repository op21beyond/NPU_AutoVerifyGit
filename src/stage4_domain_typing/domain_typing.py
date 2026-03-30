from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.common.runtime import StageRun


def _bit_width_from_range(bit_range: str) -> int:
    br = (bit_range or "").strip().replace(" ", "")
    if ":" in br:
        parts = br.split(":")
        if len(parts) == 2:
            try:
                msb, lsb = int(parts[0]), int(parts[1])
                return abs(msb - lsb) + 1
            except ValueError:
                pass
    if br.isdigit():
        return 1
    return 4


def _type_id_for_width(w: int) -> str:
    if w <= 0:
        return "uint4"
    if w <= 64:
        return f"uint{w}"
    return "uint_wide"


def _domain_allowed_for_width(w: int) -> Tuple[str, str]:
    if w <= 0:
        return "range", "0..15"
    if w >= 63:
        return "range", f"0..(2^{w}-1)"
    maxv = (1 << w) - 1
    return "range", f"0..{maxv}"


def build_datatype_registry(fields: List[Dict[str, Any]], run: StageRun) -> List[Dict[str, Any]]:
    """Collect unique primitive types inferred from bit_range widths in instruction_field_map rows."""
    seen: Dict[str, Dict[str, Any]] = {}
    for row in fields:
        br = str(row.get("bit_range") or "")
        w = _bit_width_from_range(br)
        tid = _type_id_for_width(w)
        if tid in seen:
            continue
        seen[tid] = {
            "trace_id": f"{run.stage_run_id}:reg:{tid}",
            "type_id": tid,
            "type_name_raw": tid,
            "type_name_normalized": tid,
            "category": "software_primitive",
            "description": f"Inferred unsigned integer type from field bit widths ({w} bits)",
            "value_constraint_summary": _domain_allowed_for_width(w)[1],
            "value_generation_method": "",
            "source_refs": [],
        }
    if not seen:
        tid = "uint4"
        seen[tid] = {
            "trace_id": f"{run.stage_run_id}:reg:{tid}",
            "type_id": tid,
            "type_name_raw": tid,
            "type_name_normalized": tid,
            "category": "software_primitive",
            "description": "Default placeholder when no fields are available",
            "value_constraint_summary": "0..15",
            "value_generation_method": "",
            "source_refs": [],
        }
    return [seen[k] for k in sorted(seen.keys())]


def build_field_datatype_catalog(fields: List[Dict[str, Any]], run: StageRun) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(fields):
        br = str(row.get("bit_range") or "")
        w = _bit_width_from_range(br)
        tid = _type_id_for_width(w)
        instr = str(row.get("instruction_name", "")).strip().upper()
        fname = str(row.get("field_name", "")).strip()
        rows.append(
            {
                "trace_id": f"{run.stage_run_id}:dtype:{i}",
                "instruction_name": instr,
                "field_name": fname,
                "data_type_raw": tid,
                "data_type_ref": tid,
                "source_refs": row.get("source_refs") or [],
            }
        )
    return rows


def build_field_domain_catalog(fields: List[Dict[str, Any]], run: StageRun) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(fields):
        br = str(row.get("bit_range") or "")
        w = _bit_width_from_range(br)
        form, allowed = _domain_allowed_for_width(w)
        fname = str(row.get("field_name", "")).strip()
        rows.append(
            {
                "trace_id": f"{run.stage_run_id}:domain:{i}",
                "field_name": fname,
                "allowed_value_form": form,
                "allowed_values_or_range": allowed,
                "source_refs": row.get("source_refs") or [],
            }
        )
    return rows
