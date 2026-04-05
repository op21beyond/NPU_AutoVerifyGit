from __future__ import annotations

from typing import Any, Dict, List, Set

from src.common.instruction_key import normalize_variation, variation_from_catalog_row
from src.common.llm_page_blocks import serialize_page_blocks_for_prompt
from src.common.openai_json import openai_chat_json_object
from src.common.runtime import StageRun

_SYSTEM_PROMPT = """You assign a data type from a fixed registry to each instruction field.
Return ONLY valid JSON (no markdown fences). The JSON must match this shape:
{
  "mappings": [
    {
      "instruction_name": "<uppercase logical instruction name>",
      "variation": "<short label or null when single form>",
      "field_name": "<field name as in the field list>",
      "data_type_ref": "<must be exactly one of the allowed type_id strings>",
      "data_type_raw": "<optional verbatim type from document>",
      "source_page": <integer page from excerpt headers>
    }
  ]
}
Rules:
- Emit exactly one mapping per field line in the user message (same order is preferred).
- data_type_ref must be copied exactly from the allowed list; never invent new type ids.
- If unsure, pick the closest primitive (e.g. unsigned integer width) and set source_page to a relevant page.
"""


def _field_lines_from_instruction_map(rows: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for row in rows:
        inst = str(row.get("instruction_name", "")).strip().upper()
        fn = str(row.get("field_name", "")).strip()
        if not inst or not fn:
            continue
        var = variation_from_catalog_row(row)
        v = "" if var is None else str(var).strip().upper()
        lines.append(f"{inst}|{v}|{fn}")
    return "\n".join(lines) if lines else "(no fields)"


def _allowed_type_ids(registry: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for r in registry:
        tid = str(r.get("type_id", "")).strip()
        if tid:
            out.append(tid)
    return sorted(set(out))


def _normalize_mappings(
    payload: Dict[str, Any],
    run: StageRun,
    allowed: Set[str],
) -> List[Dict[str, Any]]:
    items = payload.get("mappings")
    if not isinstance(items, list):
        return []

    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        inst = str(raw.get("instruction_name", "")).strip().upper()
        fn = str(raw.get("field_name", "")).strip()
        if not inst or not fn:
            continue
        var = normalize_variation(raw.get("variation"))
        ref = str(raw.get("data_type_ref", "")).strip()
        if ref not in allowed and allowed:
            ref = next(iter(sorted(allowed))) if allowed else ref
        try:
            page_i = int(raw.get("source_page", 1))
        except (TypeError, ValueError):
            page_i = 1
        out.append(
            {
                "trace_id": f"{run.stage_run_id}:dtype:{i}",
                "instruction_name": inst,
                "variation": var,
                "field_name": fn,
                "data_type_raw": str(raw.get("data_type_raw", ref)).strip() or ref,
                "data_type_ref": ref,
                "source_refs": [{"page": page_i}],
            }
        )
    return out


def build_field_datatype_catalog_openai(
    page_blocks: List[Dict[str, Any]],
    instruction_field_rows: List[Dict[str, Any]],
    datatype_registry: List[Dict[str, Any]],
    run: StageRun,
    *,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    allowed = set(_allowed_type_ids(datatype_registry))
    if not allowed:
        allowed.add("UNKNOWN")

    excerpt = serialize_page_blocks_for_prompt(page_blocks)
    fields_block = _field_lines_from_instruction_map(instruction_field_rows)
    allowed_block = "\n".join(sorted(allowed))

    user_msg = (
        "Allowed type_id values (data_type_ref must be exactly one of these):\n"
        f"{allowed_block}\n\n"
        "Map each field line below to one data_type_ref. Field lines use INSTRUCTION|VAR|FIELD "
        "(VAR empty means no variation, e.g. ADD||OPCODE).\n\n"
        f"{fields_block}\n\n"
        "Document excerpts:\n"
        f"{excerpt}"
    )

    payload = openai_chat_json_object(
        system_prompt=_SYSTEM_PROMPT,
        user_message=user_msg,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    return _normalize_mappings(payload, run, allowed)
