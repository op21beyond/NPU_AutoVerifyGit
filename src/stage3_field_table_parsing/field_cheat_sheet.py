"""
Optional JSON cheat sheet: per-instruction-scope field encodings when table heuristics fail.

Top-level keys: instruction scope labels (NAME or NAME|VAR), same as instruction_scope_label.
Each value: { "fields": [ { "field_name", "bit_range", "word_index" }, ... ] }
Keys starting with "_" are ignored (comments).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from src.common.instruction_key import instruction_scope_label, variation_from_catalog_row
from src.common.runtime import StageRun


def load_field_cheat_sheet(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Field cheat sheet not found: {path}")
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Cheat sheet must be a JSON object")
    out: Dict[str, Any] = {}
    for k, v in data.items():
        ks = str(k).strip()
        if ks.startswith("_"):
            continue
        out[ks.strip().upper()] = v
    return out


def _primary_page(inst: Dict[str, Any]) -> int:
    for ref in inst.get("source_refs") or []:
        p = ref.get("page")
        if isinstance(p, int) and p >= 1:
            return p
    return 1


def _field_rows_from_cheat(
    cheat_key_used: str,
    inst: Dict[str, Any],
    fields: List[Dict[str, Any]],
    run: StageRun,
) -> List[Dict[str, Any]]:
    iname = str(inst.get("instruction_name", "")).strip().upper()
    ivar = variation_from_catalog_row(inst)
    page = _primary_page(inst)
    ref = {"page": page, "method": "field_cheat_sheet", "cheat_sheet_key": cheat_key_used}
    rows: List[Dict[str, Any]] = []
    for fi, f in enumerate(fields):
        if not isinstance(f, dict):
            continue
        fn = str(f.get("field_name", "")).strip()
        br = str(f.get("bit_range", "")).strip()
        if not fn or not br:
            continue
        try:
            wi = int(f.get("word_index", 0) or 0)
        except (TypeError, ValueError):
            wi = 0
        scope = instruction_scope_label(iname, ivar)
        rows.append(
            {
                "trace_id": f"{run.stage_run_id}:field:cheat:{scope}:{fi}",
                "stage_name": run.stage_name,
                "stage_run_id": run.stage_run_id,
                "instruction_name": iname,
                "variation": ivar,
                "field_name": fn,
                "bit_range": br,
                "word_index": wi,
                "confidence_score": 0.95,
                "source_refs": [ref],
                "uncertain": False,
            }
        )
    return rows


def apply_field_cheat_sheet(
    heuristic_rows: List[Dict[str, Any]],
    instructions: List[Dict[str, Any]],
    cheat: Dict[str, Any],
    run: StageRun,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    For each catalog instruction scope:
    - If cheat has an entry (exact NAME|VAR, or NAME-only fallback when variation is set), replace
      heuristic rows for that scope with cheat rows.
    - Otherwise keep heuristic rows for that scope.
    - Heuristic rows whose scope is not in the catalog are appended unchanged.

    Returns (merged_rows, warning_messages).
    """
    warnings: List[str] = []

    by_scope: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in heuristic_rows:
        iname = str(r.get("instruction_name", "UNKNOWN")).strip().upper()
        ivar = variation_from_catalog_row(r)
        sk = instruction_scope_label(iname, ivar)
        by_scope[sk].append(r)

    # Overlap NAME vs NAME|VAR
    for k in cheat:
        if "|" not in k:
            continue
        base = k.split("|", 1)[0].strip()
        if base in cheat and base != k:
            warnings.append(
                f"cheat_sheet_ambiguous_keys: both {base!r} and {k!r} exist; "
                f"matching uses the most specific key first, then NAME-only fallback."
            )
            break

    unique_scopes: List[Tuple[str, Dict[str, Any]]] = []
    seen: Set[str] = set()
    for inst in instructions:
        name = str(inst.get("instruction_name", "")).strip().upper()
        var = variation_from_catalog_row(inst)
        sk = instruction_scope_label(name, var)
        if sk not in seen:
            seen.add(sk)
            unique_scopes.append((sk, inst))

    catalog_scopes = {sk for sk, _ in unique_scopes}
    merged: List[Dict[str, Any]] = []

    for sk, inst in unique_scopes:
        name = str(inst.get("instruction_name", "")).strip().upper()
        var = variation_from_catalog_row(inst)

        entry: Any = None
        key_used: str | None = None
        if sk in cheat:
            entry = cheat[sk]
            key_used = sk
        elif var is not None:
            base_only = instruction_scope_label(name, None)
            if base_only in cheat:
                entry = cheat[base_only]
                key_used = base_only
                warnings.append(
                    f"cheat_sheet_variation_fallback: scope {sk!r} used base key {base_only!r}"
                )

        if entry is not None:
            if not isinstance(entry, dict):
                warnings.append(f"cheat_sheet_invalid_entry: key {key_used!r} is not an object; keeping heuristics")
                merged.extend(by_scope.get(sk, []))
                if not by_scope.get(sk):
                    warnings.append(f"cheat_sheet_missing_rows: scope {sk!r} has no heuristic rows and invalid cheat entry")
                continue
            fields = entry.get("fields")
            if not isinstance(fields, list) or not fields:
                warnings.append(f"cheat_sheet_empty_fields: key {key_used!r}; keeping heuristic rows for {sk!r}")
                merged.extend(by_scope.get(sk, []))
                continue
            cheat_rows = _field_rows_from_cheat(key_used or sk, inst, fields, run)
            if not cheat_rows:
                warnings.append(f"cheat_sheet_no_valid_fields: key {key_used!r}; keeping heuristics for {sk!r}")
                merged.extend(by_scope.get(sk, []))
            else:
                merged.extend(cheat_rows)
        else:
            merged.extend(by_scope.get(sk, []))
            if not by_scope.get(sk):
                warnings.append(f"cheat_sheet_missing: no entry for catalog scope {sk!r} and no heuristic rows")

    for sk, rows in by_scope.items():
        if sk not in catalog_scopes:
            merged.extend(rows)

    return merged, warnings
