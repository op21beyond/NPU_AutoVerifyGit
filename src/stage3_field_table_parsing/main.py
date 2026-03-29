from __future__ import annotations

import argparse
from pathlib import Path

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage3_field_table_parsing.field_tables import build_instruction_field_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage3: instruction field map from tables / loose text")
    parser.add_argument("--page-blocks", type=str, default=None)
    parser.add_argument("--instruction-catalog", type=str, default=None)
    args = parser.parse_args()

    pb = Path(args.page_blocks or artifact_path("stage1_ingestion", "page_blocks.jsonl"))
    ic = Path(args.instruction_catalog or artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl"))

    page_blocks = load_jsonl(pb)
    instructions = load_jsonl(ic)

    run = StageRun.create("stage3_field_table_parsing")
    rows = build_instruction_field_map(page_blocks, instructions, run)

    out = artifact_path("stage3_field_table_parsing", "instruction_field_map.jsonl")
    write_jsonl(out, rows)
    write_json(
        artifact_path("stage3_field_table_parsing", "parsing_summary.json"),
        {
            "stage_run_id": run.stage_run_id,
            "field_row_count": len(rows),
            "instruction_count_input": len(instructions),
            "output_schema_version": "instruction_field_map@1",
        },
    )
    write_json(artifact_path("stage3_field_table_parsing", "run_manifest.json"), run.to_dict())
    print(f"wrote {len(rows)} field rows -> {out}")


if __name__ == "__main__":
    main()
