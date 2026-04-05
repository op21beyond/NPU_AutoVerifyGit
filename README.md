# NPU AutoVerify Skeleton

Stage-based skeleton for NPU command extraction and testcase generation.

## Quick start

Install dependencies and set `PYTHONPATH` to the repository root (so `import src...` resolves).

```bash
pip install -r requirements.txt
```

Recommended stage order:

```bash
python -m src.stage1_ingestion.main --input-pdf "path/to/architecture.pdf"
python -m src.stage2_instruction_extraction.main
python -m src.stage3_field_table_parsing.main
python -m src.stage3b_global_field_schema.main
python -m src.stage4_domain_typing.main
python -m src.stage4b_field_datatype_catalog.main
python -m src.stage4c_field_domain_catalog.main
python -m src.stage5_constraint_ontology.main
```

Set **`OPENAI_API_KEY`** for Stage 2 and Stage 4 / 4b / 4c OpenAI paths (or use `--ground-truth-as-output` per stage).

Optional **page range** (same semantics for Stage 1–4c where `page_blocks` is used): `--page-start N` and/or `--page-end N` (1-based). Neither → all pages; start only → that page through end of document; end only → page 1 through that page; both → inclusive range (clamped to document length). Stages 3 and 4–4c filter loaded `page_blocks` by `page` when a range is set.

Recommended evaluation order (with sample GT files):

```bash
python -m src.stage2_instruction_extraction.main --ground-truth ground_truth_examples/stage2_ground_truth.txt
python -m src.stage3_field_table_parsing.main --ground-truth ground_truth_examples/stage3_ground_truth.txt
python -m src.stage3b_global_field_schema.main --ground-truth ground_truth_examples/stage3b_ground_truth.txt
python -m src.stage4_domain_typing.main --ground-truth ground_truth_examples/stage4_datatype_registry_ground_truth.txt
python -m src.stage4b_field_datatype_catalog.main --ground-truth ground_truth_examples/stage4b_field_datatype_ground_truth.txt
python -m src.stage4c_field_domain_catalog.main --ground-truth ground_truth_examples/stage4c_field_domain_ground_truth.txt
python -m src.stage5_constraint_ontology.main --ground-truth ground_truth_examples/stage5_ground_truth.txt
```

Run Stage 1 only:

```bash
python src/stage1_ingestion/main.py --input-pdf "path/to/architecture.pdf"
```

Stage 1 (optional hybrid text backend): `python src/stage1_ingestion/main.py --input-pdf "...pdf" --text-backend hybrid` writes supplemental `artifacts/stage1_ingestion/pymupdf4llm_corpus.json`.

Stage 1 also supports **table bbox merge** (default on), optional **full-width x expansion**, **cross-page table merge** (edge-aligned bottom/top blocks), **`<sup>`/`<sub>` tagging** with `--max-subsup-length`, optional **`--preserve-heading`** (font-size role tags in `raw_text`), and **`--export-reading-order pdf|docx|md`**. Use `--table-merge-bypass`, `--text-span-script-bypass`, or `--no-cross-page-table-merge` for comparisons. See [`doc/stage1_ingestion.md`](doc/stage1_ingestion.md).

Stage 2 (default OpenAI extraction): set `OPENAI_API_KEY`, then e.g. `python src/stage2_instruction_extraction/main.py --openai-model gpt-4o-mini`. Alternative: `--ground-truth-as-catalog --ground-truth PATH` skips the API and builds the catalog from a reference file only.

Stage 2 (optional supplemental text from Stage 1): auto-loads `artifacts/stage1_ingestion/pymupdf4llm_corpus.json` if present. Override via `--supplemental-text-corpus PATH`, disable via `--disable-default-supplemental-text`.

Stage 2 (evaluate vs reference list): `python src/stage2_instruction_extraction/main.py --ground-truth path/to/instructions.txt` — writes `artifacts/stage2_instruction_extraction/evaluation_report.json` (precision/recall/F1).

Stage 2 (page coverage, OpenAI path by default): writes `artifacts/stage2_instruction_extraction/page_coverage.json` and `page_coverage.png` (needs **`matplotlib`** from `requirements.txt`). Disable with `--no-page-coverage`. Interactive chart: **`tools/page_coverage_viewer`** (requires **Node.js** + `npm install`; see [`tools/page_coverage_viewer/README.md`](tools/page_coverage_viewer/README.md)).

## Ground Truth Quickstart

Sample files are provided in `ground_truth_examples/` for Stage2~5, using easy-to-edit text formats.

Evaluate with examples:

```bash
python -m src.stage2_instruction_extraction.main --ground-truth ground_truth_examples/stage2_ground_truth.txt
python -m src.stage3_field_table_parsing.main --ground-truth ground_truth_examples/stage3_ground_truth.txt
python -m src.stage3b_global_field_schema.main --ground-truth ground_truth_examples/stage3b_ground_truth.txt
python -m src.stage4_domain_typing.main --ground-truth ground_truth_examples/stage4_datatype_registry_ground_truth.txt
python -m src.stage4b_field_datatype_catalog.main --ground-truth ground_truth_examples/stage4b_field_datatype_ground_truth.txt
python -m src.stage4c_field_domain_catalog.main --ground-truth ground_truth_examples/stage4c_field_domain_ground_truth.txt
python -m src.stage5_constraint_ontology.main --ground-truth ground_truth_examples/stage5_ground_truth.txt
```

Build outputs directly from GT:

```bash
python -m src.stage2_instruction_extraction.main --ground-truth-as-catalog --ground-truth ground_truth_examples/stage2_ground_truth.txt
python -m src.stage3_field_table_parsing.main --ground-truth-as-output --ground-truth ground_truth_examples/stage3_ground_truth.txt
python -m src.stage3b_global_field_schema.main --ground-truth-as-output --ground-truth ground_truth_examples/stage3b_ground_truth.txt
python -m src.stage4_domain_typing.main --ground-truth-as-output --ground-truth ground_truth_examples/stage4_datatype_registry_ground_truth.txt
python -m src.stage4b_field_datatype_catalog.main --ground-truth-as-output --ground-truth ground_truth_examples/stage4b_field_datatype_ground_truth.txt
python -m src.stage4c_field_domain_catalog.main --ground-truth-as-output --ground-truth ground_truth_examples/stage4c_field_domain_ground_truth.txt
python -m src.stage5_constraint_ontology.main --ground-truth-as-output --ground-truth ground_truth_examples/stage5_ground_truth.txt
```

Notes:
- Stage2/3/3b text GT formats are line-based (see files in `ground_truth_examples/`).
- Stage3 optional: `--field-cheat-sheet ground_truth_examples/field_cheat_sheet.example.json` overrides per-scope field rows (see `doc/stage3_field_table_parsing.md`).
- Stage4 / 4b / 4c: use split examples `stage4_datatype_registry_ground_truth.txt`, `stage4b_field_datatype_ground_truth.txt`, `stage4c_field_domain_ground_truth.txt` (`TYPE|...`, `DTYPE|...`, `DOMAIN|...`). Combined `stage4_ground_truth.txt` remains for reference.
- Stage5 text GT supports `CONSTRAINT|...`, `NODE|...`, `EDGE|...` lines.
- Partial GT is allowed: you can provide only a subset of items/fields for iterative evaluation.

Run the integration skeleton:

```bash
python src/integration_pipeline/main.py --input-pdf "path/to/architecture.pdf"
```

Optional page slice (passed through integration to Stage 1–5): `--page-start N` and/or `--page-end N` — same semantics as individual stages (see Quick start above). Stage 5 uses filtered `page_blocks` for optional OpenAI constraint/value passes (`--skip-llm-constraints` / `--skip-llm-values` to disable).

Optional Stage3 field overrides: `--field-cheat-sheet ground_truth_examples/field_cheat_sheet.example.json` (forwarded only to Stage3; see `doc/stage3_field_table_parsing.md`).

Optional **RAG** (FAISS built at Stage1, used at Stage2/4/4b/4c/5): `--build-rag-index` on the integration command (requires `OPENAI_API_KEY`), then `--use-rag` with optional `--rag-index-dir`, `--rag-top-k`, `--rag-embedding-model`. Stage5 also writes a **Kuzu** graph DB at `artifacts/stage5_constraint_ontology/mission_graph_kuzu/graph.kuzu` unless `--skip-kuzu-graph-db` is passed to that stage. Details: `doc/rag_integration_checklist.md`.

Artifacts are written to `artifacts/`.

## Tools

The [`tools/`](tools/) folder holds **optional utilities** that are not part of the main stage pipeline—small apps and scripts for development, manual testing, and ad-hoc LLM experiments.

- **`ontology_graph_viewer`**: Streamlit + Pyvis for `mission_ontology_graph.json` (interactive drag/zoom; usage instructions in-app). `streamlit run tools/ontology_graph_viewer/app.py`. See [`tools/ontology_graph_viewer/README.md`](tools/ontology_graph_viewer/README.md).
- **`rag_graph_chatbot`**: Streamlit UI over Stage1 FAISS **`rag_index`** + Stage5 Kuzu **`mission_graph_kuzu/graph.kuzu`** with OpenAI (paths and multiturn in `st.session_state`). `pip install -r tools/requirements-tools.txt`, then `streamlit run tools/rag_graph_chatbot/app.py`. See [`tools/README.md`](tools/README.md).
- **`streamlit_llm_chat`**: Streamlit UI that connects to up to five company remote LLMs (OpenAI-compatible Chat Completions, configured via `COMPANY_LLM_1` … `COMPANY_LLM_5` env vars), loads Stage1 **`page_blocks.jsonl`**, builds a **`selected_page_blocks`** map from a one-line page/block selector, and sends System/User prompts (single- or multi-turn). Install extras with `pip install -r tools/requirements-tools.txt`, then run `streamlit run tools/streamlit_llm_chat/app.py` from the repo root.

- **`page_coverage_viewer`**: Vite + React chart for Stage 2 `page_coverage.json` (zoom with brush; complements default `page_coverage.png`). **Dependency:** Node.js (LTS 권장) + npm — not installed via `pip`. See [`tools/page_coverage_viewer/README.md`](tools/page_coverage_viewer/README.md).

Full details, selector syntax, and environment variables: **[`tools/README.md`](tools/README.md)**.

## Structure

- `src/stage*_*/main.py`: stage entry points (`stage3b` = global field schema; `stage4b` / `stage4c` = field–type map and value domains)
- `src/integration_pipeline/main.py`: end-to-end runner
- `src/common`: shared helpers
- `data_contracts`: JSON schemas for stage IO
- `doc`: mission/plan/stage docs
- `tools/`: optional dev utilities (see [`tools/README.md`](tools/README.md))
