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

from src.stage4_domain_typing.ground_truth_eval import (
    build_field_datatype_catalog_only_from_ground_truth,
    evaluate_stage4_extraction,
    load_stage4_ground_truth,
)
from src.stage4b_field_datatype_catalog.llm_field_datatype import build_field_datatype_catalog_openai
from src.common.rag_cli import add_rag_arguments
from src.common.rag_resolve import DEFAULT_RAG_QUERIES, narrow_page_blocks_with_optional_rag


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage4b: field_datatype_catalog (field to type_id) via OpenAI or ground truth",
    )
    parser.add_argument("--page-blocks", type=str, default=None)
    parser.add_argument("--page-start", type=int, default=None, metavar="N")
    parser.add_argument("--page-end", type=int, default=None, metavar="N")
    parser.add_argument(
        "--instruction-field-map",
        type=str,
        default=None,
        help="instruction_field_map.jsonl (default: artifacts/stage3_field_table_parsing/...)",
    )
    parser.add_argument(
        "--datatype-registry",
        type=str,
        default=None,
        help="datatype_registry.jsonl from Stage4 (default: artifacts/stage4_domain_typing/...)",
    )
    parser.add_argument("--openai-model", default="gpt-4o-mini")
    parser.add_argument("--openai-base-url", default=None)
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        metavar="PATH",
        help="GT with field_datatype_catalog (DTYPE lines or JSON).",
    )
    parser.add_argument(
        "--ground-truth-as-output",
        action="store_true",
        help="Write field_datatype_catalog.jsonl from --ground-truth only.",
    )
    add_rag_arguments(parser)
    args = parser.parse_args()

    run = StageRun.create("stage4b_field_datatype_catalog")
    out_dir = artifact_path("stage4b_field_datatype_catalog")

    if args.ground_truth_as_output:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-output requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt = load_stage4_ground_truth(gt_path)
        rows = build_field_datatype_catalog_only_from_ground_truth(gt, run)
        write_jsonl(out_dir / "field_datatype_catalog.jsonl", rows)
        write_json(
            out_dir / "extraction_summary.json",
            {
                "stage_run_id": run.stage_run_id,
                "mode": "ground_truth_as_output",
                "row_count": len(rows),
                "ground_truth_path": str(gt_path.resolve()),
            },
        )
        write_json(out_dir / "run_manifest.json", run.to_dict())
        print(f"[GT-as-output] field_datatype_catalog rows={len(rows)}")
        return

    pb = Path(args.page_blocks or artifact_path("stage1_ingestion", "page_blocks.jsonl"))
    page_blocks = load_jsonl(pb)
    page_range_applied = None
    if args.page_start is not None or args.page_end is not None:
        total_pages = infer_document_total_pages_from_blocks(page_blocks)
        first_p, last_p = resolve_page_range(total_pages, args.page_start, args.page_end)
        page_blocks = filter_page_blocks_by_page_range(page_blocks, first_p, last_p)
        page_range_applied = (first_p, last_p)

    ifm_path = Path(
        args.instruction_field_map or artifact_path("stage3_field_table_parsing", "instruction_field_map.jsonl")
    )
    instruction_rows = load_jsonl(ifm_path)

    reg_path = Path(args.datatype_registry or artifact_path("stage4_domain_typing", "datatype_registry.jsonl"))
    registry = load_jsonl(reg_path)

    pb_for_llm, rag_stats = narrow_page_blocks_with_optional_rag(
        page_blocks,
        args,
        default_rag_query=DEFAULT_RAG_QUERIES["stage4b_field_datatype_catalog"],
    )
    if rag_stats and rag_stats.get("rag_error"):
        print(f"WARNING: RAG failed ({rag_stats['rag_error']}); using full page_blocks.")

    rows = build_field_datatype_catalog_openai(
        pb_for_llm,
        instruction_rows,
        registry,
        run,
        model=args.openai_model,
        base_url=args.openai_base_url,
    )

    write_jsonl(out_dir / "field_datatype_catalog.jsonl", rows)
    write_json(
        out_dir / "extraction_summary.json",
        {
            "stage_run_id": run.stage_run_id,
            "mode": "openai",
            "openai_model": args.openai_model,
            "row_count": len(rows),
            "page_blocks_path": str(pb.resolve()),
            "instruction_field_map_path": str(ifm_path.resolve()),
            "datatype_registry_path": str(reg_path.resolve()),
            "page_range": (
                {"first": page_range_applied[0], "last": page_range_applied[1]}
                if page_range_applied
                else None
            ),
            "rag": rag_stats,
        },
    )

    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        gt = load_stage4_ground_truth(gt_path)
        report = evaluate_stage4_extraction(
            [],
            rows,
            [],
            {
                "datatype_registry": [],
                "field_datatype_catalog": gt.get("field_datatype_catalog") or [],
                "field_domain_catalog": [],
            },
        )
        report["ground_truth_path"] = str(gt_path.resolve())
        write_json(out_dir / "evaluation_report.json", report)
        for name, sec in (report.get("sections") or {}).items():
            m = sec.get("metrics", {})
            print(f"eval[{name}] P={m.get('precision')} R={m.get('recall')} F1={m.get('f1')}")

    write_json(out_dir / "run_manifest.json", run.to_dict())
    print(f"field_datatype_catalog rows={len(rows)}")


if __name__ == "__main__":
    main()
