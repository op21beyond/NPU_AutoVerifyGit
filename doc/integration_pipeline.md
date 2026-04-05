# Integration Pipeline

## Plan
- 목표: 단계별 모듈을 연결한 end-to-end 파이프라인 운영
- 입력: Architecture PDF
- 출력: 최종 Test Case 테이블 + 메타정보/감사 패키지
- 완료 기준:
  - 단계 간 `data_contracts` 준수
  - 재실행 시 동일 입력에서 재현 가능한 결과 확보

## Status
- 상태: Scaffolded
- 통합도: 30%
- 오픈 이슈:
  - 스테이지 간 스키마 검증 훅 미연동
  - 단계 실패 시 재시도/복구 전략 미구현
- 다음 액션:
  - 각 stage 실행 전후 contract validation 추가
  - 통합 smoke test와 샘플 PDF 실행 스크립트 정리

## Technical Note
- 통합 계층은 orchestration, state tracking, retry, lineage 기록을 담당
- 단계별 실험 결과를 비교해 승자 전략을 통합 계층으로 승격
- 실행 순서: `stage1` → `stage2` → `stage3` → **`stage3b`(전역 필드·별칭)** → **`stage4`(datatype_registry)** → **`stage4b`(field_datatype_catalog)** → **`stage4c`(field_domain_catalog)** → `stage5` → `stage6`(조합만) → `stage7`
- Stage 1 인제스트 옵션(표 bbox 병합, 첨자 태깅, `parsing_report` 필드)은 [`doc/stage1_ingestion.md`](stage1_ingestion.md)를 기준으로 한다.
- 선택 인자 `--page-start` / `--page-end`(1-based)는 **Stage 1·2·3·4·4b·4c**에 동일하게 전달된다(의미: [`doc/stage1_ingestion.md`](stage1_ingestion.md); `page_blocks`의 `page` 필터).
- 선택 인자 `--field-cheat-sheet PATH`는 **Stage3**에만 전달된다([`doc/stage3_field_table_parsing.md`](stage3_field_table_parsing.md): 카탈로그 스코프별 필드 행 오버라이드).
- `--build-rag-index`는 **Stage1**에 전달되어 FAISS `rag_index/`를 생성한다(`OPENAI_API_KEY` 필요).
- `--use-rag`와 선택적 `--rag-index-dir` / `--rag-top-k` / `--rag-embedding-model`은 **Stage2·4·4b·4c·5**에 전달되어 LLM 전에 블록을 축소한다.
- 자세한 형식·산출물은 [`doc/rag_integration_checklist.md`](rag_integration_checklist.md)를 참고한다.
