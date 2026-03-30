from __future__ import annotations

import argparse
from pathlib import Path

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage4_domain_typing.domain_typing import (
    build_datatype_registry,
    build_field_datatype_catalog,
    build_field_domain_catalog,
)
from src.stage4_domain_typing.ground_truth_eval import (
    build_stage4_outputs_from_ground_truth,
    evaluate_stage4_extraction,
    load_stage4_ground_truth,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage4: datatype registry and field typing from instruction_field_map")
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        metavar="PATH",
        help="Ground truth JSON for evaluation (datatype_registry, field_datatype_catalog, field_domain_catalog).",
    )
    parser.add_argument(
        "--ground-truth-as-output",
        action="store_true",
        help="Skip extraction and write stage4 artifacts directly from --ground-truth JSON.",
    )
    args = parser.parse_args()

    run = StageRun.create("stage4_domain_typing")
    out_dir = artifact_path("stage4_domain_typing")

    if args.ground_truth_as_output:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-output requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt = load_stage4_ground_truth(gt_path)
        registry_rows, datatype_rows, domain_rows = build_stage4_outputs_from_ground_truth(gt, run)
        write_jsonl(out_dir / "datatype_registry.jsonl", registry_rows)
        write_jsonl(out_dir / "field_datatype_catalog.jsonl", datatype_rows)
        write_jsonl(out_dir / "field_domain_catalog.jsonl", domain_rows)
        write_json(out_dir / "run_manifest.json", run.to_dict())
        print(
            f"[GT-as-output] registry={len(registry_rows)} dtype_rows={len(datatype_rows)} domain_rows={len(domain_rows)}"
        )
        return

    fields = load_jsonl(artifact_path("stage3_field_table_parsing", "instruction_field_map.jsonl"))
    registry_rows = build_datatype_registry(fields, run)
    datatype_rows = build_field_datatype_catalog(fields, run)
    domain_rows = build_field_domain_catalog(fields, run)

    write_jsonl(out_dir / "datatype_registry.jsonl", registry_rows)
    write_jsonl(out_dir / "field_datatype_catalog.jsonl", datatype_rows)
    write_jsonl(out_dir / "field_domain_catalog.jsonl", domain_rows)

    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        gt = load_stage4_ground_truth(gt_path)
        report = evaluate_stage4_extraction(registry_rows, datatype_rows, domain_rows, gt)
        report["ground_truth_path"] = str(gt_path.resolve())
        write_json(out_dir / "evaluation_report.json", report)
        for name, sec in (report.get("sections") or {}).items():
            m = sec.get("metrics", {})
            print(f"eval[{name}] P={m.get('precision')} R={m.get('recall')} F1={m.get('f1')}")

    write_json(out_dir / "run_manifest.json", run.to_dict())
    print(f"registry types={len(registry_rows)} fields={len(fields)} dtype_rows={len(datatype_rows)}")


if __name__ == "__main__":
    main()
