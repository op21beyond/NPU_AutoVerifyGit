from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.common.instruction_key import normalize_variation
from src.common.runtime import StageRun


def _norm_inst_name(s: str) -> str:
    return (s or "").strip().upper()


def _norm_field_name(s: str) -> str:
    # Normalize into the same "canonical-ish" style used by stage3b (spaces -> underscore).
    x = (s or "").strip()
    x = re.sub(r"\s+", "_", x)
    return x.upper()


def _norm_bit_range(s: str) -> str:
    x = (s or "").strip()
    x = x.replace(" ", "")
    return x


def _looks_like_bit_token(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    if re.match(r"^\d{1,2}:\d{1,2}$", s):
        return True
    if re.match(r"^\d{1,2}$", s):
        return True
    return False


def _parse_instruction_field_text_line(line: str) -> Optional[Dict[str, Any]]:
    """
    - INSTR FIELD [BITS]
    - INSTR VAR FIELD BITS   (four or more tokens; fourth token is bit range)
    - INSTR VAR FIELD        (three tokens; third is not a bit token — field without bit range)
    """
    parts = re.split(r"\s+", line.strip())
    if len(parts) < 2:
        return None
    if len(parts) >= 4 and _looks_like_bit_token(parts[3]):
        return {
            "instruction_name": _norm_inst_name(parts[0]),
            "variation": normalize_variation(parts[1]),
            "field_name": _norm_field_name(parts[2]),
            "bit_range": _norm_bit_range(parts[3]),
        }
    if len(parts) >= 3 and _looks_like_bit_token(parts[2]):
        return {
            "instruction_name": _norm_inst_name(parts[0]),
            "variation": None,
            "field_name": _norm_field_name(parts[1]),
            "bit_range": _norm_bit_range(parts[2]),
        }
    if len(parts) == 3:
        return {
            "instruction_name": _norm_inst_name(parts[0]),
            "variation": normalize_variation(parts[1]),
            "field_name": _norm_field_name(parts[2]),
        }
    if len(parts) == 2:
        return {
            "instruction_name": _norm_inst_name(parts[0]),
            "variation": None,
            "field_name": _norm_field_name(parts[1]),
        }
    return None


def load_instruction_field_ground_truth(path: Path) -> List[Dict[str, Any]]:
    """
    Supported formats:
    - .txt / .lst / .list: one record per line.
        * INSTR FIELD [BIT_RANGE]
        * INSTR VAR FIELD BIT_RANGE  (when four+ tokens and last of first four is a bit pattern)
    - .json / .jsonl: objects with instruction_name, field_name, optional variation, bit_range, ...
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")

    if suffix in (".txt", ".lst", ".list"):
        out: List[Dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = _parse_instruction_field_text_line(line)
            if parsed:
                out.append(parsed)
        return out

    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            if not data:
                return []
            if all(isinstance(x, str) for x in data):
                # Not enough info for field eval; return empty.
                return []
            if all(isinstance(x, dict) for x in data):
                return _normalize_gt_objects(data)
        raise ValueError("GT .json must be an array of objects (instruction_name/field_name)")

    if suffix == ".jsonl":
        out: List[Dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            if isinstance(obj, str):
                continue
            if isinstance(obj, dict):
                out.extend(_normalize_gt_objects([obj]))
        return out

    raise ValueError(f"Unsupported ground-truth extension: {suffix}")


def _normalize_gt_objects(objs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for o in objs:
        inst = o.get("instruction_name") or o.get("instruction") or o.get("inst")
        field = o.get("field_name") or o.get("field")
        if not inst or not field:
            continue
        row: Dict[str, Any] = {
            "instruction_name": _norm_inst_name(str(inst)),
            "field_name": _norm_field_name(str(field)),
            "variation": normalize_variation(o.get("variation")),
        }
        if o.get("bit_range") is not None:
            row["bit_range"] = _norm_bit_range(str(o.get("bit_range")))
        if o.get("word_index") is not None:
            try:
                row["word_index"] = int(o.get("word_index"))
            except (TypeError, ValueError):
                pass
        if o.get("uncertain") is not None:
            row["uncertain"] = bool(o.get("uncertain"))
        out.append(row)
    return out


def build_instruction_field_map_from_ground_truth(
    gt_rows: List[Dict[str, Any]],
    run: StageRun,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, gt in enumerate(gt_rows):
        inst = _norm_inst_name(str(gt.get("instruction_name", "")))
        field = _norm_field_name(str(gt.get("field_name", "")))
        bit_range = _norm_bit_range(str(gt.get("bit_range", ""))) if gt.get("bit_range") else ""
        word_index = gt.get("word_index", 0) or 0
        uncertain = bool(gt.get("uncertain", False))
        var = normalize_variation(gt.get("variation"))
        rows.append(
            {
                "trace_id": f"{run.stage_run_id}:field:gt:{idx}",
                "stage_name": run.stage_name,
                "stage_run_id": run.stage_run_id,
                "instruction_name": inst,
                "variation": var,
                "field_name": field,
                "bit_range": bit_range,
                "word_index": int(word_index),
                "confidence_score": 1.0,
                "source_refs": [{"method": "ground_truth_field_map", "ground_truth": True}],
                "uncertain": uncertain,
            }
        )
    return rows


def evaluate_instruction_field_map_extraction(
    pred_rows: List[Dict[str, Any]],
    gt_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Field-level precision/recall on (instruction_name, variation, field_name[, bit_range]).
    If GT includes bit_range, bit_range is required for exact match.
    """
    use_bit_range = any(bool(r.get("bit_range")) for r in gt_rows)

    def mk_key(r: Dict[str, Any]) -> Tuple[str, str, str, Optional[str]]:
        inst = _norm_inst_name(str(r.get("instruction_name", "")))
        field = _norm_field_name(str(r.get("field_name", "")))
        var = normalize_variation(r.get("variation"))
        vk = var if var is not None else ""
        br = r.get("bit_range")
        br_norm = _norm_bit_range(str(br)) if br else None
        if use_bit_range:
            return (inst, vk, field, br_norm)
        return (inst, vk, field, None)

    gt_keys: Set[Tuple[str, str, str, Optional[str]]] = {
        mk_key(r) for r in gt_rows if r.get("instruction_name") and r.get("field_name")
    }
    pred_keys: Set[Tuple[str, str, str, Optional[str]]] = {
        mk_key(r) for r in pred_rows if r.get("instruction_name") and r.get("field_name")
    }

    tp = len(gt_keys & pred_keys)
    fp = len(pred_keys - gt_keys)
    fn = len(gt_keys - pred_keys)

    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not gt_keys else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 0.0 if precision + recall <= 0 else 2 * precision * recall / (precision + recall)

    return {
        "metrics": {
            "true_positive_count": tp,
            "false_positive_count": fp,
            "false_negative_count": fn,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "use_bit_range": use_bit_range,
        },
        "true_positives": sorted(list(gt_keys & pred_keys)),
        "false_positives": sorted(list(pred_keys - gt_keys)),
        "false_negatives": sorted(list(gt_keys - pred_keys)),
    }

