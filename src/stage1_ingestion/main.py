from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from src.common.contracts import write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage1_ingestion.ingestion import PageMetrics, extract_page_blocks, extract_pymupdf4llm_corpus


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
    parser.add_argument(
        "--image-ocr-engine",
        choices=("none", "tesseract", "paddleocr"),
        default="none",
        help="Run OCR for `image` blocks using selected engine (default: none).",
    )
    parser.add_argument(
        "--image-ocr-route",
        choices=("needs_ocr", "always"),
        default="needs_ocr",
        help="Run image OCR on pages flagged by OCR routing (`needs_ocr`) or always.",
    )
    parser.add_argument(
        "--image-ocr-dpi",
        type=int,
        default=200,
        help="DPI for rendering cropped image OCR (default: 200).",
    )
    parser.add_argument(
        "--image-ocr-min-chars",
        type=int,
        default=5,
        help="Min recognized characters to accept an image OCR result (default: 5).",
    )
    parser.add_argument(
        "--table-text-engine",
        choices=("pymupdf", "pdflumber", "tesseract", "paddleocr"),
        default="pymupdf",
        help="Engine for table block text extraction (default: pymupdf).",
    )
    parser.add_argument(
        "--table-ocr-route",
        choices=("empty_only", "always"),
        default="empty_only",
        help="For table OCR engines, run OCR only when table text is empty/short or always.",
    )
    parser.add_argument(
        "--table-ocr-dpi",
        type=int,
        default=200,
        help="DPI for rendering table bbox OCR (default: 200).",
    )
    parser.add_argument(
        "--table-ocr-min-chars",
        type=int,
        default=8,
        help="Min recognized characters to accept table OCR result (default: 8).",
    )
    parser.add_argument(
        "--paddle-device",
        choices=("auto", "cpu", "gpu"),
        default="auto",
        help="PaddleOCR device policy: auto-detect GPU, or force cpu/gpu.",
    )
    parser.add_argument(
        "--paddle-model-dir",
        default="",
        help="Optional PaddleOCR model root directory (expects det/rec/cls subdirs).",
    )
    parser.add_argument(
        "--paddle-gpu-id",
        type=int,
        default=0,
        help="GPU index for PaddleOCR 3.x device string (gpu:N). Ignored for 2.x use_gpu flag.",
    )
    parser.add_argument(
        "--header-footer-mode",
        choices=("none", "position", "repeat"),
        default="none",
        help="Header/footer removal mode: none, position-based, or repeat-based",
    )
    parser.add_argument(
        "--header-top-ratio",
        type=float,
        default=0.08,
        help="Top area ratio used by --header-footer-mode position (default: 0.08)",
    )
    parser.add_argument(
        "--footer-bottom-ratio",
        type=float,
        default=0.08,
        help="Bottom area ratio used by --header-footer-mode position (default: 0.08)",
    )
    parser.add_argument(
        "--repeat-min-pages",
        type=int,
        default=3,
        help="Min distinct pages with repeated short text for --header-footer-mode repeat",
    )
    parser.add_argument(
        "--repeat-max-chars",
        type=int,
        default=120,
        help="Max raw text length considered as header/footer candidate for repeat mode",
    )
    parser.add_argument(
        "--text-backend",
        choices=("pymupdf", "pymupdf4llm", "hybrid"),
        default="pymupdf",
        help="Text extraction backend policy: pymupdf only, pymupdf4llm supplemental, or hybrid",
    )
    parser.add_argument(
        "--table-merge-bypass",
        action="store_true",
        help="Skip PyMuPDF table bbox merge (use raw find_tables() rows; for before/after comparison).",
    )
    parser.add_argument(
        "--table-merge-gap",
        type=float,
        default=5.0,
        help="Max vertical/horizontal gap (pt) for adjacent table bbox merge when merge is enabled (default: 5).",
    )
    parser.add_argument(
        "--table-merge-horizontal",
        action="store_true",
        help="Also merge horizontally adjacent table bboxes (default: off; overlap/vertical merge always on when merge enabled).",
    )
    parser.add_argument(
        "--table-expand-x-to-page",
        action="store_true",
        help="After merge, expand each table bbox x-range to page width minus margins (y unchanged).",
    )
    parser.add_argument(
        "--table-page-margin-left",
        type=float,
        default=0.0,
        help="Left margin (pt) reserved when using --table-expand-x-to-page (default: 0).",
    )
    parser.add_argument(
        "--table-page-margin-right",
        type=float,
        default=0.0,
        help="Right margin (pt) reserved when using --table-expand-x-to-page (default: 0).",
    )
    parser.add_argument(
        "--text-span-script-bypass",
        action="store_true",
        help="Skip <sup>/<sub> tagging on text blocks (plain PyMuPDF span merge; for before/after comparison).",
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
        image_ocr_engine=args.image_ocr_engine,
        image_ocr_route=args.image_ocr_route,
        image_ocr_dpi=args.image_ocr_dpi,
        image_ocr_min_chars=args.image_ocr_min_chars,
        table_text_engine=args.table_text_engine,
        table_ocr_route=args.table_ocr_route,
        table_ocr_dpi=args.table_ocr_dpi,
        table_ocr_min_chars=args.table_ocr_min_chars,
        paddle_device=args.paddle_device,
        paddle_gpu_id=args.paddle_gpu_id,
        paddle_model_dir=args.paddle_model_dir,
        header_footer_mode=args.header_footer_mode,
        header_top_ratio=args.header_top_ratio,
        footer_bottom_ratio=args.footer_bottom_ratio,
        repeat_min_pages=args.repeat_min_pages,
        repeat_max_chars=args.repeat_max_chars,
        table_merge_bypass=args.table_merge_bypass,
        table_merge_gap=args.table_merge_gap,
        table_merge_horizontal=args.table_merge_horizontal,
        table_expand_x=args.table_expand_x_to_page,
        table_page_margin_left=args.table_page_margin_left,
        table_page_margin_right=args.table_page_margin_right,
        text_span_script_bypass=args.text_span_script_bypass,
    )

    out = artifact_path("stage1_ingestion", "page_blocks.jsonl")
    write_jsonl(out, rows)

    parsing_report = {
        **summary,
        "text_backend": args.text_backend,
        "ocr_candidate_pages_count": len([m for m in metrics_list if m.needs_ocr]),
        "output_schema_version": "page_blocks@1",
    }
    if args.text_backend in ("pymupdf4llm", "hybrid"):
        corpus = extract_pymupdf4llm_corpus(pdf_path)
        corpus_path = artifact_path("stage1_ingestion", "pymupdf4llm_corpus.json")
        write_json(corpus_path, corpus)
        parsing_report["supplemental_text_corpus"] = str(corpus_path)

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
