from __future__ import annotations

import re
from collections import defaultdict
import argparse
from pathlib import Path
from typing import Any, Dict, List, Set

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage3b_global_field_schema.ground_truth_eval import (
    build_global_field_schema_from_ground_truth,
    evaluate_global_field_schema_extraction,
    load_global_field_ground_truth,
)

def _canonical_field_name(name: str) -> str:
    s = name.strip()
    s = re.sub(r"\s+", "_", s)
    return s


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage3b: global field schema from instruction_field_map")
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        metavar="PATH",
        help="Ground truth for evaluation (canonical_field_names list).",
    )
    parser.add_argument(
        "--ground-truth-as-output",
        action="store_true",
        help="Skip extraction and generate global_field_schema directly from --ground-truth.",
    )
    args = parser.parse_args()

    run = StageRun.create("stage3b_global_field_schema")

    out_dir = artifact_path("stage3b_global_field_schema")

    alias_rows: List[Dict[str, Any]] = []

    if args.ground_truth_as_output:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-output requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt = load_global_field_ground_truth(gt_path)
        schema = build_global_field_schema_from_ground_truth(gt, run)
        write_json(out_dir / "global_field_schema.json", schema)
        write_jsonl(out_dir / "field_alias_map.jsonl", alias_rows)
        write_json(out_dir / "run_manifest.json", run.to_dict())
        print(f"[GT-as-output] canonical fields={len(schema.get('canonical_field_names', []))}")
        return

    rows = load_jsonl(artifact_path("stage3_field_table_parsing", "instruction_field_map.jsonl"))
    names: Set[str] = set()
    per_instruction: Dict[str, Set[str]] = defaultdict(set)
    for row in rows:
        raw_fn = row.get("field_name", "")
        fn = _canonical_field_name(raw_fn) if raw_fn else ""
        if fn:
            names.add(fn)
            ins = row.get("instruction_name", "")
            if ins:
                per_instruction[ins].add(fn)

    canonical = sorted(names)
    schema: Dict[str, Any] = {
        "stage_name": run.stage_name,
        "stage_run_id": run.stage_run_id,
        "canonical_field_names": canonical,
        "field_count_per_instruction": {k: sorted(v) for k, v in per_instruction.items()},
        "alias_catalog": "field_alias_map.jsonl",
        "output_schema_version": "global_field_schema@1",
    }
    write_json(out_dir / "global_field_schema.json", schema)
    write_jsonl(out_dir / "field_alias_map.jsonl", alias_rows)

    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        gt = load_global_field_ground_truth(gt_path)
        report = evaluate_global_field_schema_extraction(canonical, gt)
        report["ground_truth_path"] = str(gt_path.resolve())
        write_json(out_dir / "evaluation_report.json", report)
        print(
            f"evaluation: P={report['metrics']['precision']} R={report['metrics']['recall']} F1={report['metrics']['f1']}"
        )

    write_json(out_dir / "run_manifest.json", run.to_dict())
    print(f"canonical fields={len(canonical)} instructions={len(per_instruction)}")


if __name__ == "__main__":
    main()
