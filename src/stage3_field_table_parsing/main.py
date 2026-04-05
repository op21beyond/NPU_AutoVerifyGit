from __future__ import annotations

import argparse
from pathlib import Path

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.page_range import (
    filter_page_blocks_by_page_range,
    infer_document_total_pages_from_blocks,
    resolve_page_range,
)
from src.common.runtime import StageRun, artifact_path

from src.stage3_field_table_parsing.field_cheat_sheet import apply_field_cheat_sheet, load_field_cheat_sheet
from src.stage3_field_table_parsing.field_tables import build_instruction_field_map
from src.stage3_field_table_parsing.ground_truth_eval import (
    build_instruction_field_map_from_ground_truth,
    evaluate_instruction_field_map_extraction,
    load_instruction_field_ground_truth,
)
from src.stage3_field_table_parsing.scope_coverage import build_scope_coverage_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage3: instruction field map from tables / loose text")
    parser.add_argument("--page-blocks", type=str, default=None)
    parser.add_argument(
        "--page-start",
        type=int,
        default=None,
        metavar="N",
        help="First page to include (1-based). If omitted with no --page-end, all pages.",
    )
    parser.add_argument(
        "--page-end",
        type=int,
        default=None,
        metavar="N",
        help="Last page to include (1-based). If omitted with no --page-start, all pages.",
    )
    parser.add_argument("--instruction-catalog", type=str, default=None)
    parser.add_argument(
        "--field-cheat-sheet",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional JSON: per NAME or NAME|VAR scope, fields[] with field_name, bit_range, word_index. "
        "Overrides heuristic rows for matching catalog scopes.",
    )
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
        ic_path = Path(args.instruction_catalog or artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl"))
        instructions_for_summary = load_jsonl(ic_path) if ic_path.is_file() else None
        scope_cov = build_scope_coverage_summary(rows, instructions_for_summary)
        write_json(
            artifact_path("stage3_field_table_parsing", "parsing_summary.json"),
            {
                "stage_run_id": run.stage_run_id,
                "field_row_count": len(rows),
                "instruction_count_input": len(instructions_for_summary) if instructions_for_summary else None,
                "instruction_scope_coverage": scope_cov,
                "page_blocks_path": None,
                "page_range": None,
                "field_cheat_sheet_path": None,
                "field_cheat_sheet_warnings": [],
                "ground_truth_path": str(gt_path.resolve()),
                "ground_truth_as_output": True,
                "output_schema_version": "instruction_field_map@2",
            },
        )
        write_json(artifact_path("stage3_field_table_parsing", "run_manifest.json"), run.to_dict())
        print(f"wrote {len(rows)} GT-derived field rows -> {out}")
        return

    pb = Path(args.page_blocks or artifact_path("stage1_ingestion", "page_blocks.jsonl"))
    ic = Path(args.instruction_catalog or artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl"))

    page_blocks = load_jsonl(pb)
    page_range_applied = None
    if args.page_start is not None or args.page_end is not None:
        total_pages = infer_document_total_pages_from_blocks(page_blocks)
        first_p, last_p = resolve_page_range(total_pages, args.page_start, args.page_end)
        page_blocks = filter_page_blocks_by_page_range(page_blocks, first_p, last_p)
        page_range_applied = (first_p, last_p)

    instructions = load_jsonl(ic)
    rows = build_instruction_field_map(page_blocks, instructions, run)

    cheat_path: str | None = None
    cheat_warnings: list[str] = []
    if args.field_cheat_sheet:
        cheat_path = str(Path(args.field_cheat_sheet).resolve())
        cheat_data = load_field_cheat_sheet(Path(args.field_cheat_sheet))
        rows, cheat_warnings = apply_field_cheat_sheet(rows, instructions, cheat_data, run)
        for w in cheat_warnings:
            print(f"WARNING: {w}", flush=True)

    write_jsonl(out, rows)
    scope_cov = build_scope_coverage_summary(rows, instructions if instructions else None)
    summary: dict = {
        "stage_run_id": run.stage_run_id,
        "field_row_count": len(rows),
        "instruction_count_input": len(instructions),
        "instruction_scope_coverage": scope_cov,
        "page_blocks_path": str(pb.resolve()),
        "page_range": (
            {"first": page_range_applied[0], "last": page_range_applied[1]}
            if page_range_applied
            else None
        ),
        "field_cheat_sheet_path": cheat_path,
        "field_cheat_sheet_warnings": cheat_warnings,
        "ground_truth_as_output": False,
        "output_schema_version": "instruction_field_map@2",
    }
    write_json(artifact_path("stage3_field_table_parsing", "parsing_summary.json"), summary)

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
