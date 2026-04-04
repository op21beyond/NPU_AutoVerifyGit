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
python -m src.stage5_constraint_ontology.main
```

Recommended evaluation order (with sample GT files):

```bash
python -m src.stage2_instruction_extraction.main --ground-truth ground_truth_examples/stage2_ground_truth.txt
python -m src.stage3_field_table_parsing.main --ground-truth ground_truth_examples/stage3_ground_truth.txt
python -m src.stage3b_global_field_schema.main --ground-truth ground_truth_examples/stage3b_ground_truth.txt
python -m src.stage4_domain_typing.main --ground-truth ground_truth_examples/stage4_ground_truth.txt
python -m src.stage5_constraint_ontology.main --ground-truth ground_truth_examples/stage5_ground_truth.txt
```

Run Stage 1 only:

```bash
python src/stage1_ingestion/main.py --input-pdf "path/to/architecture.pdf"
```

Stage 1 (optional hybrid text backend): `python src/stage1_ingestion/main.py --input-pdf "...pdf" --text-backend hybrid` writes supplemental `artifacts/stage1_ingestion/pymupdf4llm_corpus.json`.

Stage 1 also supports **table bbox merge** (default on), optional **full-width x expansion**, **cross-page table merge** (edge-aligned bottom/top blocks), **`<sup>`/`<sub>` tagging** with `--max-subsup-length`, optional **`--preserve-heading`** (font-size role tags in `raw_text`), and **`--export-reading-order pdf|docx|md`**. Use `--table-merge-bypass`, `--text-span-script-bypass`, or `--no-cross-page-table-merge` for comparisons. See [`doc/stage1_ingestion.md`](doc/stage1_ingestion.md).

Stage 2 (optional LLM): set `OPENAI_API_KEY`, then e.g. `python src/stage2_instruction_extraction/main.py --extractor openai --openai-model gpt-4o-mini`. Default is rule-based `--extractor regex`.

Stage 2 (optional supplemental text from Stage 1): auto-loads `artifacts/stage1_ingestion/pymupdf4llm_corpus.json` if present. Override via `--supplemental-text-corpus PATH`, disable via `--disable-default-supplemental-text`.

Stage 2 (evaluate vs reference list): `python src/stage2_instruction_extraction/main.py --ground-truth path/to/instructions.txt` — writes `artifacts/stage2_instruction_extraction/evaluation_report.json` (precision/recall/F1).

## Ground Truth Quickstart

Sample files are provided in `ground_truth_examples/` for Stage2~5, using easy-to-edit text formats.

Evaluate with examples:

```bash
python -m src.stage2_instruction_extraction.main --ground-truth ground_truth_examples/stage2_ground_truth.txt
python -m src.stage3_field_table_parsing.main --ground-truth ground_truth_examples/stage3_ground_truth.txt
python -m src.stage3b_global_field_schema.main --ground-truth ground_truth_examples/stage3b_ground_truth.txt
python -m src.stage4_domain_typing.main --ground-truth ground_truth_examples/stage4_ground_truth.txt
python -m src.stage5_constraint_ontology.main --ground-truth ground_truth_examples/stage5_ground_truth.txt
```

Build outputs directly from GT:

```bash
python -m src.stage2_instruction_extraction.main --ground-truth-as-catalog --ground-truth ground_truth_examples/stage2_ground_truth.txt
python -m src.stage3_field_table_parsing.main --ground-truth-as-output --ground-truth ground_truth_examples/stage3_ground_truth.txt
python -m src.stage3b_global_field_schema.main --ground-truth-as-output --ground-truth ground_truth_examples/stage3b_ground_truth.txt
python -m src.stage4_domain_typing.main --ground-truth-as-output --ground-truth ground_truth_examples/stage4_ground_truth.txt
python -m src.stage5_constraint_ontology.main --ground-truth-as-output --ground-truth ground_truth_examples/stage5_ground_truth.txt
```

Notes:
- Stage2/3/3b text GT formats are line-based (see files in `ground_truth_examples/`).
- Stage4 text GT supports `TYPE|...`, `DTYPE|...`, `DOMAIN|...` lines.
- Stage5 text GT supports `CONSTRAINT|...`, `NODE|...`, `EDGE|...` lines.
- Partial GT is allowed: you can provide only a subset of items/fields for iterative evaluation.

Run the integration skeleton:

```bash
python src/integration_pipeline/main.py --input-pdf "path/to/architecture.pdf"
```

Artifacts are written to `artifacts/`.

## Structure

- `src/stage*_*/main.py`: stage entry points (`stage3b_global_field_schema` = 전역 필드 집합·별칭)
- `src/integration_pipeline/main.py`: end-to-end runner
- `src/common`: shared helpers
- `data_contracts`: JSON schemas for stage IO
- `doc`: mission/plan/stage docs
