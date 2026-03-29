from __future__ import annotations

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path


def main() -> None:
    run = StageRun.create("stage5_constraint_ontology")
    domains = load_jsonl(artifact_path("stage4_domain_typing", "field_domain_catalog.jsonl"))
    instructions = load_jsonl(artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl"))
    constraints = [
        {
            "trace_id": f"{run.stage_run_id}:c0",
            "constraint_id": "C_PLACEHOLDER_001",
            "constraint_type_level1": "range",
            "constraint_type_level2": "instruction-specific",
            "expression": "0 <= OPCODE <= 15",
            "classification_rationale": "seed placeholder",
            "source_refs": domains[0]["source_refs"] if domains else [],
            "applies_to": {"entity_type": "Field", "entity_name": "OPCODE"},
        }
    ]
    inst0 = instructions[0] if instructions else {}
    eu_name = str(inst0.get("execution_unit", "UNKNOWN_UNIT"))
    inst_name = str(inst0.get("instruction_name", "UNKNOWN"))
    inst_kind = str(inst0.get("instruction_kind", "unknown"))
    opc_val = inst0.get("opcode_value")
    instr_id = f"Instr:{opc_val}" if opc_val is not None else f"Instr:{inst_name}"
    ontology = {
        "nodes": [
            {"type": "IP", "id": "IP:sample", "ip_name": "sample", "ip_type": "npu", "ip_version": "v0"},
            {"type": "ExecutionUnit", "id": f"EU:{eu_name}", "name": eu_name},
            {
                "type": "Instruction",
                "id": instr_id,
                "instruction_name": inst_name,
                "instruction_kind": inst_kind,
                "opcode_raw": inst0.get("opcode_raw"),
                "opcode_radix": inst0.get("opcode_radix"),
                "opcode_value": opc_val,
            },
            {"type": "Field", "id": "Field:OPCODE"},
            {"type": "Constraint", "id": "Constraint:C_PLACEHOLDER_001"},
        ],
        "edges": [
            {"from": instr_id, "rel": "EXECUTES_ON", "to": f"EU:{eu_name}"},
            {"from": "IP:sample", "rel": "HAS_INSTRUCTION", "to": instr_id},
            {"from": "Constraint:C_PLACEHOLDER_001", "rel": "APPLIES_TO", "to": "Field:OPCODE"},
        ],
    }
    write_jsonl(artifact_path("stage5_constraint_ontology", "constraint_registry.jsonl"), constraints)
    write_json(artifact_path("stage5_constraint_ontology", "mission_ontology_graph.json"), ontology)
    write_json(artifact_path("stage5_constraint_ontology", "run_manifest.json"), run.to_dict())
    print("ontology skeleton generated")


if __name__ == "__main__":
    main()
