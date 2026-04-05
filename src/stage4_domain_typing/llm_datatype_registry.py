from __future__ import annotations

import re
from typing import Any, Dict, List

from src.common.llm_page_blocks import serialize_page_blocks_for_prompt
from src.common.openai_json import openai_chat_json_object
from src.common.runtime import StageRun

_SYSTEM_PROMPT = """You extract NPU/ISA data type definitions from architecture document excerpts.
Return ONLY valid JSON (no markdown fences). The JSON must match this shape:
{
  "types": [
    {
      "type_id": "<unique slug, uppercase letters, digits, underscore, e.g. UINT6 or NPU_TILE_FMT>",
      "type_name_raw": "<verbatim name or phrase from the document>",
      "category": "software_primitive" | "ip_architecture" | "alias" | "unknown",
      "description": "<short description of what the type represents>",
      "value_constraint_summary": "<e.g. unsigned 6-bit 0..63, or enum values>",
      "source_page": <integer page number from the excerpt headers>
    }
  ]
}
Rules:
- Include types explicitly defined or named in the excerpts (enumerations, typedefs, bit-width integers, IP-specific formats).
- type_id must be stable and unique; prefer document naming when clear.
- source_page must match one of the page numbers shown in --- page=... --- headers.
- Omit duplicate type_id; merge synonyms into one row with aliases in description if needed.
- If no types are found, return { "types": [] }.
"""


def _clamp_category(raw: Any) -> str:
    s = str(raw or "").lower().strip()
    if s in ("software_primitive", "ip_architecture", "alias", "unknown"):
        return s
    return "unknown"


def _norm_type_id(s: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]+", "_", (s or "").strip().upper())
    return t.strip("_") or "UNKNOWN_TYPE"


def _normalize_types_from_llm(payload: Dict[str, Any], run: StageRun) -> List[Dict[str, Any]]:
    items = payload.get("types")
    if not isinstance(items, list):
        return []

    merged: Dict[str, Dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        tid = _norm_type_id(str(raw.get("type_id", "")))
        if not tid or tid == "UNKNOWN_TYPE":
            continue
        try:
            page_i = int(raw.get("source_page", 1))
        except (TypeError, ValueError):
            page_i = 1
        row = {
            "type_id": tid,
            "type_name_raw": str(raw.get("type_name_raw", tid)).strip() or tid,
            "type_name_normalized": tid,
            "category": _clamp_category(raw.get("category")),
            "description": str(raw.get("description", "")).strip(),
            "value_constraint_summary": str(raw.get("value_constraint_summary", "")).strip(),
            "value_generation_method": "",
            "source_refs": [{"page": page_i}],
        }
        if tid not in merged:
            merged[tid] = row

    out: List[Dict[str, Any]] = []
    for idx, tid in enumerate(sorted(merged.keys())):
        r = dict(merged[tid])
        r["trace_id"] = f"{run.stage_run_id}:reg:{idx}"
        out.append(r)
    return out


def build_datatype_registry_openai(
    page_blocks: List[Dict[str, Any]],
    run: StageRun,
    *,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    excerpt = serialize_page_blocks_for_prompt(page_blocks)
    user_msg = (
        "List all distinct data types defined or referenced in the following document excerpts.\n\n" + excerpt
    )
    payload = openai_chat_json_object(
        system_prompt=_SYSTEM_PROMPT,
        user_message=user_msg,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    return _normalize_types_from_llm(payload, run)
