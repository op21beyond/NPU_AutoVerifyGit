# Page coverage viewer

Interactive chart for Stage 2 **`page_coverage.json`** (one bar per page in the analyzed range). Use when a 300-page PNG is hard to read.

## Requirements

- **Node.js** (LTS 권장, npm 포함). 파이프라인 Python 의존성(`pip install -r requirements.txt`)과 별개입니다.
- Stage 2가 만든 `page_coverage.json`이 있어야 합니다(OpenAI 추출 경로, `--no-page-coverage` 미사용).

## Run

From the **repository root**:

```bash
cd tools/page_coverage_viewer
npm install
npm run dev
```

The browser opens (port **5175**). Use **JSON file** → choose `artifacts/stage2_instruction_extraction/page_coverage.json`.

- **Metric**: max confidence per page, instruction count, or binary covered.
- **Brush** (grey strip under the chart): drag handles to zoom along the page axis.

## Pipeline output (default)

Stage 2 (OpenAI path, without `--no-page-coverage`) also writes:

- `artifacts/stage2_instruction_extraction/page_coverage.json`
- `artifacts/stage2_instruction_extraction/page_coverage.png`

`--ground-truth-as-catalog` skips coverage files (no per-page `source_refs`).
