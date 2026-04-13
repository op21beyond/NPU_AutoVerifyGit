from __future__ import annotations

from src.common.contracts import load_json, load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path


def main() -> None:
    run = StageRun.create("stage6_combination_generation")
    constraints = load_jsonl(artifact_path("stage5_constraint_ontology", "constraint_registry.jsonl"))
    gpath = artifact_path("stage3b_global_field_schema", "global_field_schema.json")
    global_schema = load_json(gpath) if gpath.exists() else {}
    _canonical = global_schema.get("canonical_field_names", [])

    s5 = artifact_path("stage5_constraint_ontology", "constraint_pruning_index.json")
    pruning = load_json(s5) if s5.exists() else {}
    # Future: prune combinations using pruning["canonical_categories"] + per-row constraint_type_level1
    combination_context = {
        "stage_run_id": run.stage_run_id,
        "constraint_pruning_index": pruning,
        "constraint_registry_row_count": len(constraints),
        "canonical_categories_ref": (pruning or {}).get("canonical_categories") or [],
    }
    write_json(artifact_path("stage6_combination_generation", "combination_context.json"), combination_context)

    rows = [
        {
            "trace_id": f"{run.stage_run_id}:t0",
            "instruction_name": "NOP_PLACEHOLDER",
            "variation": None,
            "OPCODE": 0,
            "constraint_satisfaction_status": "assumed_valid",
            "canonical_field_names_ref": _canonical,
            "source_refs": constraints[0]["source_refs"] if constraints else [],
        }
    ]
    out = artifact_path("stage6_combination_generation", "test_case_matrix.jsonl")
    write_jsonl(out, rows)
    write_json(artifact_path("stage6_combination_generation", "run_manifest.json"), run.to_dict())
    print(f"wrote {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
