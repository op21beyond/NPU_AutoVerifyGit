from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from src.common.contracts import write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage1_ingestion.ingestion import PageMetrics, extract_page_blocks


def _build_ocr_routing_payload(
    run: StageRun,
    metrics_summary: Dict[str, Any],
    metrics_list: List[PageMetrics],
) -> Dict[str, Any]:
    ocr_pages = [m.page for m in metrics_list if m.needs_ocr]
    return {
        "stage_name": run.stage_name,
        "stage_run_id": run.stage_run_id,
        "ocr_candidate_pages": ocr_pages,
        "ocr_candidate_pages_count": len(ocr_pages),
        "pages": [
            {
                "page": m.page,
                "needs_ocr": m.needs_ocr,
                "reasons": m.ocr_reasons,
                "metrics": {
                    "char_count": m.char_count,
                    "text_blocks": m.text_blocks,
                    "image_blocks": m.image_blocks,
                    "table_blocks": m.table_blocks,
                },
            }
            for m in metrics_list
        ],
        "summary": metrics_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage1: PDF ingestion and page/block segmentation")
    parser.add_argument("--input-pdf", required=True, help="Path to Architecture PDF")
    parser.add_argument(
        "--min-chars-ocr",
        type=int,
        default=40,
        help="Pages with fewer text-layer characters than this are candidates for OCR routing",
    )
    parser.add_argument(
        "--ocr-full-page",
        action="store_true",
        help="Run optional Tesseract full-page OCR on routed pages (requires tesseract on PATH)",
    )
    args = parser.parse_args()

    pdf_path = Path(args.input_pdf)
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")

    run = StageRun.create("stage1_ingestion")
    rows, metrics_list, summary = extract_page_blocks(
        pdf_path,
        run,
        min_chars_for_no_ocr=args.min_chars_ocr,
        run_full_page_ocr=args.ocr_full_page,
    )

    out = artifact_path("stage1_ingestion", "page_blocks.jsonl")
    write_jsonl(out, rows)

    parsing_report = {
        **summary,
        "ocr_candidate_pages_count": len([m for m in metrics_list if m.needs_ocr]),
        "output_schema_version": "page_blocks@1",
    }
    write_json(artifact_path("stage1_ingestion", "parsing_report.json"), parsing_report)
    write_json(
        artifact_path("stage1_ingestion", "ocr_routing.json"),
        _build_ocr_routing_payload(run, parsing_report, metrics_list),
    )
    write_json(artifact_path("stage1_ingestion", "run_manifest.json"), run.to_dict())

    print(f"wrote {len(rows)} blocks -> {out}")
    print(
        f"pages={summary['total_pages']} parse_success_rate={summary['parse_success_rate']} "
        f"ocr_candidates={parsing_report['ocr_candidate_pages_count']}"
    )


if __name__ == "__main__":
    main()
