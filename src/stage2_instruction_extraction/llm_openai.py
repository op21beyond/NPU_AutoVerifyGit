from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.opcode import parse_opcode_token
from src.common.runtime import StageRun
from src.common.instruction_key import catalog_row_key, normalize_variation

_SYSTEM_PROMPT = """You extract NPU/ISA instruction entries from architecture document excerpts.
Return ONLY valid JSON (no markdown fences). The JSON must match this shape:
{
  "instructions": [
    {
      "instruction_name": "<logical family name, uppercase, e.g. RESCALE>",
      "variation": "<short label or null>",
      "opcode_raw": "<verbatim opcode string from doc, e.g. 0x2A or 42>",
      "aliases": ["<optional: family aliases + variation-specific mnemonics, e.g. RESCALE_CW>"],
      "execution_unit": "<hardware block name if stated, else UNKNOWN_UNIT>",
      "instruction_kind": "macro" | "micro" | "unknown",
      "instruction_kind_confidence": <number 0..1>,
      "confidence_score": <number 0..1 for this extraction>,
      "source_page": <integer page number where this instruction is evidenced>
    }
  ]
}
Rules:
- instruction_name is the shared logical instruction (one family). If the document uses distinct mnemonics for the same opcode with different field layouts (e.g. RESCALE_CW vs RESCALE_GW for channelwise vs groupwise), use the SAME instruction_name (e.g. RESCALE), set variation to a short discriminator (e.g. CW, GW), and list document mnemonics in aliases.
- If there is only one form, set variation to null and still list surface names in aliases when helpful.
- Include only real instruction-like entities (opcodes / instruction mnemonics), not generic English words.
- If opcode is unclear, set opcode_raw to "UNKNOWN" and keep confidence_score low.
- source_page must match one of the page numbers shown in the excerpt headers.
- Prefer fewer, higher-quality rows over noisy duplicates. Emit separate rows for different (instruction_name, variation) pairs.
"""


def _serialize_blocks_for_prompt(page_blocks: List[Dict[str, Any]], max_total_chars: int = 100_000) -> str:
    chunks: List[str] = []
    used = 0
    for b in page_blocks:
        page = b.get("page", "?")
        bid = b.get("block_id", "?")
        btype = b.get("block_type", "?")
        raw = (b.get("raw_text") or "").strip()
        if not raw:
            continue
        cap = 8000
        if used + len(raw) > max_total_chars:
            cap = max(0, max_total_chars - used)
            raw = raw[:cap] + ("\n...[truncated]" if len(raw) > cap else "")
        header = f"--- page={page} block_id={bid} type={btype} ---\n"
        piece = header + raw + "\n"
        if used + len(piece) > max_total_chars:
            break
        chunks.append(piece)
        used += len(piece)
    return "\n".join(chunks) if chunks else "(no text blocks)"


def _clamp_kind(raw: Any) -> str:
    s = str(raw or "").lower().strip()
    if s in ("macro", "micro", "unknown"):
        return s
    return "unknown"


def _clamp01(x: Any, default: float = 0.5) -> float:
    try:
        v = float(x)
        return max(0.0, min(1.0, v))
    except (TypeError, ValueError):
        return default


def _normalize_rows_from_llm(
    payload: Dict[str, Any],
    run: StageRun,
) -> List[Dict[str, Any]]:
    items = payload.get("instructions")
    if not isinstance(items, list):
        return []

    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("instruction_name", "")).strip().upper()
        if not name or len(name) > 64:
            continue
        var = normalize_variation(raw.get("variation"))
        opc_raw = str(raw.get("opcode_raw", "UNKNOWN")).strip() or "UNKNOWN"
        page = raw.get("source_page")
        try:
            page_i = int(page)
        except (TypeError, ValueError):
            page_i = 1

        row = {
            "instruction_name": name,
            "variation": var,
            "opcode_raw": opc_raw,
            "aliases": [str(a).strip() for a in (raw.get("aliases") or []) if str(a).strip()],
            "execution_unit": str(raw.get("execution_unit", "UNKNOWN_UNIT")).strip() or "UNKNOWN_UNIT",
            "instruction_kind": _clamp_kind(raw.get("instruction_kind")),
            "instruction_kind_confidence": _clamp01(raw.get("instruction_kind_confidence"), 0.35),
            "confidence_score": _clamp01(raw.get("confidence_score"), 0.6),
            "source_refs": [{"page": page_i}],
        }
        key = catalog_row_key(name, var)
        if key not in merged:
            merged[key] = row
            continue
        cur = merged[key]
        if row["confidence_score"] > cur["confidence_score"] + 0.01:
            merged[key] = row

    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(
        sorted(
            merged.values(),
            key=lambda r: (r["instruction_name"], r.get("variation") or ""),
        )
    ):
        opc_val, opc_radix = parse_opcode_token(row["opcode_raw"])
        out.append(
            {
                "trace_id": f"{run.stage_run_id}:instr:{idx}",
                "stage_name": run.stage_name,
                "stage_run_id": run.stage_run_id,
                "instruction_name": row["instruction_name"],
                "variation": row.get("variation"),
                "aliases": row["aliases"],
                "opcode_raw": row["opcode_raw"],
                "opcode_radix": opc_radix,
                "opcode_value": opc_val,
                "execution_unit": row["execution_unit"],
                "instruction_kind": row["instruction_kind"],
                "instruction_kind_confidence": round(row["instruction_kind_confidence"], 4),
                "confidence_score": round(row["confidence_score"], 4),
                "source_refs": row["source_refs"],
            }
        )
    return out


def build_instruction_catalog_openai(
    page_blocks: List[Dict[str, Any]],
    run: StageRun,
    *,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_s: float = 120.0,
) -> List[Dict[str, Any]]:
    """
    Extract instructions via OpenAI Chat Completions (JSON object mode).
    API key: OPENAI_API_KEY env, or pass api_key= (tests only; prefer env).
    """
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it or pass api_key= for OpenAI extraction mode."
        )

    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "The 'openai' package is required for Stage2 LLM extraction. Install: pip install openai"
        ) from e

    excerpt = _serialize_blocks_for_prompt(page_blocks)
    user_msg = (
        "Extract instruction catalog entries from the following document excerpts.\n\n" + excerpt
    )

    client_kwargs: Dict[str, Any] = {"api_key": key, "timeout": timeout_s}
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")

    client = OpenAI(**client_kwargs)
    completion = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )
    text = completion.choices[0].message.content or "{}"
    text = re.sub(r"^\s*```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```\s*$", "", text.strip())
    payload = json.loads(text)
    if not isinstance(payload, dict):
        return []
    return _normalize_rows_from_llm(payload, run)
