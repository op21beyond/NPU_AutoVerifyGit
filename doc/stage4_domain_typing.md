# Stage 4 - DataType Registry (LLM)

## Plan
- 목표: 문서 `page_blocks`에서 **데이터 타입 정의**를 수집해 **`datatype_registry`** 한 벌을 만든다 (Stage2 명령 추출과 동일하게 페이지 정렬·직렬화 후 OpenAI JSON 응답).
- 입력: `page_blocks` (선택 `--page-start` / `--page-end`)
- 출력: `artifacts/stage4_domain_typing/datatype_registry.jsonl`, `extraction_summary.json`
- **필드–타입 매핑**은 **Stage4b**, **값 도메인**은 **Stage4c**에서 별도 실행.

## Status
- 구현: `llm_datatype_registry.py` — OpenAI Chat Completions `response_format=json_object`, `OPENAI_API_KEY` 필요.
- Ground truth: `--ground-truth-as-output` + `ground_truth_examples/stage4_datatype_registry_ground_truth.txt` (TYPE 라인만) 또는 JSON의 `datatype_registry` 배열.
- 평가: `--ground-truth` — 동일 포맷에서 **datatype_registry 섹션만** 지표화.

## CLI
```bash
python -m src.stage4_domain_typing.main
python -m src.stage4_domain_typing.main --page-start 1 --page-end 20 --openai-model gpt-4o-mini
python -m src.stage4_domain_typing.main --ground-truth-as-output --ground-truth ground_truth_examples/stage4_datatype_registry_ground_truth.txt
```

## Technical Note
- 이전 휴리스틱(`bit_range` → `uintN`) 경로는 제거되었다.
- 통합 파이프라인에서 Stage4 → **Stage4b** → **Stage4c** → Stage5 순으로 실행한다.
- 선택 **RAG**: `--use-rag` 등 — Stage1 FAISS 인덱스로 LLM 입력 `page_blocks` 축소; `extraction_summary.json`의 `rag`. [`doc/rag_integration_checklist.md`](rag_integration_checklist.md).
