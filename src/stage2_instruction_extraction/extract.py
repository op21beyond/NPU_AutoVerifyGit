from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple

from src.common.opcode import parse_opcode_token
from src.common.runtime import StageRun


_EXCLUDE_NAMES: Set[str] = {
    "THE",
    "AND",
    "FOR",
    "NOT",
    "ARE",
    "BUT",
    "ALL",
    "CAN",
    "HAS",
    "HAD",
    "WAS",
    "ITS",
    "MAY",
    "ONE",
    "OUR",
    "OUT",
    "NEW",
    "WAY",
    "WHO",
    "BIT",
    "BITS",
    "BYTE",
    "WORD",
    "DWORD",
    "FIELD",
    "FIELDS",
    "NAME",
    "TYPE",
    "TABLE",
    "FIGURE",
    "NOTE",
    "SEE",
    "PAGE",
    "SECTION",
    "CHAPTER",
    "THIS",
    "THAT",
    "WITH",
    "FROM",
    "INTO",
    "THAN",
    "WHEN",
    "EACH",
    "USED",
    "USES",
    "TRUE",
    "FALSE",
    "NULL",
    "NONE",
    "UNKNOWN",
    "NPU",
    "ISA",
    "TRM",
    "PDF",
    "ROW",
    "ROWS",
    "CELL",
    "HEADER",
    "VALUE",
    "VALUES",
    "RANGE",
    "MASK",
    "SIZE",
    "WIDTH",
    "HIGH",
    "LOW",
    "MSB",
    "LSB",
    "HEX",
    "DEC",
    "BIN",
    "OPCODE",
    "INST",
    "INSTRUCTION",
    "MACRO",
    "MICRO",
    "UNIT",
    "EXECUTION",
    "FORMAT",
    "DATA",
    "ADDR",
    "ADDRESS",
}

_RE_NAME_OPCODE_PAREN = re.compile(
    r"\b([A-Z][A-Z0-9_]{1,47})\s*\(\s*(0[xX][0-9A-Fa-f]+|\d{1,9})\s*\)"
)
_RE_OPCODE_DASH_NAME = re.compile(
    r"\b(0[xX][0-9A-Fa-f]+|\d{1,9})\s*[-–—]\s*([A-Z][A-Z0-9_]{1,47})\b"
)
_RE_NAME_EQ_OPCODE = re.compile(
    r"(?im)^\s*([A-Z][A-Z0-9_]{1,47})\s*[=:]\s*(0[xX][0-9A-Fa-f]+|\d{1,9})\s*$"
)
_RE_TABLE_TWO_COL = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?:\t|\s{2,})\s*(0[xX][0-9A-Fa-f]+|\d{1,9})\s*$"
)
_RE_EXEC_UNIT = re.compile(
    r"(?i)\b(?:execution\s+unit|exec\.?\s*unit|EU|cluster|engine)\s*[:=]\s*([A-Za-z][A-Za-z0-9_]*)"
)


def _ref_from_block(block: Dict[str, Any]) -> Dict[str, Any]:
    refs = block.get("source_refs") or []
    if refs:
        return dict(refs[0])
    page = block.get("page", 1)
    bbox = block.get("bbox", [])
    return {"page": page, "bbox": bbox, "block_id": block.get("block_id")}


def _valid_instruction_name(name: str) -> bool:
    n = name.strip()
    if len(n) < 2 or len(n) > 48:
        return False
    if not (n[0].isalpha() and n[0].isupper()):
        return False
    nu = n.upper()
    if nu in _EXCLUDE_NAMES:
        return False
    if nu.isdigit():
        return False
    return True


@dataclass
class RawHit:
    instruction_name: str
    opcode_raw: str
    source_ref: Dict[str, Any]
    base_confidence: float
    context_snippet: str = ""
    block_text: str = ""


def _hits_from_text(text: str, source_ref: Dict[str, Any], base_conf: float) -> List[RawHit]:
    hits: List[RawHit] = []
    if not text or not text.strip():
        return hits

    for m in _RE_NAME_OPCODE_PAREN.finditer(text):
        name, opc = m.group(1), m.group(2)
        if _valid_instruction_name(name):
            hits.append(
                RawHit(
                    instruction_name=name.upper(),
                    opcode_raw=opc.strip(),
                    source_ref=source_ref,
                    base_confidence=base_conf + 0.08,
                    context_snippet=text[max(0, m.start() - 20) : m.end() + 20],
                )
            )

    for m in _RE_OPCODE_DASH_NAME.finditer(text):
        opc, name = m.group(1), m.group(2)
        if _valid_instruction_name(name):
            hits.append(
                RawHit(
                    instruction_name=name.upper(),
                    opcode_raw=opc.strip(),
                    source_ref=source_ref,
                    base_confidence=base_conf + 0.05,
                    context_snippet=text[max(0, m.start() - 20) : m.end() + 20],
                )
            )

    for line in text.splitlines():
        stripped = line.strip()
        m = _RE_NAME_EQ_OPCODE.match(stripped)
        if m:
            name, opc = m.group(1), m.group(2)
            if _valid_instruction_name(name):
                hits.append(
                    RawHit(
                        instruction_name=name.upper(),
                        opcode_raw=opc.strip(),
                        source_ref=source_ref,
                        base_confidence=base_conf + 0.06,
                        context_snippet=stripped[:120],
                    )
                )
        m2 = _RE_TABLE_TWO_COL.match(stripped)
        if m2:
            name, opc = m2.group(1), m2.group(2)
            if _valid_instruction_name(name.upper()):
                hits.append(
                    RawHit(
                        instruction_name=name.upper(),
                        opcode_raw=opc.strip(),
                        source_ref=source_ref,
                        base_confidence=base_conf + 0.04,
                        context_snippet=stripped[:120],
                    )
                )

    return hits


def _infer_execution_unit(text: str) -> str:
    m = _RE_EXEC_UNIT.search(text)
    if m:
        return m.group(1).strip()
    return "UNKNOWN_UNIT"


def _infer_instruction_kind(text: str) -> Tuple[str, float]:
    t = text.lower()
    if "macro" in t and "micro" not in t:
        return "macro", 0.45
    if "micro" in t and "macro" not in t:
        return "micro", 0.45
    return "unknown", 0.35


def extract_instruction_hits(page_blocks: List[Dict[str, Any]]) -> List[RawHit]:
    all_hits: List[RawHit] = []
    for block in page_blocks:
        raw_text = block.get("raw_text") or ""
        ref = _ref_from_block(block)
        method = block.get("extraction_method", "")
        base = 0.62 if method == "text_layer" else 0.55
        if block.get("block_type") == "table":
            base += 0.05
        for h in _hits_from_text(raw_text, ref, base):
            h.block_text = raw_text
            all_hits.append(h)
    return all_hits


def _merge_hits(hits: List[RawHit], run: StageRun) -> List[Dict[str, Any]]:
    best: Dict[str, RawHit] = {}
    for h in sorted(hits, key=lambda x: x.base_confidence, reverse=True):
        key = h.instruction_name
        if key not in best:
            best[key] = h
            continue
        cur = best[key]
        ov_new, _ = parse_opcode_token(h.opcode_raw)
        ov_old, _ = parse_opcode_token(cur.opcode_raw)
        if ov_new is not None and ov_old is None:
            best[key] = h
        elif h.base_confidence > cur.base_confidence + 0.02:
            best[key] = h

    rows: List[Dict[str, Any]] = []
    for idx, h in enumerate(sorted(best.values(), key=lambda x: x.instruction_name)):
        opc_val, opc_radix = parse_opcode_token(h.opcode_raw)
        ctx = (h.block_text or "") + "\n" + (h.context_snippet or "")
        eu = _infer_execution_unit(ctx)
        kind, kconf = _infer_instruction_kind(ctx)

        conf = min(0.97, max(0.35, h.base_confidence))
        if opc_val is None:
            conf *= 0.85

        rows.append(
            {
                "trace_id": f"{run.stage_run_id}:instr:{idx}",
                "stage_name": run.stage_name,
                "stage_run_id": run.stage_run_id,
                "instruction_name": h.instruction_name,
                "aliases": [],
                "opcode_raw": h.opcode_raw,
                "opcode_radix": opc_radix,
                "opcode_value": opc_val,
                "execution_unit": eu,
                "instruction_kind": kind,
                "instruction_kind_confidence": round(kconf, 4),
                "confidence_score": round(conf, 4),
                "source_refs": [h.source_ref],
            }
        )
    return rows


def build_instruction_catalog(page_blocks: List[Dict[str, Any]], run: StageRun) -> List[Dict[str, Any]]:
    hits = extract_instruction_hits(page_blocks)
    if not hits:
        return []
    return _merge_hits(hits, run)
