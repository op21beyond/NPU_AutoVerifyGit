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
    build_datatype_registry_only_from_ground_truth,
    evaluate_stage4_extraction,
    load_stage4_ground_truth,
)
from src.stage4_domain_typing.llm_datatype_registry import build_datatype_registry_openai
from src.common.rag_cli import add_rag_arguments
from src.common.rag_resolve import DEFAULT_RAG_QUERIES, narrow_page_blocks_with_optional_rag


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage4: datatype_registry from document excerpts (OpenAI) or ground truth",
    )
    parser.add_argument(
        "--page-blocks",
        type=str,
        default=None,
        help="Path to page_blocks.jsonl (default: artifacts/stage1_ingestion/page_blocks.jsonl)",
    )
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
    parser.add_argument(
        "--openai-model",
        default="gpt-4o-mini",
        help="OpenAI model id for datatype extraction (e.g. gpt-4o-mini, gpt-4o)",
    )
    parser.add_argument(
        "--openai-base-url",
        default=None,
        help="OpenAI-compatible API base URL (omit for https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        metavar="PATH",
        help="Ground truth for evaluation (datatype_registry section; same format as stage4 combined GT).",
    )
    parser.add_argument(
        "--ground-truth-as-output",
        action="store_true",
        help="Skip LLM; write datatype_registry.jsonl from --ground-truth (TYPE lines or JSON).",
    )
    add_rag_arguments(parser)
    args = parser.parse_args()

    run = StageRun.create("stage4_domain_typing")
    out_dir = artifact_path("stage4_domain_typing")

    if args.ground_truth_as_output:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-output requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt = load_stage4_ground_truth(gt_path)
        registry_rows = build_datatype_registry_only_from_ground_truth(gt, run)
        write_jsonl(out_dir / "datatype_registry.jsonl", registry_rows)
        write_json(
            out_dir / "extraction_summary.json",
            {
                "stage_run_id": run.stage_run_id,
                "mode": "ground_truth_as_output",
                "datatype_registry_row_count": len(registry_rows),
                "ground_truth_path": str(gt_path.resolve()),
                "page_range": None,
                "page_blocks_path": None,
            },
        )
        write_json(out_dir / "run_manifest.json", run.to_dict())
        print(f"[GT-as-output] datatype_registry rows={len(registry_rows)}")
        return

    pb = Path(args.page_blocks or artifact_path("stage1_ingestion", "page_blocks.jsonl"))
    page_blocks = load_jsonl(pb)
    page_range_applied = None
    if args.page_start is not None or args.page_end is not None:
        total_pages = infer_document_total_pages_from_blocks(page_blocks)
        first_p, last_p = resolve_page_range(total_pages, args.page_start, args.page_end)
        page_blocks = filter_page_blocks_by_page_range(page_blocks, first_p, last_p)
        page_range_applied = (first_p, last_p)

    pb_for_llm, rag_stats = narrow_page_blocks_with_optional_rag(
        page_blocks,
        args,
        default_rag_query=DEFAULT_RAG_QUERIES["stage4_domain_typing"],
    )
    if rag_stats and rag_stats.get("rag_error"):
        print(f"WARNING: RAG failed ({rag_stats['rag_error']}); using full page_blocks.")

    registry_rows = build_datatype_registry_openai(
        pb_for_llm,
        run,
        model=args.openai_model,
        base_url=args.openai_base_url,
    )

    write_jsonl(out_dir / "datatype_registry.jsonl", registry_rows)
    write_json(
        out_dir / "extraction_summary.json",
        {
            "stage_run_id": run.stage_run_id,
            "mode": "openai",
            "openai_model": args.openai_model,
            "datatype_registry_row_count": len(registry_rows),
            "page_blocks_path": str(pb.resolve()),
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
            registry_rows,
            [],
            [],
            {
                "datatype_registry": gt.get("datatype_registry") or [],
                "field_datatype_catalog": [],
                "field_domain_catalog": [],
            },
        )
        report["ground_truth_path"] = str(gt_path.resolve())
        write_json(out_dir / "evaluation_report.json", report)
        for name, sec in (report.get("sections") or {}).items():
            m = sec.get("metrics", {})
            print(f"eval[{name}] P={m.get('precision')} R={m.get('recall')} F1={m.get('f1')}")

    write_json(out_dir / "run_manifest.json", run.to_dict())
    print(f"datatype_registry types={len(registry_rows)}")


if __name__ == "__main__":
    main()
