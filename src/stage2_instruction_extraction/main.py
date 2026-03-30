from __future__ import annotations

import argparse
from pathlib import Path

from src.common.contracts import load_json, load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage2_instruction_extraction.extract import (
    augment_page_blocks_with_supplemental_corpus,
    build_instruction_catalog,
)
from src.stage2_instruction_extraction.ground_truth_eval import (
    build_instruction_catalog_from_ground_truth,
    evaluate_instruction_extraction,
    load_ground_truth,
)
from src.stage2_instruction_extraction.llm_openai import build_instruction_catalog_openai


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage2: instruction catalog from page_blocks")
    parser.add_argument(
        "--page-blocks",
        type=str,
        default=None,
        help="Override path to page_blocks.jsonl (default: artifacts/stage1_ingestion/page_blocks.jsonl)",
    )
    parser.add_argument(
        "--extractor",
        choices=("regex", "openai"),
        default="regex",
        help="regex: rule-based (default); openai: OpenAI Chat Completions JSON mode",
    )
    parser.add_argument(
        "--openai-model",
        default="gpt-4o-mini",
        help="Model id when --extractor openai (e.g. gpt-4o-mini, gpt-4o)",
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
        help="Skip regex/OpenAI extraction; write instruction_catalog from --ground-truth file only",
    )
    args = parser.parse_args()

    run = StageRun.create("stage2_instruction_extraction")

    if args.ground_truth_as_catalog:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-catalog requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt_rows = load_ground_truth(gt_path)
        rows = build_instruction_catalog_from_ground_truth(gt_rows, run)
        pb_path = None
        supplemental_path = None
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

        if args.extractor == "regex":
            rows = build_instruction_catalog(page_blocks, run)
        else:
            rows = build_instruction_catalog_openai(
                page_blocks,
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
        "extractor": args.extractor if not args.ground_truth_as_catalog else None,
        "catalog_source": "ground_truth" if args.ground_truth_as_catalog else "extractor",
        "openai_model": args.openai_model if args.extractor == "openai" and not args.ground_truth_as_catalog else None,
        "openai_base_url": args.openai_base_url if args.extractor == "openai" and not args.ground_truth_as_catalog else None,
        "ground_truth_path": args.ground_truth,
        "ground_truth_as_catalog": args.ground_truth_as_catalog,
        "output_schema_version": "instruction_catalog@1",
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

    write_json(artifact_path("stage2_instruction_extraction", "extraction_summary.json"), summary)
    write_json(artifact_path("stage2_instruction_extraction", "run_manifest.json"), run.to_dict())
    print(f"wrote {len(rows)} instructions -> {out}")


if __name__ == "__main__":
    main()
