# 변경 이력

## 2026-04-06

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

- Stage2 기본 추출: OpenAI(LLM), `--ground-truth-as-catalog`만 대안; regex 경로 제거.
- Stage1·Stage2: `--page-start` / `--page-end` 동일 의미(미지정=전체, 단일 인자=한쪽 끝까지).
- Stage2: `page_coverage.json` / `page_coverage.png` 기본 출력(`matplotlib`), `--no-page-coverage`로 끔.
- `tools/page_coverage_viewer`: `page_coverage.json` 인터랙티브 차트(Vite/React, Brush 줌).
- `integration_pipeline`: 페이지 인자 전달.
- README·`tools/README`·Stage 문서에 의존성(Node/npm, matplotlib) 및 사용법 보강.

## 2026-04-01

- `src/common/page_range.py`: 페이지 범위 해석·블록 필터 유틸.
