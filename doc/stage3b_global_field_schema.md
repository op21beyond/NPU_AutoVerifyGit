# Stage 3b - Global Field Schema and Aliases

## Plan
- 목표: Step 3에서 얻은 `instruction_field_map`으로 **전역 unique 필드 이름 집합**을 확정하고, **별칭(alias)** 맵 스켈레톤을 둔다(제약·타입 문장에서 필드명 정규화에 사용).
- 입력: `instruction_field_map`
- 출력:
  - `global_field_schema.json` (`canonical_field_names`, 명령어별 필드 요약 선택)
  - `field_alias_map.jsonl` (alias → canonical)
- 완료 기준:
  - `canonical_field_names`가 Step 4·5에서 참조 가능
  - 타입이 필드 표에 없을 수 있으므로, 본 단계는 **이름·비트 위치** 중심으로만 고정

## Status
- 상태: Implemented
- 구현률: ~60%
- 구현: `instruction_field_map`에서 전역 `canonical_field_names`(공백→`_` 정규화), `field_count_per_instruction`, 빈 `field_alias_map.jsonl`
- 오픈 이슈:
  - 동의어·표기 차이 병합·`rapidfuzz` alias 후보 미구현
  - OCR 오타 교정 미구현
- 다음 액션:
  - 용어집 블록과 필드명 매칭
  - Step 4와 필드 문자열 정렬 규칙 통일

## Technical Note
- Step 4(타입/도메인)·Step 5(제약)은 **같은 필드를 가리키는 문자열**을 `canonical_field_names`에 맞추는 것이 안전함
- 필드 구성 표는 비트/워드·이름만 있을 수 있어, 타입은 Step 4에서 **다른 근거**로 채움
