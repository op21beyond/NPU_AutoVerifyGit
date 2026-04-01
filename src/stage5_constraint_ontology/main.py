from __future__ import annotations

import argparse
from pathlib import Path

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.runtime import StageRun, artifact_path

from src.stage5_constraint_ontology.constraint_ontology import (
    build_constraint_registry,
    build_mission_ontology_graph,
)
from src.stage5_constraint_ontology.ground_truth_eval import (
    build_stage5_outputs_from_ground_truth,
    evaluate_stage5_extraction,
    load_stage5_ground_truth,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage5: constraint registry and mission ontology graph")
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        metavar="PATH",
        help="Ground truth file (.json or .txt/.lst/.list) for evaluation.",
    )
    parser.add_argument(
        "--ground-truth-as-output",
        action="store_true",
        help="Skip extraction and write stage5 artifacts directly from --ground-truth.",
    )
    args = parser.parse_args()

    run = StageRun.create("stage5_constraint_ontology")
    out_dir = artifact_path("stage5_constraint_ontology")

    if args.ground_truth_as_output:
        if not args.ground_truth:
            raise SystemExit("--ground-truth-as-output requires --ground-truth PATH")
        gt_path = Path(args.ground_truth)
        gt = load_stage5_ground_truth(gt_path)
        constraints, ontology = build_stage5_outputs_from_ground_truth(gt, run)
        write_jsonl(out_dir / "constraint_registry.jsonl", constraints)
        write_json(out_dir / "mission_ontology_graph.json", ontology)
        write_json(out_dir / "run_manifest.json", run.to_dict())
        print(f"[GT-as-output] constraints={len(constraints)} nodes={len(ontology.get('nodes', []))} edges={len(ontology.get('edges', []))}")
        return

    domains = load_jsonl(artifact_path("stage4_domain_typing", "field_domain_catalog.jsonl"))
    datatype_catalog = load_jsonl(artifact_path("stage4_domain_typing", "field_datatype_catalog.jsonl"))
    registry = load_jsonl(artifact_path("stage4_domain_typing", "datatype_registry.jsonl"))
    instructions = load_jsonl(artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl"))

    constraints = build_constraint_registry(domains, instructions, run)
    ontology = build_mission_ontology_graph(constraints, instructions, datatype_catalog, registry)

    write_jsonl(out_dir / "constraint_registry.jsonl", constraints)
    write_json(out_dir / "mission_ontology_graph.json", ontology)
    write_json(out_dir / "run_manifest.json", run.to_dict())

    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        gt = load_stage5_ground_truth(gt_path)
        report = evaluate_stage5_extraction(constraints, ontology, gt)
        report["ground_truth_path"] = str(gt_path.resolve())
        write_json(out_dir / "evaluation_report.json", report)
        sec = report.get("sections") or {}
        if "constraint_registry" in sec:
            m = sec["constraint_registry"]["metrics"]
            print(f"eval[constraint_registry] P={m.get('precision')} R={m.get('recall')} F1={m.get('f1')}")
        mog = sec.get("mission_ontology_graph")
        if isinstance(mog, dict):
            if "nodes" in mog:
                mn = mog["nodes"]["metrics"]
                print(f"eval[ontology.nodes] P={mn.get('precision')} R={mn.get('recall')} F1={mn.get('f1')}")
            if "edges" in mog:
                me = mog["edges"]["metrics"]
                print(f"eval[ontology.edges] P={me.get('precision')} R={me.get('recall')} F1={me.get('f1')}")

    print(
        f"constraints={len(constraints)} nodes={len(ontology.get('nodes', []))} edges={len(ontology.get('edges', []))}"
    )


if __name__ == "__main__":
    main()
