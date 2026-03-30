# Stage 2 - Instruction Extraction

## Plan
- 목표: 문서 전반에서 NPU 명령어 후보를 추출하고 정규화된 명령어 카탈로그 생성
- 입력: `page_blocks`
- 출력: `instruction_catalog` (instruction_name, aliases, **OPCODE**: `opcode_raw`, `opcode_radix` hex|dec|unknown, `opcode_value`; `execution_unit`, `instruction_kind` macro|micro|unknown; 선택: execution_unit_id, instruction_kind_confidence; source_refs, confidence, trace_id)
- 완료 기준:
  - 중복/동의어 통합 규칙 정의
  - 미확정 명령어 목록 별도 관리

## Status
- 상태: Implemented (rule-based)
- 구현률: ~70%
- 구현: `src/stage2_instruction_extraction/extract.py` — 본문/표 텍스트에서 `NAME (0x..)`, `0x..—NAME`, `NAME=0x..`, 표 두 열 패턴 + `parse_opcode_token`; 동일 이름 병합
- 선택: `--extractor openai` — OpenAI Chat Completions(JSON object) 기반 추출(`llm_openai.py`). 환경변수 `OPENAI_API_KEY`, 선택 `OPENAI_BASE_URL` 대신 `--openai-base-url`로 OpenAI 호환 엔드포인트 지정 가능. `--openai-model`(기본 `gpt-4o-mini`)
- 평가: `--ground-truth PATH` — 정답 instruction 목록 파일. 추출 후 `artifacts/stage2_instruction_extraction/evaluation_report.json`에 precision/recall/F1·FP/FN 목록·(선택) opcode_value 일치 수 기록. 형식: `.txt`는 한 줄에 하나( `#` 주석 가능), `.json`은 `["A","B"]` 또는 `[{"instruction_name":"CONV","opcode_value":42}]`, `.jsonl`은 객체/문자열 한 줄씩
- 보강 입력: `--supplemental-text-corpus PATH` — Stage1 `pymupdf4llm_corpus.json`을 읽어 pseudo block으로 합쳐 regex 추출 recall을 보강. 미지정 시 기본 경로(`artifacts/stage1_ingestion/pymupdf4llm_corpus.json`) 자동 탐지(해제: `--disable-default-supplemental-text`)
- 정답 직접 출력: `--ground-truth-as-catalog` + `--ground-truth PATH` — regex/LLM 추출을 건너뛰고 정답 파일만으로 `instruction_catalog.jsonl` 생성(JSON 객체에 `opcode_raw`/`opcode_value`, 선택 `execution_unit`/`instruction_kind`/`aliases` 지원). 이 모드에서는 `--ground-truth` 성능 평가 리포트를 생략(출력이 정답과 동일)
- 오픈 이슈:
  - LLM low-confidence 보정 게이트 미구현
  - execution_unit은 히트 주변 스니펫 기준이라 같은 블록 원문 전체 맥락 미반영 가능
- 다음 액션:
  - 실제 TRM에 맞게 패턴·제외 사전 튜닝
  - 신뢰도 임계치와 LLM 보정 진입 조건

## Technical Note
- regex/사전 기반 검출과 tool-call 기반 문맥 검증을 결합
- `source_refs` 없이는 확정 엔티티로 승급하지 않음
- LLM API는 규칙 기반 추출의 low-confidence 케이스에만 제한 사용
- `execution_unit`: 명령이 매핑되는 하드웨어 실행 블록(문서 챕터/표/용어에서 추출)
- `instruction_kind`: macro(복합)·micro(유닛)·unknown — 문서에 명시 없으면 `unknown` + 신뢰도 기록
- **OPCODE**: 문서 원문 `opcode_raw` 보존; `0x`/16진 문맥이면 `opcode_radix=hex`, 순수 10진 표기면 `dec`; `opcode_value`는 항상 동일 명령에 대해 같은 정수로 정규화(파싱 규칙 단위 테스트 권장). 참고 구현 스켈레톤: `src/common/opcode.py`
