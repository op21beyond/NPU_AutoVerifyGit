from __future__ import annotations

import argparse
from pathlib import Path

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage3_field_table_parsing.field_tables import build_instruction_field_map
from src.stage3_field_table_parsing.ground_truth_eval import (
    build_instruction_field_map_from_ground_truth,
    evaluate_instruction_field_map_extraction,
    load_instruction_field_ground_truth,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage3: instruction field map from tables / loose text")
    parser.add_argument("--page-blocks", type=str, default=None)
    parser.add_argument("--instruction-catalog", type=str, default=None)
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        metavar="PATH",
        help="Ground truth for evaluation (instruction_name/field_name rows).",
    )
    parser.add_argument(
        "--ground-truth-as-output",
        action="store_true",
        help="Skip extraction and generate instruction_field_map directly from --ground-truth.",
    )
    args = parser.parse_args()

    run = StageRun.create("stage3_field_table_parsing")
    out = artifact_path("stage3_field_table_parsing", "instruction_field_map.jsonl")

    if args.ground_truth_as_output:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-output requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt_rows = load_instruction_field_ground_truth(gt_path)
        rows = build_instruction_field_map_from_ground_truth(gt_rows, run)
        write_jsonl(out, rows)
        write_json(
            artifact_path("stage3_field_table_parsing", "parsing_summary.json"),
            {
                "stage_run_id": run.stage_run_id,
                "field_row_count": len(rows),
                "instruction_count_input": None,
                "ground_truth_path": str(gt_path.resolve()),
                "ground_truth_as_output": True,
                "output_schema_version": "instruction_field_map@1",
            },
        )
        write_json(artifact_path("stage3_field_table_parsing", "run_manifest.json"), run.to_dict())
        print(f"wrote {len(rows)} GT-derived field rows -> {out}")
        return

    pb = Path(args.page_blocks or artifact_path("stage1_ingestion", "page_blocks.jsonl"))
    ic = Path(args.instruction_catalog or artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl"))

    page_blocks = load_jsonl(pb)
    instructions = load_jsonl(ic)
    rows = build_instruction_field_map(page_blocks, instructions, run)

    write_jsonl(out, rows)
    write_json(
        artifact_path("stage3_field_table_parsing", "parsing_summary.json"),
        {
            "stage_run_id": run.stage_run_id,
            "field_row_count": len(rows),
            "instruction_count_input": len(instructions),
            "ground_truth_as_output": False,
            "output_schema_version": "instruction_field_map@1",
        },
    )

    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        gt_rows = load_instruction_field_ground_truth(gt_path)
        report = evaluate_instruction_field_map_extraction(rows, gt_rows)
        report["ground_truth_path"] = str(gt_path.resolve())
        eval_path = artifact_path("stage3_field_table_parsing", "evaluation_report.json")
        write_json(eval_path, report)
        print(f"evaluation_report: P={report['metrics']['precision']} R={report['metrics']['recall']} F1={report['metrics']['f1']}")

    write_json(artifact_path("stage3_field_table_parsing", "run_manifest.json"), run.to_dict())
    print(f"wrote {len(rows)} field rows -> {out}")


if __name__ == "__main__":
    main()
