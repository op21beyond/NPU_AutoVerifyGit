from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List

from src.common.contracts import load_jsonl, write_json, write_jsonl
from src.common.page_range import (
    filter_page_blocks_by_page_range,
    infer_document_total_pages_from_blocks,
    resolve_page_range,
)
from src.common.runtime import StageRun, artifact_path

from src.stage5_constraint_ontology.constraint_ontology import (
    build_constraint_pruning_index,
    build_constraint_registry,
    build_mission_ontology_graph,
)
from src.stage5_constraint_ontology.ground_truth_eval import (
    build_stage5_outputs_from_ground_truth,
    evaluate_stage5_extraction,
    load_stage5_ground_truth,
)
from src.stage5_constraint_ontology.llm_stage5 import (
    extract_constraint_candidates_openai,
    extract_ontology_values_openai,
    llm_items_to_constraint_rows,
    normalize_constraint_categories_openai,
)
from src.common.lightrag_cli import add_lightrag_arguments
from src.common.lightrag_resolve import narrow_page_blocks_for_stage5_llm
from src.common.rag_cli import add_rag_arguments
from src.common.rag_resolve import DEFAULT_RAG_QUERIES
from src.stage5_constraint_ontology.mission_graph_kuzu import export_mission_ontology_to_kuzu


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage5: constraints, ontology graph, optional LLM constraint/value extraction",
    )
    parser.add_argument("--page-blocks", type=str, default=None)
    parser.add_argument("--page-start", type=int, default=None, metavar="N")
    parser.add_argument("--page-end", type=int, default=None, metavar="N")
    parser.add_argument("--openai-model", default="gpt-4o-mini")
    parser.add_argument("--openai-base-url", default=None)
    parser.add_argument(
        "--skip-llm-constraints",
        action="store_true",
        help="Do not call OpenAI for constraint sentence extraction / category normalization.",
    )
    parser.add_argument(
        "--skip-llm-values",
        action="store_true",
        help="Do not call OpenAI for ontology value extraction pass.",
    )
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
    add_rag_arguments(parser)
    add_lightrag_arguments(parser)
    parser.add_argument(
        "--skip-kuzu-graph-db",
        action="store_true",
        help="Do not export mission_ontology_graph to embedded Kuzu DB (mission_graph_kuzu/).",
    )
    args = parser.parse_args()
    if getattr(args, "use_rag", False) and getattr(args, "use_lightrag", False):
        raise SystemExit("Use either --use-rag or --use-lightrag, not both.")

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
        print(
            f"[GT-as-output] constraints={len(constraints)} nodes={len(ontology.get('nodes', []))} edges={len(ontology.get('edges', []))}"
        )
        return

    pb = Path(args.page_blocks or artifact_path("stage1_ingestion", "page_blocks.jsonl"))
    page_blocks = load_jsonl(pb)
    page_range_applied = None
    if args.page_start is not None or args.page_end is not None:
        total_pages = infer_document_total_pages_from_blocks(page_blocks)
        first_p, last_p = resolve_page_range(total_pages, args.page_start, args.page_end)
        page_blocks = filter_page_blocks_by_page_range(page_blocks, first_p, last_p)
        page_range_applied = (first_p, last_p)

    pb_for_llm, rag_stats = narrow_page_blocks_for_stage5_llm(
        page_blocks,
        args,
        default_rag_query=DEFAULT_RAG_QUERIES["stage5_constraint_extract"],
    )
    if rag_stats and rag_stats.get("rag_error"):
        print(f"WARNING: RAG failed ({rag_stats['rag_error']}); using full page_blocks.")
    if rag_stats and rag_stats.get("lightrag_error"):
        print(f"WARNING: LightRAG failed ({rag_stats['lightrag_error']}); using full page_blocks.")

    domains = load_jsonl(artifact_path("stage4c_field_domain_catalog", "field_domain_catalog.jsonl"))
    datatype_catalog = load_jsonl(artifact_path("stage4b_field_datatype_catalog", "field_datatype_catalog.jsonl"))
    registry = load_jsonl(artifact_path("stage4_domain_typing", "datatype_registry.jsonl"))
    instructions = load_jsonl(artifact_path("stage2_instruction_extraction", "instruction_catalog.jsonl"))

    base_constraints = build_constraint_registry(domains, instructions, run)
    llm_constraints: List[Dict[str, Any]] = []
    category_payload: Dict[str, Any] = {"canonical_categories": [], "mapping": {}}
    candidates_payload: List[Dict[str, Any]] = []
    llm_skip_reason: str | None = None

    if not args.skip_llm_constraints and os.environ.get("OPENAI_API_KEY"):
        try:
            candidates_payload = extract_constraint_candidates_openai(
                pb_for_llm,
                run,
                model=args.openai_model,
                base_url=args.openai_base_url,
            )
            write_json(out_dir / "constraint_candidates.json", {"items": candidates_payload})
            labels = [str(x.get("constraint_category_candidate", "")).strip() for x in candidates_payload]
            # Same batch as LLM: Stage4c field_domain allowed_value_form (e.g. range, enum) may align with extraction phrasing
            extra_domain_labels = [
                str(d.get("allowed_value_form", "")).strip()
                for d in domains
                if str(d.get("allowed_value_form", "")).strip()
            ]
            category_payload = normalize_constraint_categories_openai(
                labels,
                run,
                model=args.openai_model,
                base_url=args.openai_base_url,
                extra_labels=extra_domain_labels,
            )
            write_json(out_dir / "constraint_type_catalog.json", category_payload)
            mapping = category_payload.get("mapping") or {}
            if not isinstance(mapping, dict):
                mapping = {}
            llm_constraints = llm_items_to_constraint_rows(
                candidates_payload,
                mapping,
                run,
                start_index=0,
            )
        except Exception as ex:
            llm_skip_reason = f"llm_constraints_failed: {ex}"
    else:
        if args.skip_llm_constraints:
            llm_skip_reason = "skip_llm_constraints_flag"
        elif not os.environ.get("OPENAI_API_KEY"):
            llm_skip_reason = "no_openai_api_key"

    all_constraints = base_constraints + llm_constraints

    ontology = build_mission_ontology_graph(all_constraints, instructions, datatype_catalog, registry)

    value_bindings: List[Dict[str, Any]] = []
    if not args.skip_llm_values and os.environ.get("OPENAI_API_KEY"):
        try:
            nodes = ontology.get("nodes") or []
            if isinstance(nodes, list):
                value_bindings = extract_ontology_values_openai(
                    pb_for_llm,
                    nodes,
                    run,
                    model=args.openai_model,
                    base_url=args.openai_base_url,
                )
        except Exception as ex:
            if llm_skip_reason:
                llm_skip_reason += f"; values_failed: {ex}"
            else:
                llm_skip_reason = f"llm_values_failed: {ex}"

    write_jsonl(out_dir / "constraint_registry.jsonl", all_constraints)
    pruning_index = build_constraint_pruning_index(all_constraints, category_payload)
    write_json(out_dir / "constraint_pruning_index.json", pruning_index)
    write_json(out_dir / "mission_ontology_graph.json", ontology)
    if value_bindings:
        write_json(out_dir / "ontology_value_bindings.json", {"bindings": value_bindings})

    report_summary: Dict[str, Any] = {
        "stage_run_id": run.stage_run_id,
        "constraint_count_domain_derived": len(base_constraints),
        "constraint_count_llm": len(llm_constraints),
        "constraint_count_total": len(all_constraints),
        "ontology_node_count": len(ontology.get("nodes", [])),
        "ontology_edge_count": len(ontology.get("edges", [])),
        "value_bindings_count": len(value_bindings),
        "page_blocks_path": str(pb.resolve()),
        "page_range": (
            {"first": page_range_applied[0], "last": page_range_applied[1]} if page_range_applied else None
        ),
        "openai_model": args.openai_model,
        "llm_constraints_ran": bool(llm_constraints) or bool(candidates_payload),
        "llm_values_ran": bool(value_bindings),
        "llm_skip_reason": llm_skip_reason,
        "rag": rag_stats,
        "constraint_pruning_index_path": str((out_dir / "constraint_pruning_index.json").resolve()),
    }
    if not args.skip_kuzu_graph_db:
        kuzu_dir = out_dir / "mission_graph_kuzu"
        try:
            db_file = export_mission_ontology_to_kuzu(ontology, kuzu_dir)
            report_summary["kuzu_graph_db_path"] = str(kuzu_dir.resolve())
            report_summary["kuzu_graph_db_file"] = str(db_file.resolve())
        except Exception as ex:
            report_summary["kuzu_export_error"] = str(ex)
            print(f"WARNING: Kuzu export failed: {ex}")
    write_json(out_dir / "stage5_report.json", report_summary)

    write_json(out_dir / "run_manifest.json", run.to_dict())

    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        gt = load_stage5_ground_truth(gt_path)
        report = evaluate_stage5_extraction(all_constraints, ontology, gt)
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
        f"constraints={len(all_constraints)} (domain={len(base_constraints)} llm={len(llm_constraints)}) "
        f"nodes={len(ontology.get('nodes', []))} edges={len(ontology.get('edges', []))} "
        f"value_bindings={len(value_bindings)}"
    )


if __name__ == "__main__":
    main()
