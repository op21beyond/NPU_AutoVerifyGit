from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from src.common.runtime import StageRun


def _norm_field(s: str) -> str:
    x = (s or "").strip()
    x = re.sub(r"\s+", "_", x)
    return x.upper()


def _norm_type_id(s: str) -> str:
    return (s or "").strip()


def load_stage4_ground_truth(path: Path) -> Dict[str, Any]:
    """
    Ground-truth file (JSON) with optional keys:
    - datatype_registry: list of objects (type_id required for eval)
    - field_datatype_catalog: list (instruction_name, field_name, data_type_ref)
    - field_domain_catalog: list (field_name, allowed_value_form, allowed_values_or_range)
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")
    if path.suffix.lower() != ".json":
        raise ValueError("Stage4 ground truth must be a .json file with datatype_registry / field_datatype_catalog / field_domain_catalog arrays")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Stage4 GT .json must be an object")
    out: Dict[str, Any] = {}
    for key in ("datatype_registry", "field_datatype_catalog", "field_domain_catalog"):
        v = data.get(key)
        if v is None:
            out[key] = []
        elif isinstance(v, list):
            out[key] = v
        else:
            raise ValueError(f"Stage4 GT key {key} must be an array")
    return out


def _ensure_trace_ids(rows: List[Dict[str, Any]], run: StageRun, prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        r = dict(row)
        if not r.get("trace_id"):
            r["trace_id"] = f"{run.stage_run_id}:{prefix}:{i}"
        if "source_refs" not in r:
            r["source_refs"] = []
        out.append(r)
    return out


def build_stage4_outputs_from_ground_truth(gt: Dict[str, Any], run: StageRun) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    reg = _ensure_trace_ids(list(gt.get("datatype_registry") or []), run, "reg")
    dcat = _ensure_trace_ids(list(gt.get("field_datatype_catalog") or []), run, "dtype")
    dom = _ensure_trace_ids(list(gt.get("field_domain_catalog") or []), run, "domain")
    return reg, dcat, dom


def _registry_keys(rows: List[Dict[str, Any]]) -> Set[str]:
    s: Set[str] = set()
    for r in rows:
        tid = _norm_type_id(str(r.get("type_id", "")))
        if tid:
            s.add(tid)
    return s


def _dtype_cat_key(r: Dict[str, Any]) -> Tuple[str, str, str]:
    inst = str(r.get("instruction_name", "")).strip().upper()
    fn = _norm_field(str(r.get("field_name", "")))
    ref = _norm_type_id(str(r.get("data_type_ref", "")))
    return (inst, fn, ref)


def _dtype_keys(rows: List[Dict[str, Any]]) -> Set[Tuple[str, str, str]]:
    return {_dtype_cat_key(r) for r in rows if r.get("field_name")}


def _domain_key(r: Dict[str, Any]) -> Tuple[str, str, str]:
    fn = _norm_field(str(r.get("field_name", "")))
    form = str(r.get("allowed_value_form", "")).strip()
    av = str(r.get("allowed_values_or_range", "")).strip()
    return (fn, form, av)


def _domain_keys(rows: List[Dict[str, Any]]) -> Set[Tuple[str, str, str]]:
    return {_domain_key(r) for r in rows if r.get("field_name")}


def evaluate_stage4_extraction(
    pred_registry: List[Dict[str, Any]],
    pred_dtype: List[Dict[str, Any]],
    pred_domain: List[Dict[str, Any]],
    gt: Dict[str, Any],
) -> Dict[str, Any]:
    report: Dict[str, Any] = {"sections": {}}

    gt_reg = list(gt.get("datatype_registry") or [])
    if gt_reg:
        gk = _registry_keys(gt_reg)
        pk = _registry_keys(pred_registry)
        tp = len(gk & pk)
        fp = len(pk - gk)
        fn = len(gk - pk)
        prec = tp / (tp + fp) if (tp + fp) else (1.0 if not gk else 0.0)
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 0.0 if prec + rec <= 0 else 2 * prec * rec / (prec + rec)
        report["sections"]["datatype_registry"] = {
            "metrics": {
                "true_positive_count": tp,
                "false_positive_count": fp,
                "false_negative_count": fn,
                "precision": round(prec, 6),
                "recall": round(rec, 6),
                "f1": round(f1, 6),
            },
            "true_positives": sorted(gk & pk),
            "false_positives": sorted(pk - gk),
            "false_negatives": sorted(gk - pk),
        }

    gt_dtype = list(gt.get("field_datatype_catalog") or [])
    if gt_dtype:
        gk = _dtype_keys(gt_dtype)
        pk = _dtype_keys(pred_dtype)
        tp = len(gk & pk)
        fp = len(pk - gk)
        fn = len(gk - pk)
        prec = tp / (tp + fp) if (tp + fp) else (1.0 if not gk else 0.0)
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 0.0 if prec + rec <= 0 else 2 * prec * rec / (prec + rec)
        report["sections"]["field_datatype_catalog"] = {
            "metrics": {
                "true_positive_count": tp,
                "false_positive_count": fp,
                "false_negative_count": fn,
                "precision": round(prec, 6),
                "recall": round(rec, 6),
                "f1": round(f1, 6),
            },
            "true_positives": sorted(list(gk & pk)),
            "false_positives": sorted(list(pk - gk)),
            "false_negatives": sorted(list(gk - pk)),
        }

    gt_dom = list(gt.get("field_domain_catalog") or [])
    if gt_dom:
        gk = _domain_keys(gt_dom)
        pk = _domain_keys(pred_domain)
        tp = len(gk & pk)
        fp = len(pk - gk)
        fn = len(gk - pk)
        prec = tp / (tp + fp) if (tp + fp) else (1.0 if not gk else 0.0)
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 0.0 if prec + rec <= 0 else 2 * prec * rec / (prec + rec)
        report["sections"]["field_domain_catalog"] = {
            "metrics": {
                "true_positive_count": tp,
                "false_positive_count": fp,
                "false_negative_count": fn,
                "precision": round(prec, 6),
                "recall": round(rec, 6),
                "f1": round(f1, 6),
            },
            "true_positives": sorted(list(gk & pk)),
            "false_positives": sorted(list(pk - gk)),
            "false_negatives": sorted(list(gk - pk)),
        }

    return report
