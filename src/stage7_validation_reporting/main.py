from __future__ import annotations

import csv

from src.common.contracts import load_jsonl, write_json
from src.common.runtime import StageRun, artifact_path


def main() -> None:
    run = StageRun.create("stage7_validation_reporting")
    rows = load_jsonl(artifact_path("stage6_combination_generation", "test_case_matrix.jsonl"))
    out_csv = artifact_path("stage7_validation_reporting", "npu_testcase_table.csv")
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    if rows:
        fieldnames = sorted({k for row in rows for k in row.keys()})
        with out_csv.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    write_json(
        artifact_path("stage7_validation_reporting", "coverage_report.json"),
        {"row_count": len(rows), "status": "skeleton"},
    )
    write_json(artifact_path("stage7_validation_reporting", "run_manifest.json"), run.to_dict())
    print(f"exported csv -> {out_csv}")


if __name__ == "__main__":
    main()
