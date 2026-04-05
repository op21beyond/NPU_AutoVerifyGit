# Stage 4c - Field Value Domain Catalog (LLM)

## Plan
- 목표: 각 필드의 **허용 값 형태·범위**를 `field_domain_catalog`로 수집.
- 입력: `page_blocks`, `instruction_field_map.jsonl` (선택 페이지 범위).
- 출력: `artifacts/stage4c_field_domain_catalog/field_domain_catalog.jsonl`

## Status
- 구현: `llm_field_domain.py` — 필드 목록 + 문서 발췌를 LLM에 전달.
- 선택 **RAG**: `--use-rag` 등 — Stage1 FAISS로 `page_blocks` 축소; `extraction_summary.json`의 `rag`. [`doc/rag_integration_checklist.md`](rag_integration_checklist.md).

## CLI
```bash
python -m src.stage4c_field_domain_catalog.main
python -m src.stage4c_field_domain_catalog.main --ground-truth-as-output --ground-truth ground_truth_examples/stage4c_field_domain_ground_truth.txt
```

## Ground truth
- 예시: `ground_truth_examples/stage4c_field_domain_ground_truth.txt` (`DOMAIN|...` 라인).
