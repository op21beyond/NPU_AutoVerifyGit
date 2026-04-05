# Stage 4b - Field ↔ DataType Catalog (LLM)

## Plan
- 목표: Stage3 `instruction_field_map`의 각 필드에 **Stage4 `datatype_registry`의 `type_id`**를 연결한 **`field_datatype_catalog`** 생성.
- 입력: `page_blocks`, `instruction_field_map.jsonl`, `datatype_registry.jsonl` (선택 페이지 범위).
- 출력: `artifacts/stage4b_field_datatype_catalog/field_datatype_catalog.jsonl`

## Status
- 구현: `llm_field_datatype.py` — 허용 `type_id` 목록과 필드 목록( `INSTRUCTION|VAR|FIELD` ) + 문서 발췌를 LLM에 전달.
- 선택 **RAG**: `--use-rag` 등 — Stage1 FAISS로 `page_blocks` 축소 후 LLM; `extraction_summary.json`의 `rag`. [`doc/rag_integration_checklist.md`](rag_integration_checklist.md).

## CLI
```bash
python -m src.stage4b_field_datatype_catalog.main
python -m src.stage4b_field_datatype_catalog.main --ground-truth-as-output --ground-truth ground_truth_examples/stage4b_field_datatype_ground_truth.txt
```

## Ground truth
- 예시: `ground_truth_examples/stage4b_field_datatype_ground_truth.txt` (`DTYPE|...` 라인).
- 평가 시 GT 파일의 **field_datatype_catalog** 섹션만 사용한다.
