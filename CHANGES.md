# 변경 이력

## 2026-04-02

- Stage5: [LightRAG](https://github.com/hkuds/lightrag)(`lightrag-hku`) 선택 경로 `--use-lightrag` + `src/common/lightrag_resolve.py` / `lightrag_cli.py`; FAISS `--use-rag`와 동시 사용 불가. `requirements.txt`에 `lightrag-hku`. 통합 파이프라인에 `--use-lightrag` 등 Stage5 전용 인자.
- Stage5 `field_domain_catalog` → `constraint_registry`: `enum`은 `IN`, `range`는 `lo <= FIELD <= hi`(빈 도메인은 placeholder); `domain_constraint_meta`; `constraint_pruning_index.json` + `stage5_report` 경로; Stage6 `combination_context.json`이 프루닝 인덱스 스냅샷 로드.
- 테스트: `tests/test_stage5_domain_constraints.py`, (선택) `OPENAI_API_KEY` 시 `tests/test_stage5_llm_constraints_optional.py`.
- 문서: `doc/stage5_constraint_ontology.md`, `doc/stage6_combination_generation.md` 갱신.
- `tools/ontology_graph_viewer`: Streamlit + Pyvis로 `mission_ontology_graph.json` 시각화(앱 내 사용 방법·범례); `tools/requirements-tools.txt`에 `pyvis`.
- Stage1 `--build-rag-index`: FAISS(`faiss-cpu`) + OpenAI 임베딩, `rag_index/`에 메타데이터·페이지 계층(`rag_manifest.json`).
- 공통 `src/common/rag_index_faiss.py`, `rag_resolve.py`, `rag_cli.py`; Stage2·4·4b·4c·5 `--use-rag` 옵션 경로(LLM 전 블록 축소).
- Stage5: Kuzu 임베디드 그래프 DB `mission_graph_kuzu/graph.kuzu`; `--skip-kuzu-graph-db`.
- `tools/rag_graph_chatbot/app.py`: FAISS+Kuzu+OpenAI Streamlit 챗(경로/멀티턴 session state).
- `requirements.txt`: numpy, faiss-cpu, kuzu; `integration_pipeline`에 `--build-rag-index` / `--use-rag` 전달.
- 문서: `doc/rag_integration_checklist.md`(구현 요약·`ontology_graph_viewer`·로드맵 구분·`--use-rag` 표기), `tools/README.md`에 rag_graph_chatbot.
- 문서: `doc/stage2_instruction_extraction.md`, `doc/stage4_domain_typing.md`, `doc/stage4b_field_datatype_catalog.md`, `doc/stage4c_field_domain_catalog.md`, `doc/stage_document_governance.md`, `README.md`에 RAG/Kuzu 반영.

## 2026-04-06

- Stage4: 휴리스틱 제거 → OpenAI로 `datatype_registry`만 생성; `--page-start`/`--page-end`; `extraction_summary.json`.
- Stage4b `stage4b_field_datatype_catalog`: OpenAI로 `field_datatype_catalog`; Stage4c `stage4c_field_domain_catalog`: OpenAI로 `field_domain_catalog`; 각 GT 예제 `ground_truth_examples/stage4*_ground_truth.txt`.
- Stage5: 입력 아티팩트를 Stage4/4b/4c 산출 경로로 분리.
- Stage5: `page_blocks` + OpenAI로 제약 후보 추출(`constraint_candidates.json`)·카테고리 정규화(`constraint_type_catalog.json`)·온톨로지 값 바인딩(`ontology_value_bindings.json`); `stage5_report.json`; `--skip-llm-constraints` / `--skip-llm-values`; 통합 파이프라인에 Stage5 페이지 인자.
- Stage5: 카테고리 정규화 2차 LLM 프롬프트 강화(`merge_rationale`); Stage4c `allowed_value_form` 라벨을 정규화 배치에 포함.
- 공통: `src/common/llm_page_blocks.py`, `openai_json.py`; Stage2 `llm_openai`가 직렬화 공유.
- 문서: `README.md`, `doc/integration_pipeline.md`, `doc/stage3_field_table_parsing.md`에 Stage3 페이지 범위·`parsing_summary`(`instruction_scope_coverage` 등) 반영.
- Stage3: `--page-start` / `--page-end`로 `page_blocks` 필터(Stage2·`page_range`와 동일 의미); `parsing_summary`에 `page_range`·`page_blocks_path` 기록; `integration_pipeline`이 Stage3에 페이지 인자 전달.
- Stage3: `--field-cheat-sheet` JSON으로 스코프별 필드 오버라이드(`field_cheat_sheet.py`), `field_cheat_sheet.example.json`; `integration_pipeline`이 동일 인자를 Stage3에 전달.
- `.cursor/rules/plan_and_doc_sync_rule.md`: `CHANGES.md` 갱신 의무·형식(날짜별 한 줄)·체크리스트 반영.

## 2026-04-05

- Stage3 `instruction_field_map@2`: `variation` 필드 추가, 카탈로그·페이지 매칭 반영.
- Stage3 GT: 텍스트/`variation` JSON 지원, 평가 키에 variation 포함.
- Stage3b `field_count_per_instruction` 키를 `NAME` 또는 `NAME|VAR` 형식으로 집계.
- Stage4 `field_datatype_catalog`에 `variation` 반영, GT `DTYPE` 5토큰(variation) 지원.
- Stage5 온톨로지: Instruction 노드 id `Instr:{opcode}_{VAR}`, `HAS_FIELD`를 `(instruction_name, variation)` 기준으로 연결.
- Stage6 플레이스홀더 행에 `variation: null` 추가.
- `src/common/instruction_key.py` 도입, Stage2 GT/LLM이 동일 키 규칙 사용.
- `data_contracts`: `variation` 및 `instruction_field_map.schema.json` 보강.
- `ground_truth_examples` Stage3~5 예시에 variation·`stage3b_ground_truth.json` 반영.
- 관련 `doc/stage3`~`stage5` 문서 갱신.

## 2026-04-02

- Stage3 `parsing_summary.json`: `instruction_scope_coverage` (카탈로그 스코프 대비 완전·부재·불확실, `per_scope_status`, 출력 전용 스코프 `extra_scopes_in_output`).
- Stage2 기본 추출: OpenAI(LLM), `--ground-truth-as-catalog`만 대안; regex 경로 제거.
- Stage1·Stage2: `--page-start` / `--page-end` 동일 의미(미지정=전체, 단일 인자=한쪽 끝까지).
- Stage2: `page_coverage.json` / `page_coverage.png` 기본 출력(`matplotlib`), `--no-page-coverage`로 끔.
- `tools/page_coverage_viewer`: `page_coverage.json` 인터랙티브 차트(Vite/React, Brush 줌).
- `integration_pipeline`: 페이지 인자 전달.
- README·`tools/README`·Stage 문서에 의존성(Node/npm, matplotlib) 및 사용법 보강.

## 2026-04-01

- `src/common/page_range.py`: 페이지 범위 해석·블록 필터 유틸.
