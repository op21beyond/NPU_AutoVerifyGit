from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

from src.common.instruction_key import instruction_scope_label, variation_from_catalog_row
from src.common.runtime import StageRun

_RE_BIT_RANGE = re.compile(r"\b(\d{1,2})\s*:\s*(\d{1,2})\b")
_RE_BIT_SINGLE = re.compile(r"\b(\d{1,2})\b")
_RE_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _pages_for_instruction(row: Dict[str, Any]) -> Set[int]:
    pages: Set[int] = set()
    for ref in row.get("source_refs") or []:
        p = ref.get("page")
        if isinstance(p, int) and p >= 1:
            pages.add(p)
    return pages


def _ref_from_block(block: Dict[str, Any]) -> Dict[str, Any]:
    refs = block.get("source_refs") or []
    if refs:
        return dict(refs[0])
    return {"page": block.get("page", 1), "bbox": block.get("bbox", []), "block_id": block.get("block_id")}


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if not line:
        return []
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in re.split(r"\s{2,}", line) if c.strip()]


def _header_indices(header_cells: List[str]) -> Dict[str, int]:
    idx: Dict[str, int] = {}
    for i, c in enumerate(header_cells):
        low = c.lower().strip()
        if any(k in low for k in ("field", "name", "signal")):
            idx.setdefault("field", i)
        if "bits" in low or re.search(r"\bbit\b", low) or re.search(r"msb|lsb|\[", low):
            idx.setdefault("bits", i)
        if "word" in low or low == "w":
            idx.setdefault("word", i)
    return idx


def _parse_field_row(
    cells: List[str],
    col_map: Dict[str, int],
) -> Tuple[str, str, int, float]:
    """Returns field_name, bit_range string, word_index, row_confidence."""
    if not cells:
        return "", "", 0, 0.0

    if col_map.get("field") is not None and col_map.get("bits") is not None:
        fi, bi = col_map["field"], col_map["bits"]
        if fi < len(cells) and bi < len(cells):
            fname = cells[fi].strip()
            bit_cell = cells[bi]
            m = _RE_BIT_RANGE.search(bit_cell)
            if m:
                br = f"{m.group(1)}:{m.group(2)}"
            else:
                m2 = _RE_BIT_SINGLE.search(bit_cell)
                br = m2.group(1) if m2 else ""
            wi = 0
            if col_map.get("word") is not None:
                wi_col = col_map["word"]
                if wi_col < len(cells):
                    m3 = re.search(r"\d+", cells[wi_col])
                    wi = int(m3.group(0)) if m3 else 0
            if fname and _RE_FIELD_NAME.match(fname) and br:
                return fname, br, wi, 0.78
        return "", "", 0, 0.0

    # Heuristic: first cell = name, search other cells for bit range
    fname = cells[0].strip() if cells else ""
    if not fname or not _RE_FIELD_NAME.match(fname):
        return "", "", 0, 0.0
    rest = " ".join(cells[1:])
    m = _RE_BIT_RANGE.search(rest)
    if m:
        return fname, f"{m.group(1)}:{m.group(2)}", 0, 0.62
    m2 = _RE_BIT_SINGLE.search(rest)
    if m2:
        return fname, m2.group(1), 0, 0.48
    return "", "", 0, 0.0


def _parse_table_block(raw_text: str) -> List[Tuple[str, str, int, float]]:
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = _split_row(lines[0])
    col_map = _header_indices(header)
    if col_map.get("field") is not None or col_map.get("bits") is not None:
        data_lines = lines[1:]
    else:
        data_lines = lines
        col_map = {}

    out: List[Tuple[str, str, int, float]] = []
    for line in data_lines:
        cells = _split_row(line)
        if len(cells) < 1:
            continue
        fn, br, wi, cf = _parse_field_row(cells, col_map)
        if fn and br:
            out.append((fn, br, wi, cf))
    return out


def _parse_loose_line(line: str) -> Tuple[str, str, int, float]:
    """Single-line pattern: FIELD 31:28 or FIELD [31:28]."""
    m = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+(\d{1,2}\s*:\s*\d{1,2}|\d{1,2})\b", line)
    if not m:
        return "", "", 0, 0.0
    fname, br_raw = m.group(1), m.group(2)
    br_clean = re.sub(r"\s+", "", br_raw)
    if ":" in br_clean:
        return fname, br_clean, 0, 0.42
    return fname, br_clean, 0, 0.38


def _instructions_for_page(
    page: int,
    instructions: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], bool]:
    """Return instructions whose evidence page matches page±1. uncertain_multi if >1."""
    cands: List[Dict[str, Any]] = []
    for inst in instructions:
        pset = _pages_for_instruction(inst)
        if not pset:
            continue
        for ip in pset:
            if abs(ip - page) <= 1:
                cands.append(inst)
                break
    if len(cands) > 1:
        return cands, True
    if len(cands) == 1:
        return cands, False
    if instructions:
        return [instructions[0]], True
    return [], False


def build_instruction_field_map(
    page_blocks: List[Dict[str, Any]],
    instructions: List[Dict[str, Any]],
    run: StageRun,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not instructions:
        return rows

    block_idx = 0
    for block in page_blocks:
        raw = block.get("raw_text") or ""
        page = int(block.get("page", 1))
        btype = block.get("block_type", "text")
        ref = _ref_from_block(block)

        parsed: List[Tuple[str, str, int, float]] = []
        if btype == "table" and raw.strip():
            parsed = _parse_table_block(raw)
        elif btype in ("text", "equation", "image") and raw.strip():
            for line in raw.splitlines():
                fn, br, wi, cf = _parse_loose_line(line)
                if fn and br:
                    parsed.append((fn, br, wi, cf * 0.85))

        if not parsed:
            block_idx += 1
            continue

        inst_rows, multi = _instructions_for_page(page, instructions)
        if not inst_rows:
            block_idx += 1
            continue

        uncertain = multi or btype != "table"
        for inst in inst_rows:
            iname = str(inst.get("instruction_name", "UNKNOWN")).strip().upper()
            ivar = variation_from_catalog_row(inst)
            scope = instruction_scope_label(iname, ivar)
            for fi, (fname, br, wi, row_cf) in enumerate(parsed):
                base = 0.55 if uncertain else row_cf
                conf = min(0.95, max(0.25, base * (0.9 if multi else 1.0)))
                rows.append(
                    {
                        "trace_id": f"{run.stage_run_id}:field:{block_idx}:{fi}:{scope}",
                        "stage_name": run.stage_name,
                        "stage_run_id": run.stage_run_id,
                        "instruction_name": iname,
                        "variation": ivar,
                        "field_name": fname,
                        "bit_range": br,
                        "word_index": wi,
                        "confidence_score": round(conf, 4),
                        "source_refs": [ref],
                        "uncertain": uncertain or conf < 0.55,
                    }
                )
        block_idx += 1

    return rows
