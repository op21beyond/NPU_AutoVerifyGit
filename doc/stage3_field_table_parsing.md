# Stage 3 - Field Table Parsing

## Plan
- 목표: 명령어별 필드 구성(필드명/비트/워드/위치)을 표 중심으로 복원
- 입력: `page_blocks`, `instruction_catalog` (선택 `--page-start` / `--page-end`: Stage1·Stage2와 동일한 1-based 포함 구간으로 로드한 `page_blocks`의 `page` 필터)
- 출력: `instruction_field_map@2` (`instruction_name`, **`variation`**(nullable, Stage2와 동일), `field_name`, `bit_range`, …)
- 완료 기준:
  - 이미지 표 셀 복원 로직 포함
  - 불완전 추출 항목 `uncertain` 표기

## Status
- 상태: Implemented (heuristic)
- 구현률: ~55%
- 구현: `field_tables.py` — `table` 블록에서 헤더(`Field`/`Bits` 등) 감지 후 행 파싱, 텍스트 블록은 느슨한 `FIELD 31:28` 패턴; instruction은 `source_refs` 페이지와 표 페이지 ±1 매칭(복수 시 `uncertain`)
- 오픈 이슈:
  - 이미지 표·OpenCV 셀 분할 미연동
  - 복잡 레이아웃에서 표-명령 1:1 매핑 한계
- 산출 메타: `parsing_summary.json` — `instruction_scope_coverage`, `field_cheat_sheet_path` / `field_cheat_sheet_warnings`(치트시트 사용 시), 적용 시 `page_range`·`page_blocks_path`
- **필드 치트시트**(선택): `--field-cheat-sheet PATH.json` — 키는 `instruction_scope_label`과 동일(`NAME` 또는 `NAME|VAR`). 값은 `{ "fields": [ { "field_name", "bit_range", "word_index" } ] }`. 해당 카탈로그 스코프에 대해 **휴리스틱 행을 치트시트 행으로 교체**. variation이 있는데 치트에 `NAME`만 있으면 폴백(경고). 예시: `ground_truth_examples/field_cheat_sheet.example.json`
- Ground truth 옵션:
  - `--ground-truth-as-output` + `--ground-truth`로 GT 기반 `instruction_field_map` 직접 생성
  - `--ground-truth`만 주면 추출 결과를 GT로 성능평가(`evaluation_report.json`)
  - 예시 파일: `ground_truth_examples/stage3_ground_truth.txt`
    - 평가: `python -m src.stage3_field_table_parsing.main --ground-truth ground_truth_examples/stage3_ground_truth.txt`
    - 정답 직접 출력: `python -m src.stage3_field_table_parsing.main --ground-truth-as-output --ground-truth ground_truth_examples/stage3_ground_truth.txt`
  - 텍스트 GT: `INSTR FIELD [BIT_RANGE]` 또는 variation 포함 시 `INSTR VAR FIELD BIT_RANGE`(네 토큰 이상이면 네 번째가 비트 범위). JSON/JSONL에는 `variation` 필드 사용
- 다음 액션:
  - OCR 표 구조와 행 매핑
  - 실 PDF로 열 인덱스·헤더 튜닝

## Technical Note
- 표 인식 실패는 필드 누락으로 직결되므로 재시도 전략 필요
- OCR 결과와 구조 인식을 분리해 로그 저장하면 디버깅이 쉬움
