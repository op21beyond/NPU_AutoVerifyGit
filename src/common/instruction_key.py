"""Shared (instruction_name, variation) helpers aligned with Stage 2 instruction_catalog."""

from __future__ import annotations

from typing import Any, Optional, Tuple


def normalize_variation(raw: Any) -> Optional[str]:
    """Empty / missing → None (JSON null in catalog). Else uppercase stripped string."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s.upper()


def catalog_row_key(name: Any, variation: Any) -> Tuple[str, str]:
    """Stable key: (instruction_name upper, variation or '')."""
    n = str(name or "").strip().upper()
    v = normalize_variation(variation)
    return (n, v if v is not None else "")


def instruction_scope_label(instruction_name: str, variation: Optional[str]) -> str:
    """Human/JSON object key: NAME or NAME|VAR when variation is set."""
    n = str(instruction_name or "").strip().upper()
    v = normalize_variation(variation)
    return f"{n}|{v}" if v else n


def variation_from_catalog_row(row: Dict[str, Any]) -> Optional[str]:
    return normalize_variation(row.get("variation"))


def attach_variation_fields(
    out: Dict[str, Any],
    *,
    instruction_name: str,
    variation: Optional[str],
) -> None:
    out["instruction_name"] = str(instruction_name or "").strip().upper()
    out["variation"] = variation  # explicit null in JSON when absent
