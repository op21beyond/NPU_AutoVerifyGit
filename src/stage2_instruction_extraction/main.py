from __future__ import annotations

import argparse
from pathlib import Path

from src.common.contracts import load_json, load_jsonl, write_json, write_jsonl
from src.common.page_range import (
    filter_page_blocks_by_page_range,
    infer_document_total_pages_from_blocks,
    resolve_page_range,
)
from src.common.runtime import StageRun, artifact_path

from src.stage2_instruction_extraction.extract import (
    augment_page_blocks_with_supplemental_corpus,
)
from src.stage2_instruction_extraction.ground_truth_eval import (
    build_instruction_catalog_from_ground_truth,
    evaluate_instruction_extraction,
    load_ground_truth,
)
from src.stage2_instruction_extraction.llm_openai import build_instruction_catalog_openai
from src.stage2_instruction_extraction.page_coverage import (
    build_page_coverage_payload,
    resolve_coverage_page_range,
    write_page_coverage_png,
)
from src.common.rag_cli import add_rag_arguments
from src.common.rag_resolve import DEFAULT_RAG_QUERIES, narrow_page_blocks_with_optional_rag


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage2: instruction catalog from page_blocks")
    parser.add_argument(
        "--page-blocks",
        type=str,
        default=None,
        help="Override path to page_blocks.jsonl (default: artifacts/stage1_ingestion/page_blocks.jsonl)",
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
        help="Model id for OpenAI Chat Completions (e.g. gpt-4o-mini, gpt-4o)",
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
        help="Reference instruction list for evaluation (.txt one name per line, or .json / .jsonl). "
        "Writes evaluation_report.json with precision/recall/F1 vs extracted catalog.",
    )
    parser.add_argument(
        "--supplemental-text-corpus",
        type=str,
        default=None,
        help="Optional JSON corpus from Stage1 pymupdf4llm (default auto-detect artifacts/stage1_ingestion/pymupdf4llm_corpus.json)",
    )
    parser.add_argument(
        "--disable-default-supplemental-text",
        action="store_true",
        help="Do not auto-load default supplemental corpus file when --supplemental-text-corpus is not passed",
    )
    parser.add_argument(
        "--ground-truth-as-catalog",
        action="store_true",
        help="Skip OpenAI extraction; write instruction_catalog from --ground-truth file only",
    )
    parser.add_argument(
        "--no-page-coverage",
        action="store_true",
        help="Do not write page_coverage.json / page_coverage.png (default: write after OpenAI extraction)",
    )
    add_rag_arguments(parser)
    args = parser.parse_args()

    run = StageRun.create("stage2_instruction_extraction")
    rag_stats: dict | None = None

    if args.ground_truth_as_catalog:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-catalog requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt_rows = load_ground_truth(gt_path)
        rows = build_instruction_catalog_from_ground_truth(gt_rows, run)
        pb_path = None
        supplemental_path = None
        page_range_applied = None
    else:
        pb_path = args.page_blocks or str(artifact_path("stage1_ingestion", "page_blocks.jsonl"))
        page_blocks = load_jsonl(Path(pb_path))
        supplemental_path: Path | None = None
        if args.supplemental_text_corpus:
            supplemental_path = Path(args.supplemental_text_corpus)
        elif not args.disable_default_supplemental_text:
            default_supp = artifact_path("stage1_ingestion", "pymupdf4llm_corpus.json")
            if default_supp.exists():
                supplemental_path = default_supp
        if supplemental_path and supplemental_path.exists():
            corpus = load_json(supplemental_path)
            page_blocks = augment_page_blocks_with_supplemental_corpus(page_blocks, corpus)

        if args.page_start is not None or args.page_end is not None:
            total_pages = infer_document_total_pages_from_blocks(page_blocks)
            first_p, last_p = resolve_page_range(total_pages, args.page_start, args.page_end)
            page_blocks = filter_page_blocks_by_page_range(page_blocks, first_p, last_p)
            page_range_applied = (first_p, last_p)
        else:
            page_range_applied = None

        pb_for_llm, rag_stats = narrow_page_blocks_with_optional_rag(
            page_blocks,
            args,
            default_rag_query=DEFAULT_RAG_QUERIES["stage2_instruction_extraction"],
        )
        if rag_stats and rag_stats.get("rag_error"):
            print(f"WARNING: RAG failed ({rag_stats['rag_error']}); using full page_blocks.")

        rows = build_instruction_catalog_openai(
            pb_for_llm,
            run,
            model=args.openai_model,
            base_url=args.openai_base_url,
        )

    out = artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl")
    write_jsonl(out, rows)
    summary: dict = {
        "stage_run_id": run.stage_run_id,
        "instruction_count": len(rows),
        "page_blocks_path": pb_path,
        "supplemental_text_corpus_path": str(supplemental_path) if supplemental_path else None,
        "extractor": None if args.ground_truth_as_catalog else "openai",
        "catalog_source": "ground_truth" if args.ground_truth_as_catalog else "openai",
        "openai_model": args.openai_model if not args.ground_truth_as_catalog else None,
        "openai_base_url": args.openai_base_url if not args.ground_truth_as_catalog else None,
        "ground_truth_path": args.ground_truth,
        "ground_truth_as_catalog": args.ground_truth_as_catalog,
        "page_range": (
            {"first": page_range_applied[0], "last": page_range_applied[1]}
            if page_range_applied
            else None
        ),
        "output_schema_version": "instruction_catalog@2",
        "rag": rag_stats,
    }

    if args.ground_truth and not args.ground_truth_as_catalog:
        gt_path = Path(args.ground_truth)
        gt_rows = load_ground_truth(gt_path)
        eval_report = evaluate_instruction_extraction(rows, gt_rows)
        eval_report["ground_truth_path"] = str(gt_path.resolve())
        eval_report["stage_run_id"] = run.stage_run_id
        eval_path = artifact_path("stage2_instruction_extraction", "evaluation_report.json")
        write_json(eval_path, eval_report)
        summary["evaluation"] = eval_report["metrics"]
        m = eval_report["metrics"]
        print(
            f"evaluation: P={m['precision']} R={m['recall']} F1={m['f1']} "
            f"TP={m['true_positive_count']} FP={m['false_positive_count']} FN={m['false_negative_count']}"
        )
        print(f"wrote -> {eval_path}")

    cov_path_json = artifact_path("stage2_instruction_extraction", "page_coverage.json")
    cov_path_png = artifact_path("stage2_instruction_extraction", "page_coverage.png")
    if not args.ground_truth_as_catalog and not args.no_page_coverage:
        assert pb_path is not None
        first_c, last_c = resolve_coverage_page_range(pb_path, page_blocks, page_range_applied)
        cov_payload = build_page_coverage_payload(
            rows,
            first_c,
            last_c,
            stage_run_id=run.stage_run_id,
        )
        write_json(cov_path_json, cov_payload)
        write_page_coverage_png(str(cov_path_png), cov_payload)
        summary["page_coverage_json"] = str(cov_path_json)
        summary["page_coverage_png"] = str(cov_path_png)
        print(f"page coverage -> {cov_path_json}")
        print(f"page coverage -> {cov_path_png}")
    elif not args.ground_truth_as_catalog and args.no_page_coverage:
        summary["page_coverage_json"] = None
        summary["page_coverage_png"] = None
    elif args.ground_truth_as_catalog and not args.no_page_coverage:
        summary["page_coverage_json"] = None
        summary["page_coverage_png"] = None
        print("page coverage skipped (ground-truth-as-catalog has no per-page source_refs)")
    else:
        summary["page_coverage_json"] = None
        summary["page_coverage_png"] = None

    write_json(artifact_path("stage2_instruction_extraction", "extraction_summary.json"), summary)
    write_json(artifact_path("stage2_instruction_extraction", "run_manifest.json"), run.to_dict())
    print(f"wrote {len(rows)} instructions -> {out}")


if __name__ == "__main__":
    main()
