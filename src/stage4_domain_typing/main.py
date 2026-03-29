from __future__ import annotations

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path


def main() -> None:
    run = StageRun.create("stage4_domain_typing")
    fields = load_jsonl(artifact_path("stage3_field_table_parsing", "instruction_field_map.jsonl"))

    # 문서 전역에서 수집한 타입 레지스트리 스켈레톤 (실제로는 TRM 스캔 후 채움)
    registry_rows = [
        {
            "trace_id": f"{run.stage_run_id}:reg:uint4",
            "type_id": "uint4",
            "type_name_raw": "uint4",
            "type_name_normalized": "uint4",
            "category": "software_primitive",
            "description": "placeholder 4-bit unsigned",
            "value_constraint_summary": "typically 0..15",
            "value_generation_method": "",
            "source_refs": [],
        },
        {
            "trace_id": f"{run.stage_run_id}:reg:ip_custom",
            "type_id": "IP_ARCH_TYPE_PLACEHOLDER",
            "type_name_raw": "ArchSpecificFmt",
            "type_name_normalized": "ArchSpecificFmt",
            "category": "ip_architecture",
            "description": "replace with TRM-defined type",
            "value_constraint_summary": "TBD from architecture chapter",
            "value_generation_method": "TBD: encoding / derivation rules from TRM",
            "source_refs": [],
        },
    ]
    write_jsonl(artifact_path("stage4_domain_typing", "datatype_registry.jsonl"), registry_rows)

    datatype_rows = []
    domain_rows = []
    for i, row in enumerate(fields):
        instr = row.get("instruction_name", "")
        dtype_ref = "uint4"
        datatype_rows.append(
            {
                "trace_id": f"{run.stage_run_id}:dtype:{i}",
                "instruction_name": instr,
                "field_name": row["field_name"],
                "data_type_raw": dtype_ref,
                "data_type_ref": dtype_ref,
                "source_refs": row.get("source_refs", []),
            }
        )
        domain_rows.append(
            {
                "trace_id": f"{run.stage_run_id}:domain:{i}",
                "field_name": row["field_name"],
                "allowed_value_form": "range",
                "allowed_values_or_range": "0..15",
                "source_refs": row.get("source_refs", []),
            }
        )
    write_jsonl(artifact_path("stage4_domain_typing", "field_datatype_catalog.jsonl"), datatype_rows)
    write_jsonl(artifact_path("stage4_domain_typing", "field_domain_catalog.jsonl"), domain_rows)
    write_json(artifact_path("stage4_domain_typing", "run_manifest.json"), run.to_dict())
    print(f"registry types={len(registry_rows)} fields={len(fields)}")


if __name__ == "__main__":
    main()
