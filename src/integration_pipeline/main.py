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
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    py = sys.executable

    s1 = [py, str(root / "src" / "stage1_ingestion" / "main.py"), "--input-pdf", args.input_pdf]
    if args.page_start is not None:
        s1.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s1.extend(["--page-end", str(args.page_end)])
    run(s1)

    s2 = [py, str(root / "src" / "stage2_instruction_extraction" / "main.py")]
    if args.page_start is not None:
        s2.extend(["--page-start", str(args.page_start)])
    if args.page_end is not None:
        s2.extend(["--page-end", str(args.page_end)])
    run(s2)
    run([py, str(root / "src" / "stage3_field_table_parsing" / "main.py")])
    run([py, str(root / "src" / "stage3b_global_field_schema" / "main.py")])
    run([py, str(root / "src" / "stage4_domain_typing" / "main.py")])
    run([py, str(root / "src" / "stage5_constraint_ontology" / "main.py")])
    run([py, str(root / "src" / "stage6_combination_generation" / "main.py")])
    run([py, str(root / "src" / "stage7_validation_reporting" / "main.py")])


if __name__ == "__main__":
    main()
