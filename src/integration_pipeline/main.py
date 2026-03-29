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
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    py = sys.executable

    run([py, str(root / "src" / "stage1_ingestion" / "main.py"), "--input-pdf", args.input_pdf])
    run([py, str(root / "src" / "stage2_instruction_extraction" / "main.py")])
    run([py, str(root / "src" / "stage3_field_table_parsing" / "main.py")])
    run([py, str(root / "src" / "stage3b_global_field_schema" / "main.py")])
    run([py, str(root / "src" / "stage4_domain_typing" / "main.py")])
    run([py, str(root / "src" / "stage5_constraint_ontology" / "main.py")])
    run([py, str(root / "src" / "stage6_combination_generation" / "main.py")])
    run([py, str(root / "src" / "stage7_validation_reporting" / "main.py")])


if __name__ == "__main__":
    main()
