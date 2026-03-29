# NPU AutoVerify Skeleton

Stage-based skeleton for NPU command extraction and testcase generation.

## Quick start

Install dependencies and set `PYTHONPATH` to the repository root (so `import src...` resolves).

```bash
pip install -r requirements.txt
```

Run Stage 1 only:

```bash
python src/stage1_ingestion/main.py --input-pdf "path/to/architecture.pdf"
```

Stage 2 (optional LLM): set `OPENAI_API_KEY`, then e.g. `python src/stage2_instruction_extraction/main.py --extractor openai --openai-model gpt-4o-mini`. Default is rule-based `--extractor regex`.

Stage 2 (evaluate vs reference list): `python src/stage2_instruction_extraction/main.py --ground-truth path/to/instructions.txt` — writes `artifacts/stage2_instruction_extraction/evaluation_report.json` (precision/recall/F1).

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
