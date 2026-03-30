from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.common.runtime import StageRun


def _norm_field_name(s: str) -> str:
    x = (s or "").strip()
    x = re.sub(r"\s+", "_", x)
    return x


def load_global_field_ground_truth(path: Path) -> Dict[str, Any]:
    """
    Supported:
    - .txt: one canonical field name per line
    - .json: either {canonical_field_names:[...], field_count_per_instruction:{...}} or [...]
    - .jsonl: each line is an object with field_name / canonical_field_name
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")

    if suffix == ".txt":
        names: List[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            names.append(_norm_field_name(line))
        return {"canonical_field_names": sorted(set(names))}

    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            names = [_norm_field_name(str(x)) for x in data]
            return {"canonical_field_names": sorted(set(names))}
        if isinstance(data, dict):
            canonical = data.get("canonical_field_names") or data.get("fields") or []
            canonical_list = [_norm_field_name(str(x)) for x in canonical if x is not None]
            fcount = data.get("field_count_per_instruction")
            out: Dict[str, Any] = {"canonical_field_names": sorted(set(canonical_list))}
            if isinstance(fcount, dict):
                out["field_count_per_instruction"] = fcount
            return out
        raise ValueError("GT .json must be an array or object")

    if suffix == ".jsonl":
        names: Set[str] = set()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                continue
            n = obj.get("canonical_field_name") or obj.get("field_name") or obj.get("name")
            if n:
                names.add(_norm_field_name(str(n)))
        return {"canonical_field_names": sorted(names)}

    raise ValueError(f"Unsupported ground-truth extension: {suffix}")


def build_global_field_schema_from_ground_truth(gt: Dict[str, Any], run: StageRun) -> Dict[str, Any]:
    canonical = sorted(set(_norm_field_name(x) for x in (gt.get("canonical_field_names") or [])))
    field_count_per_instruction = gt.get("field_count_per_instruction")

    schema: Dict[str, Any] = {
        "stage_name": run.stage_name,
        "stage_run_id": run.stage_run_id,
        "canonical_field_names": canonical,
        "field_count_per_instruction": field_count_per_instruction if isinstance(field_count_per_instruction, dict) else {},
        "alias_catalog": "field_alias_map.jsonl",
        "output_schema_version": "global_field_schema@1",
    }
    return schema


def evaluate_global_field_schema_extraction(pred_canonical: List[str], gt: Dict[str, Any]) -> Dict[str, Any]:
    gt_names: Set[str] = set(_norm_field_name(x) for x in (gt.get("canonical_field_names") or []))
    pred_names: Set[str] = set(_norm_field_name(x) for x in pred_canonical or [])

    tp = len(gt_names & pred_names)
    fp = len(pred_names - gt_names)
    fn = len(gt_names - pred_names)

    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not gt_names else 0.0)
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
        },
        "true_positives": sorted(list(gt_names & pred_names)),
        "false_positives": sorted(list(pred_names - gt_names)),
        "false_negatives": sorted(list(gt_names - pred_names)),
    }

