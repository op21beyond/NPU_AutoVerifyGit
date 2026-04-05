from __future__ import annotations

from typing import Any, Dict, List

from src.common.instruction_key import normalize_variation, variation_from_catalog_row
from src.common.llm_page_blocks import serialize_page_blocks_for_prompt
from src.common.openai_json import openai_chat_json_object
from src.common.runtime import StageRun

_SYSTEM_PROMPT = """You extract allowed value domains for instruction operand/encoding fields from architecture excerpts.
Return ONLY valid JSON (no markdown fences). The JSON must match this shape:
{
  "domains": [
    {
      "instruction_name": "<uppercase>",
      "variation": "<short label or null>",
      "field_name": "<field name>",
      "allowed_value_form": "range" | "enum" | "mask" | "set" | "other",
      "allowed_values_or_range": "<human-readable: interval, enum list, or pattern>",
      "source_page": <integer from excerpt headers>
    }
  ]
}
Rules:
- Cover each field line in the user message; one domain row per field when possible.
- allowed_values_or_range should be concise (e.g. 0..63, or TILE_A|TILE_B).
- source_page must match a page shown in the excerpts.
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


def _normalize_domains(payload: Dict[str, Any], run: StageRun) -> List[Dict[str, Any]]:
    items = payload.get("domains")
    if not isinstance(items, list):
        return []

    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        fn = str(raw.get("field_name", "")).strip()
        if not fn:
            continue
        form = str(raw.get("allowed_value_form", "range")).strip() or "range"
        av = str(raw.get("allowed_values_or_range", "")).strip()
        try:
            page_i = int(raw.get("source_page", 1))
        except (TypeError, ValueError):
            page_i = 1
        out.append(
            {
                "trace_id": f"{run.stage_run_id}:domain:{i}",
                "instruction_name": str(raw.get("instruction_name", "")).strip().upper(),
                "variation": normalize_variation(raw.get("variation")),
                "field_name": fn,
                "allowed_value_form": form,
                "allowed_values_or_range": av,
                "source_refs": [{"page": page_i}],
            }
        )
    return out


def build_field_domain_catalog_openai(
    page_blocks: List[Dict[str, Any]],
    instruction_field_rows: List[Dict[str, Any]],
    run: StageRun,
    *,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> List[Dict[str, Any]]:
    excerpt = serialize_page_blocks_for_prompt(page_blocks)
    fields_block = _field_lines_from_instruction_map(instruction_field_rows)
    user_msg = (
        "Fields to describe (format INSTRUCTION|VAR|FIELD; VAR empty means no variation):\n"
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
    return _normalize_domains(payload, run)
