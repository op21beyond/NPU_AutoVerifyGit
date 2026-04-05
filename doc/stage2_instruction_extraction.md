# Stage 2 - Instruction Extraction

## Plan
- 목표: 문서 전반에서 NPU 명령어 후보를 추출하고 정규화된 명령어 카탈로그 생성
- 입력: `page_blocks` (선택 `--page-start` / `--page-end`: Stage1과 동일한 페이지 범위 의미로 `page` 필터)
- 출력: `instruction_catalog` (`instruction_catalog@2`): **instruction_name** (논리적 한 가족), **variation** (`null` 또는 짧은 구분자, 예: 동일 opcode·다른 필드 레이아웃인 `RESCALE_CW`/`RESCALE_GW` → `instruction_name=RESCALE`, `variation=CW|GW`), **aliases** (가족 공통 + variation별 표면 니모닉), **OPCODE**: `opcode_raw`, `opcode_radix`, `opcode_value`; `execution_unit`, `instruction_kind`; source_refs, confidence, trace_id).
- 완료 기준:
  - 중복/동의어 통합 규칙 정의
  - 미확정 명령어 목록 별도 관리

## Status
- 상태: Implemented (OpenAI 기본)
- 구현률: ~70%
- 구현: 기본 경로는 `llm_openai.py` — OpenAI Chat Completions(JSON object)로 추출. 환경변수 `OPENAI_API_KEY`, 선택 `OPENAI_BASE_URL` 대신 `--openai-base-url`로 OpenAI 호환 엔드포인트 지정 가능. `--openai-model`(기본 `gpt-4o-mini`)
- 평가: `--ground-truth PATH` — 정답 목록. **매칭 키는 `(instruction_name, variation)`** (정답에 `variation` 없으면 `null`과만 일치). 추출 후 `evaluation_report.json`에 precision/recall/F1·FP/FN(각 항목에 `instruction_name`+`variation`)·(선택) opcode_value 일치. 형식: `.txt`는 한 줄에 하나, `.json`/`.jsonl` 객체에 선택 필드 `"variation": "CW"` 등 가능.
- 보강 입력: `--supplemental-text-corpus PATH` — Stage1 `pymupdf4llm_corpus.json`을 읽어 pseudo block으로 합쳐 LLM 입력 recall을 보강. 미지정 시 기본 경로(`artifacts/stage1_ingestion/pymupdf4llm_corpus.json`) 자동 탐지(해제: `--disable-default-supplemental-text`)
- 정답 직접 출력: `--ground-truth-as-catalog` + `--ground-truth PATH` — OpenAI 추출을 건너뛰고 정답 파일만으로 `instruction_catalog.jsonl` 생성(JSON 객체에 `opcode_raw`/`opcode_value`, 선택 `execution_unit`/`instruction_kind`/`aliases` 지원). 이 모드에서는 `--ground-truth` 성능 평가 리포트를 생략(출력이 정답과 동일)
- 페이지 커버리지(OpenAI 경로 기본): `page_coverage.json` + `page_coverage.png` — 카탈로그 `source_refs.page` 기준으로 구간 전체(한 히트맵) 집계. 비활성: `--no-page-coverage`. 인터랙티브 확인: `tools/page_coverage_viewer`(JSON 로드·브러시 줌).
- 예시 파일: `ground_truth_examples/stage2_ground_truth.txt`
  - 평가: `python -m src.stage2_instruction_extraction.main --ground-truth ground_truth_examples/stage2_ground_truth.txt`
  - 정답 직접 출력: `python -m src.stage2_instruction_extraction.main --ground-truth-as-catalog --ground-truth ground_truth_examples/stage2_ground_truth.txt`
- 오픈 이슈:
  - LLM low-confidence 보정 게이트 미구현
  - execution_unit은 히트 주변 스니펫 기준이라 같은 블록 원문 전체 맥락 미반영 가능
- 다음 액션:
  - 실제 TRM에 맞게 시스템/유저 프롬프트·출력 스키마 검증
  - 신뢰도 임계치·후처리(선택) 게이트

## Technical Note
- **의존성(파이프라인)**: `openai`(API 키 `OPENAI_API_KEY`); 페이지 커버리지 PNG 기본 출력에는 `matplotlib`(`pip install -r requirements.txt`). **인터랙티브 뷰어** `tools/page_coverage_viewer`는 **Node.js + npm**(저장소에 `package.json` 포함).
- 기본은 **OpenAI Chat Completions(JSON object)** 한 번에 카탈로그 생성; 대안은 **`--ground-truth-as-catalog`** 로 정답 파일만으로 출력
- `source_refs` 없이는 확정 엔티티로 승급하지 않음
- (선택 과제) 규칙/휴리스틱 보조나 2단계 LLM 보정은 미구현 — 현재는 단일 LLM 경로가 기본
- `execution_unit`: 명령이 매핑되는 하드웨어 실행 블록(문서 챕터/표/용어에서 추출)
- `instruction_kind`: macro(복합)·micro(유닛)·unknown — 문서에 명시 없으면 `unknown` + 신뢰도 기록
- **OPCODE**: 문서 원문 `opcode_raw` 보존; `0x`/16진 문맥이면 `opcode_radix=hex`, 순수 10진 표기면 `dec`; `opcode_value`는 항상 동일 명령에 대해 같은 정수로 정규화(파싱 규칙 단위 테스트 권장). 참고 구현 스켈레톤: `src/common/opcode.py`
