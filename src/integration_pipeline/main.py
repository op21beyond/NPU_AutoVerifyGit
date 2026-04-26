from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


def run(cmd: List[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all stage skeletons")
    parser.add_argument("--input-pdf", required=True)
    parser.add_argument("--page-start", type=int, default=None, metavar="N")
    parser.add_argument("--page-end", type=int, default=None, metavar="N")
    parser.add_argument(
        "--field-cheat-sheet",
        default=None,
        metavar="PATH",
        help="Optional JSON passed to Stage3: per-scope field overrides (see doc/stage3_field_table_parsing.md).",
    )
    parser.add_argument(
        "--build-rag-index",
        action="store_true",
        help="Pass to Stage1: build FAISS RAG index (requires OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--use-rag",
        action="store_true",
        help="Pass to Stage2/4/4b/4c (and Stage5 when --use-lightrag is not set): FAISS narrowing before LLM.",
    )
    parser.add_argument(
        "--use-lightrag",
        action="store_true",
        help="Pass to Stage5 only: narrow page_blocks via LightRAG (mutually exclusive with --use-rag on Stage5).",
    )
    parser.add_argument("--rag-index-dir", default=None, metavar="DIR")
    parser.add_argument("--rag-top-k", type=int, default=None, metavar="K")
    parser.add_argument("--rag-embedding-model", default=None, metavar="MODEL")
    parser.add_argument("--lightrag-working-dir", default=None, metavar="DIR")
    parser.add_argument("--lightrag-no-rebuild", action="store_true")
    parser.add_argument(
        "--lightrag-query-mode",
        default="naive",
        choices=("naive", "local", "global", "hybrid", "mix"),
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    py = sys.executable

    s1 = [py, str(root / "src" / "stage1_ingestion" / "main.py"), "--input-pdf", args.input_pdf]
    if args.page_start is not None:
        s1.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s1.extend(["--page-end", str(args.page_end)])
    if args.build_rag_index:
        s1.append("--build-rag-index")
    run(s1)

    def _rag_args() -> List[str]:
        out: List[str] = []
        if not args.use_rag:
            return out
        out.append("--use-rag")
        if args.rag_index_dir:
            out.extend(["--rag-index-dir", str(Path(args.rag_index_dir).resolve())])
        if args.rag_top_k is not None:
            out.extend(["--rag-top-k", str(args.rag_top_k)])
        if args.rag_embedding_model:
            out.extend(["--rag-embedding-model", args.rag_embedding_model])
        return out

    s2 = [py, str(root / "src" / "stage2_instruction_extraction" / "main.py")]
    if args.page_start is not None:
        s2.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s2.extend(["--page-end", str(args.page_end)])
    s2.extend(_rag_args())
    run(s2)
    s3 = [py, str(root / "src" / "stage3_field_table_parsing" / "main.py")]
    if args.page_start is not None:
        s3.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s3.extend(["--page-end", str(args.page_end)])
    if args.field_cheat_sheet:
        cheat = Path(args.field_cheat_sheet)
        if not cheat.is_absolute():
            cheat = (Path.cwd() / cheat).resolve()
        else:
            cheat = cheat.resolve()
        s3.extend(["--field-cheat-sheet", str(cheat)])
    run(s3)
    run([py, str(root / "src" / "stage3b_global_field_schema" / "main.py")])
    s4 = [py, str(root / "src" / "stage4_domain_typing" / "main.py")]
    if args.page_start is not None:
        s4.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s4.extend(["--page-end", str(args.page_end)])
    s4.extend(_rag_args())
    run(s4)
    s4b = [py, str(root / "src" / "stage4b_field_datatype_catalog" / "main.py")]
    if args.page_start is not None:
        s4b.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s4b.extend(["--page-end", str(args.page_end)])
    s4b.extend(_rag_args())
    run(s4b)
    s4c = [py, str(root / "src" / "stage4c_field_domain_catalog" / "main.py")]
    if args.page_start is not None:
        s4c.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s4c.extend(["--page-end", str(args.page_end)])
    s4c.extend(_rag_args())
    run(s4c)
    s5 = [py, str(root / "src" / "stage5_constraint_ontology" / "main.py")]
    if args.page_start is not None:
        s5.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s5.extend(["--page-end", str(args.page_end)])
    if args.use_lightrag:
        s5.append("--use-lightrag")
        if args.lightrag_working_dir:
            s5.extend(["--lightrag-working-dir", str(Path(args.lightrag_working_dir).resolve())])
        if args.lightrag_no_rebuild:
            s5.append("--lightrag-no-rebuild")
        s5.extend(["--lightrag-query-mode", args.lightrag_query_mode])
        if args.rag_top_k is not None:
            s5.extend(["--rag-top-k", str(args.rag_top_k)])
        if args.rag_embedding_model:
            s5.extend(["--lightrag-embedding-model", args.rag_embedding_model])
    else:
        s5.extend(_rag_args())
    run(s5)
    run([py, str(root / "src" / "stage6_combination_generation" / "main.py")])
    run([py, str(root / "src" / "stage7_validation_reporting" / "main.py")])


if __name__ == "__main__":
    main()
