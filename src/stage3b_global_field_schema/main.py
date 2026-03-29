from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Set

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path


def _canonical_field_name(name: str) -> str:
    s = name.strip()
    s = re.sub(r"\s+", "_", s)
    return s


def main() -> None:
    run = StageRun.create("stage3b_global_field_schema")
    rows = load_jsonl(artifact_path("stage3_field_table_parsing", "instruction_field_map.jsonl"))

    names: Set[str] = set()
    per_instruction: Dict[str, Set[str]] = defaultdict(set)
    for row in rows:
        raw_fn = row.get("field_name", "")
        fn = _canonical_field_name(raw_fn) if raw_fn else ""
        if fn:
            names.add(fn)
            ins = row.get("instruction_name", "")
            if ins:
                per_instruction[ins].add(fn)

    canonical = sorted(names)

    alias_rows: List[Dict[str, Any]] = []

    schema: Dict[str, Any] = {
        "stage_name": run.stage_name,
        "stage_run_id": run.stage_run_id,
        "canonical_field_names": canonical,
        "field_count_per_instruction": {k: sorted(v) for k, v in per_instruction.items()},
        "alias_catalog": "field_alias_map.jsonl",
        "output_schema_version": "global_field_schema@1",
    }
    out_dir = artifact_path("stage3b_global_field_schema")
    write_json(out_dir / "global_field_schema.json", schema)
    write_jsonl(out_dir / "field_alias_map.jsonl", alias_rows)
    write_json(out_dir / "run_manifest.json", run.to_dict())
    print(f"canonical fields={len(canonical)} instructions={len(per_instruction)}")


if __name__ == "__main__":
    main()
