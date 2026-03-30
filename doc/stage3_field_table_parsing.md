# Stage 3 - Field Table Parsing

## Plan
- 목표: 명령어별 필드 구성(필드명/비트/워드/위치)을 표 중심으로 복원
- 입력: `page_blocks`, `instruction_catalog`
- 출력: `instruction_field_map` (instruction, field_name, bit_range, word_index, source_refs, confidence)
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
- Ground truth 옵션:
  - `--ground-truth-as-output` + `--ground-truth`로 GT 기반 `instruction_field_map` 직접 생성
  - `--ground-truth`만 주면 추출 결과를 GT로 성능평가(`evaluation_report.json`)
- 다음 액션:
  - OCR 표 구조와 행 매핑
  - 실 PDF로 열 인덱스·헤더 튜닝

## Technical Note
- 표 인식 실패는 필드 누락으로 직결되므로 재시도 전략 필요
- OCR 결과와 구조 인식을 분리해 로그 저장하면 디버깅이 쉬움
