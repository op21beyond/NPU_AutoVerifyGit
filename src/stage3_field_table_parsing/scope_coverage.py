from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from src.common.instruction_key import catalog_row_key, instruction_scope_label, normalize_variation

# Aligned with field_tables: uncertain rows use conf < 0.55
CONFIDENCE_OK_THRESHOLD = 0.55


def _scope_label_from_row(row: Dict[str, Any]) -> str:
    name = str(row.get("instruction_name") or "").strip().upper()
    var = normalize_variation(row.get("variation"))
    return instruction_scope_label(name, var)


def _catalog_scope_keys(instructions: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Unique (instruction_name, variation_key) pairs in catalog order (first occurrence wins)."""
    seen: Set[Tuple[str, str]] = set()
    out: List[Tuple[str, str]] = []
    for inst in instructions:
        key = catalog_row_key(inst.get("instruction_name"), inst.get("variation"))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _label_scope_key(scope_label: str) -> Tuple[str, str]:
    """Inverse of instruction_scope_label for matching: returns (NAME, '' or VAR)."""
    if "|" in scope_label:
        a, b = scope_label.split("|", 1)
        return (a.strip().upper(), b.strip().upper())
    return (scope_label.strip().upper(), "")


def _row_matches_scope_key(row: Dict[str, Any], key: Tuple[str, str]) -> bool:
    name, var_k = key
    if str(row.get("instruction_name") or "").strip().upper() != name:
        return False
    rv = normalize_variation(row.get("variation"))
    row_v = rv if rv is not None else ""
    return row_v == var_k


def group_rows_by_scope(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        label = _scope_label_from_row(row)
        buckets.setdefault(label, []).append(row)
    return buckets


def classify_scope_rows(scope_rows: List[Dict[str, Any]]) -> str:
    """Return status for a non-empty list of field rows for one instruction scope."""
    if not scope_rows:
        return "missing"
    for r in scope_rows:
        if bool(r.get("uncertain")):
            return "partial_or_uncertain"
        try:
            conf = float(r.get("confidence_score", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        if conf < CONFIDENCE_OK_THRESHOLD:
            return "partial_or_uncertain"
    return "fully_confident"


def build_scope_coverage_summary(
    rows: List[Dict[str, Any]],
    instructions: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Compare instruction field map rows to the instruction catalog (when provided).

    When instructions is None or empty, denominator is derived from unique scopes in ``rows``
    (output-only mode; no ``missing`` scopes).
    """
    by_scope = group_rows_by_scope(rows)

    if instructions:
        keys = _catalog_scope_keys(instructions)
        total = len(keys)
        per_scope: Dict[str, str] = {}
        fully = missing = partial = 0
        for key in keys:
            label = instruction_scope_label(key[0], key[1] if key[1] else None)
            scope_rows = [r for r in rows if _row_matches_scope_key(r, key)]
            if not scope_rows:
                per_scope[label] = "missing"
                missing += 1
                continue
            st = classify_scope_rows(scope_rows)
            per_scope[label] = st
            if st == "fully_confident":
                fully += 1
            else:
                partial += 1

        catalog_labels = {instruction_scope_label(k[0], k[1] if k[1] else None) for k in keys}
        extra_labels = sorted(set(by_scope.keys()) - catalog_labels)

        return {
            "denominator": "catalog",
            "instruction_scopes_total": total,
            "scopes_fully_confident": fully,
            "scopes_missing": missing,
            "scopes_partial_or_uncertain": partial,
            "extra_scopes_in_output_count": len(extra_labels),
            "extra_scopes_in_output": extra_labels,
            "confidence_threshold": CONFIDENCE_OK_THRESHOLD,
            "per_scope_status": per_scope,
        }

    # Output-derived: only scopes that appear in rows
    scopes_sorted = sorted(by_scope.keys(), key=_label_scope_key)
    total = len(scopes_sorted)
    per_scope: Dict[str, str] = {}
    fully = partial = 0
    for label in scopes_sorted:
        st = classify_scope_rows(by_scope[label])
        per_scope[label] = st
        if st == "fully_confident":
            fully += 1
        else:
            partial += 1

    return {
        "denominator": "output_derived",
        "instruction_scopes_total": total,
        "scopes_fully_confident": fully,
        "scopes_missing": 0,
        "scopes_partial_or_uncertain": partial,
        "extra_scopes_in_output_count": 0,
        "extra_scopes_in_output": [],
        "confidence_threshold": CONFIDENCE_OK_THRESHOLD,
        "per_scope_status": per_scope,
        "note": "No instruction catalog; totals are unique scopes present in field map output only.",
    }
