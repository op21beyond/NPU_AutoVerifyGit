# Stage Document Governance

## Folder Structure

- `src/stage1_ingestion`
- `src/stage2_instruction_extraction`
- `src/stage3_field_table_parsing`
- `src/stage3b_global_field_schema`
- `src/stage4_domain_typing`
- `src/stage4b_field_datatype_catalog`
- `src/stage4c_field_domain_catalog`
- `src/stage5_constraint_ontology`
- `src/stage6_combination_generation`
- `src/stage7_validation_reporting`
- `src/integration_pipeline`
- `src/common` (공통: `rag_index_faiss.py`, `rag_resolve.py`, `rag_cli.py` 등 RAG 보조)
- `experiments/`
- `data_contracts/`

## 선택 산출물 (RAG / 그래프 DB)

- Stage1: `artifacts/stage1_ingestion/rag_index/` — FAISS + 메타데이터(`--build-rag-index`, `OPENAI_API_KEY`).
- Stage5: `artifacts/stage5_constraint_ontology/mission_graph_kuzu/graph.kuzu` — Kuzu 임베디드 그래프 DB(기본 내보내기; `--skip-kuzu-graph-db`로 생략).

## Interface Rules

- 각 단계는 `input_schema_version` / `output_schema_version`을 명시한다.
- 최소 공통 메타 필드:
  - `trace_id`
  - `source_refs`
  - `confidence_score`
  - `stage_name`
  - `stage_run_id`
- 실행 파라미터/모델 버전/프롬프트 버전을 기록한다.
- provider abstraction으로 API 교체 가능 구조를 유지한다 (`base_url`, `api_key`, `model` 분리).

## OSS and LLM Usage Rules

- 오픈소스 라이브러리/모델/도구를 기본 선택으로 사용한다.
- 상용 서비스·유료 클라우드 전용 서비스·상용 유료 API는 **사용하지 않는다**.
- 사내 LLM API 호출은 최소화하고, 반드시 필요할 때만 사용한다.
  - 허용: 비정형 제약 문장 정규화, 애매한 분류 보정, 충돌 규칙 설명
  - 비허용: 단순 추출/정규화/필터링(룰 기반으로 처리 가능)
- 모든 LLM 호출은 아래를 기록한다.
  - 호출 목적, 입력 근거, 토큰 사용량, 결과 신뢰도, 재현용 파라미터

## Document Rules

- 각 단계 문서는 다음 3개 섹션을 유지한다.
  - `Plan`
  - `Status`
  - `Technical Note`
- 상태 문서는 아래 항목을 항상 포함한다.
  - 구현률
  - 검증 결과
  - 오픈 이슈
  - 다음 액션
- 통합 문서는 `integration_pipeline.md`에서 동일 규칙을 따른다.
