from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set


def _norm_name(s: str) -> str:
    return s.strip().upper()


def load_ground_truth(path: Path) -> List[Dict[str, Any]]:
    """
    Load reference instruction list for evaluation.

    Supported:
    - .txt / .lst / .list — one instruction name per line; lines starting with # ignored
    - .json — either ["INST1", ...] or [{"instruction_name": "...", "opcode_value": 42}, ...]
    - .jsonl — each line: JSON string or {"instruction_name": "...", ...}
    """
    if not path.is_file():
        raise FileNotFoundError(f"Ground truth file not found: {path}")

    suffix = path.suffix.lower()
    # utf-8-sig strips BOM from hand-edited Windows text files
    text = path.read_text(encoding="utf-8-sig")

    if suffix in (".txt", ".lst", ".list"):
        rows: List[Dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append({"instruction_name": _norm_name(line)})
        return rows

    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            if not data:
                return []
            if all(isinstance(x, str) for x in data):
                return [{"instruction_name": _norm_name(x)} for x in data]
            if all(isinstance(x, dict) for x in data):
                return _normalize_gt_objects(data)
        raise ValueError("Ground truth JSON must be a non-empty array of strings or objects")

    if suffix == ".jsonl":
        out: List[Dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = json.loads(line)
            if isinstance(row, str):
                out.append({"instruction_name": _norm_name(row)})
            elif isinstance(row, dict):
                out.extend(_normalize_gt_objects([row]))
            else:
                raise ValueError(f"Invalid JSONL row: {line[:80]}")
        return out

    # Other extension: try JSON array, else one name per line
    try:
        data = json.loads(text)
        if isinstance(data, list):
            if not data:
                return []
            if all(isinstance(x, str) for x in data):
                return [{"instruction_name": _norm_name(x)} for x in data]
            if all(isinstance(x, dict) for x in data):
                return _normalize_gt_objects(data)
    except json.JSONDecodeError:
        pass
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append({"instruction_name": _norm_name(line)})
    return rows


def _normalize_gt_objects(objs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for o in objs:
        name = o.get("instruction_name") or o.get("name") or o.get("mnemonic")
        if not name:
            continue
        row: Dict[str, Any] = {"instruction_name": _norm_name(str(name))}
        if "opcode_value" in o and o["opcode_value"] is not None:
            try:
                row["opcode_value"] = int(o["opcode_value"])
            except (TypeError, ValueError):
                pass
        if o.get("opcode_raw") is not None:
            row["opcode_raw"] = str(o["opcode_raw"])
        out.append(row)
    return out


def _pred_name_set(rows: List[Dict[str, Any]]) -> Set[str]:
    return {_norm_name(str(r.get("instruction_name", ""))) for r in rows if r.get("instruction_name")}


def _gt_name_map(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    m: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        n = e.get("instruction_name")
        if not n:
            continue
        key = _norm_name(str(n))
        m[key] = e
    return m


def evaluate_instruction_extraction(
    predicted_rows: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compare predicted instruction_catalog rows to ground truth (by instruction_name).
    Optional opcode_value check when present in ground truth.
    """
    gt_map = _gt_name_map(ground_truth)
    gt_names = set(gt_map.keys())

    pred_by_name: Dict[str, Dict[str, Any]] = {}
    for r in predicted_rows:
        n = r.get("instruction_name")
        if not n:
            continue
        key = _norm_name(str(n))
        pred_by_name.setdefault(key, r)

    pred_names = set(pred_by_name.keys())

    tp_names = sorted(pred_names & gt_names)
    fp_names = sorted(pred_names - gt_names)
    fn_names = sorted(gt_names - pred_names)

    tp = len(tp_names)
    pred_n = len(pred_names)
    gt_n = len(gt_names)

    precision = tp / pred_n if pred_n else (1.0 if gt_n == 0 else 0.0)
    recall = tp / gt_n if gt_n else 1.0
    if precision + recall <= 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    opcode_checks: List[Dict[str, Any]] = []
    opcode_defined = 0
    opcode_matches = 0
    for name in tp_names:
        g = gt_map.get(name) or {}
        p = pred_by_name.get(name) or {}
        ev = g.get("opcode_value")
        if ev is None:
            continue
        opcode_defined += 1
        pv = p.get("opcode_value")
        match = pv is not None and int(ev) == int(pv)
        if match:
            opcode_matches += 1
        opcode_checks.append(
            {
                "instruction_name": name,
                "expected_opcode_value": ev,
                "predicted_opcode_value": pv,
                "opcode_match": match,
            }
        )

    return {
        "metrics": {
            "true_positive_count": tp,
            "false_positive_count": len(fp_names),
            "false_negative_count": len(fn_names),
            "predicted_distinct_count": pred_n,
            "ground_truth_count": gt_n,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "opcode_value_defined_in_gt": opcode_defined,
            "opcode_value_matches": opcode_matches,
            "opcode_value_recall": round(opcode_matches / opcode_defined, 6) if opcode_defined else None,
        },
        "true_positives": tp_names,
        "false_positives": fp_names,
        "false_negatives": fn_names,
        "opcode_per_instruction": opcode_checks,
    }
