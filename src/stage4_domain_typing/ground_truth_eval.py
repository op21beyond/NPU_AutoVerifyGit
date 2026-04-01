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


def _split_parts(line: str) -> List[str]:
    if "|" in line:
        return [p.strip() for p in line.split("|")]
    return re.split(r"\s+", line.strip())


def load_stage4_ground_truth(path: Path) -> Dict[str, Any]:
    """
    Ground-truth file with optional keys:
    - datatype_registry: list of objects (type_id required for eval)
    - field_datatype_catalog: list (instruction_name, field_name, data_type_ref)
    - field_domain_catalog: list (field_name, allowed_value_form, allowed_values_or_range)

    Supported:
    - .json: {"datatype_registry": [...], "field_datatype_catalog": [...], "field_domain_catalog": [...]}
    - .txt/.lst/.list: line-based compact format (partial fields allowed)
      * TYPE|type_id[|category]
      * DTYPE|instruction_name|field_name|data_type_ref
      * DTYPE|field_name|data_type_ref
      * DOMAIN|field_name|allowed_value_form|allowed_values_or_range
      * DOMAIN|field_name|allowed_values_or_range
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")

    if suffix in (".txt", ".lst", ".list"):
        reg: List[Dict[str, Any]] = []
        dcat: List[Dict[str, Any]] = []
        dom: List[Dict[str, Any]] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            parts = _split_parts(raw)
            if not parts:
                continue
            tag = (parts[0] or "").strip().upper().rstrip(":")
            vals = parts[1:]
            if tag == "TYPE":
                if not vals:
                    continue
                type_id = _norm_type_id(vals[0])
                if not type_id:
                    continue
                category = str(vals[1]).strip() if len(vals) >= 2 else "unknown"
                reg.append({"type_id": type_id, "type_name_raw": type_id, "category": category})
            elif tag == "DTYPE":
                if len(vals) >= 3:
                    dcat.append(
                        {
                            "instruction_name": str(vals[0]).strip().upper(),
                            "field_name": str(vals[1]).strip(),
                            "data_type_ref": _norm_type_id(vals[2]),
                        }
                    )
                elif len(vals) >= 2:
                    dcat.append(
                        {
                            "field_name": str(vals[0]).strip(),
                            "data_type_ref": _norm_type_id(vals[1]),
                        }
                    )
            elif tag == "DOMAIN":
                if len(vals) >= 3:
                    dom.append(
                        {
                            "field_name": str(vals[0]).strip(),
                            "allowed_value_form": str(vals[1]).strip(),
                            "allowed_values_or_range": str(vals[2]).strip(),
                        }
                    )
                elif len(vals) >= 2:
                    dom.append(
                        {
                            "field_name": str(vals[0]).strip(),
                            "allowed_value_form": "range",
                            "allowed_values_or_range": str(vals[1]).strip(),
                        }
                    )
        return {
            "datatype_registry": reg,
            "field_datatype_catalog": dcat,
            "field_domain_catalog": dom,
        }

    if suffix != ".json":
        raise ValueError("Stage4 ground truth must be .json or .txt/.lst/.list")

    data = json.loads(text)
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
