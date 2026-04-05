"""OpenAI helpers: constraint sentence extraction, category normalization, value extraction."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.common.llm_page_blocks import serialize_page_blocks_for_prompt
from src.common.openai_json import openai_chat_json_object
from src.common.runtime import StageRun

_EXTRACT_SYSTEM = """You analyze NPU/ISA architecture document excerpts.
Find sentences or short clauses that state CONSTRAINTS on instructions or their operand/encoding fields
(e.g. reserved encodings, alignment requirements, invalid combinations, timing or resource limits stated as rules).
Return ONLY valid JSON:
{
  "items": [
    {
      "verbatim_sentence": "<quote or tight paraphrase from the excerpt>",
      "constraint_category_candidate": "<short English label for the kind of rule, e.g. encoding_range, alignment>",
      "constraint_content": "<one-sentence paraphrase of what must hold>",
      "source_page": <integer matching --- page=... --- headers>,
      "instruction_name": "<UPPERCASE family name if clearly tied, else null>",
      "field_name": "<field name if clearly tied, else null>"
    }
  ]
}
Rules:
- Include only substantive constraints, not generic descriptions of what an instruction does without a rule.
- If nothing qualifies, return { "items": [] }.
"""

_NORMALIZE_SYSTEM = """You are given a SET of short labels that came from earlier automated extraction passes over the same architecture document.
The same semantic category may appear under different phrasings (e.g. "field_value_range" vs "allowed_value_range" vs "encoding_range", or "enum_allowed_values" vs "field_permitted_values").
Do NOT use string-edit distance or ad-hoc rules — use your understanding of NPU/ISA constraints to merge synonyms into a SMALL, STABLE taxonomy.

Task:
1. Cluster labels that mean the same kind of constraint.
2. Choose one clear canonical name per cluster (prefer short snake_case, e.g. value_range, enum_domain, alignment, reserved_encoding).
3. Map EVERY input label exactly once to exactly one canonical label.

Return ONLY valid JSON:
{
  "canonical_categories": ["<sorted unique canonical labels>"],
  "mapping": { "<exact string as it appeared in the input list>": "<canonical label>" },
  "merge_rationale": "<optional one-sentence summary of major merges>"
}

Rules:
- Every string in the input JSON array must appear as a key in "mapping" (exact match, case-sensitive).
- "canonical_categories" must list each distinct canonical label you used, sorted.
- If the input has only one label, still return mapping with that label mapped to a cleaned canonical form if appropriate.
"""

_VALUES_SYSTEM = """You extract concrete attribute VALUES for ontology entities mentioned in the document excerpts.
The user message lists target nodes (id, type, name) and the document text.
Return ONLY valid JSON:
{
  "bindings": [
    {
      "node_id": "<must match an id from the target list>",
      "property": "<short property key, e.g. opcode_value, tile_format>",
      "value": "<string or number as string>",
      "source_page": <integer>
    }
  ]
}
Only emit bindings explicitly supported by the excerpts; otherwise return { "bindings": [] }.
"""


def extract_constraint_candidates_openai(
    page_blocks: List[Dict[str, Any]],
    run: StageRun,
    *,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    excerpt = serialize_page_blocks_for_prompt(page_blocks)
    user_msg = "Document excerpts:\n\n" + excerpt
    payload = openai_chat_json_object(
        system_prompt=_EXTRACT_SYSTEM,
        user_message=user_msg,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append(
            {
                "verbatim_sentence": str(it.get("verbatim_sentence", "")).strip(),
                "constraint_category_candidate": str(it.get("constraint_category_candidate", "")).strip(),
                "constraint_content": str(it.get("constraint_content", "")).strip(),
                "source_page": _safe_int(it.get("source_page"), 1),
                "instruction_name": _null_str(it.get("instruction_name")),
                "field_name": _null_str(it.get("field_name")),
            }
        )
    return out


def _safe_int(x: Any, default: int) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _null_str(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s.upper() if s else None


def normalize_constraint_categories_openai(
    candidate_labels: List[str],
    run: StageRun,
    *,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    extra_labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Second LLM pass only: merge synonym / near-duplicate category phrases into a canonical taxonomy.
    No fuzzy-match heuristics in code — only dedupe exact strings before the call.
    """
    raw: List[str] = list(candidate_labels)
    if extra_labels:
        raw.extend(extra_labels)
    labels = sorted({str(c).strip() for c in raw if str(c).strip()})
    if not labels:
        return {"canonical_categories": [], "mapping": {}, "merge_rationale": None}

    user_msg = (
        "The following JSON array lists ALL distinct category labels collected from prior extraction outputs "
        "(and optional field-domain metadata). Merge semantically equivalent labels into canonical categories.\n\n"
        + json.dumps(labels, ensure_ascii=False)
    )
    payload = openai_chat_json_object(
        system_prompt=_NORMALIZE_SYSTEM,
        user_message=user_msg,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    mapping = payload.get("mapping")
    cats = payload.get("canonical_categories")
    rationale = payload.get("merge_rationale")
    if not isinstance(mapping, dict):
        mapping = {}
    if not isinstance(cats, list):
        cats = []
    # Safety: if the model omitted a key, keep identity (does not invent semantics; avoids broken downstream keys)
    for lb in labels:
        if lb not in mapping:
            mapping[lb] = lb
    out: Dict[str, Any] = {
        "canonical_categories": [str(c) for c in cats],
        "mapping": mapping,
    }
    if rationale is not None:
        out["merge_rationale"] = str(rationale)
    return out


def extract_ontology_values_openai(
    page_blocks: List[Dict[str, Any]],
    ontology_nodes: List[Dict[str, Any]],
    run: StageRun,
    *,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    max_nodes: int = 80,
) -> List[Dict[str, Any]]:
    excerpt = serialize_page_blocks_for_prompt(page_blocks)
    nodes = ontology_nodes[:max_nodes]
    user_msg = (
        "Target ontology nodes (JSON array, use node_id in bindings):\n"
        + json.dumps(nodes, ensure_ascii=False)
        + "\n\nDocument excerpts:\n\n"
        + excerpt
    )
    payload = openai_chat_json_object(
        system_prompt=_VALUES_SYSTEM,
        user_message=user_msg,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    binds = payload.get("bindings")
    if not isinstance(binds, list):
        return []
    out: List[Dict[str, Any]] = []
    for b in binds:
        if not isinstance(b, dict):
            continue
        nid = str(b.get("node_id", "")).strip()
        if not nid:
            continue
        out.append(
            {
                "node_id": nid,
                "property": str(b.get("property", "")).strip(),
                "value": str(b.get("value", "")).strip(),
                "source_page": _safe_int(b.get("source_page"), 1),
            }
        )
    return out


def llm_items_to_constraint_rows(
    items: List[Dict[str, Any]],
    category_mapping: Dict[str, str],
    run: StageRun,
    start_index: int = 0,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, it in enumerate(items):
        cand = it.get("constraint_category_candidate") or "unknown"
        canon = category_mapping.get(cand, cand)
        if not str(canon).strip():
            canon = "unknown"
        cid = f"C_LLM_{start_index + i:04d}"
        expr = it.get("constraint_content") or it.get("verbatim_sentence") or ""
        fn = it.get("field_name")
        ins = it.get("instruction_name")
        applies: Dict[str, Any]
        if fn:
            applies = {"entity_type": "Field", "entity_name": str(fn).strip()}
        elif ins:
            applies = {"entity_type": "Instruction", "entity_name": str(ins).strip()}
        else:
            applies = {"entity_type": "Document", "entity_name": "GLOBAL"}
        page = _safe_int(it.get("source_page"), 1)
        rows.append(
            {
                "trace_id": f"{run.stage_run_id}:c:llm:{start_index + i}",
                "constraint_id": cid,
                "constraint_type_level1": str(canon).replace(" ", "_")[:64],
                "constraint_type_level2": "llm-document",
                "expression": str(expr)[:2000],
                "classification_rationale": f"LLM extraction; candidate={cand}",
                "source_refs": [{"page": page}],
                "applies_to": applies,
                "verbatim_sentence": it.get("verbatim_sentence"),
            }
        )
    return rows
