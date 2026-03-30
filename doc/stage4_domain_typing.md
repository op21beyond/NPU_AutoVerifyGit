# Stage 4 - DataType and ValueDomain Typing

## Plan
- 목표: 문서에서 **데이터 타입 전체 집합**을 수집하고(`datatype_registry`), 각 타입의 값 범위·값 생성 규칙을 정리한 뒤 필드와 **`data_type_ref`로 연결**
- 입력: `instruction_field_map`, `global_field_schema`(Step 3b), `page_blocks`
- 출력:
  - `datatype_registry` (primitive + **IP 아키텍처 전용 타입**)
  - `field_datatype_catalog` (`data_type_raw`, **`data_type_ref`** → `type_id`)
  - `field_domain_catalog`
- 완료 기준:
  - 타입 레지스트리와 필드 매핑 일관성 (`data_type_ref`가 레지스트리에 존재)
  - DataType/ValueDomain 분리 저장
  - 범위/열거/마스크/공식 표현 정규화

## Status
- 상태: Implemented (휴리스틱: `instruction_field_map`의 `bit_range` 폭으로 `uintN` 타입·도메인 추론)
- 구현률: ~55%
- Ground truth 옵션:
  - `--ground-truth-as-output` + `--ground-truth PATH` — GT JSON에서 `datatype_registry` / `field_datatype_catalog` / `field_domain_catalog` 배열을 읽어 산출물 직접 기록
  - `--ground-truth`만 — 추출 결과와 GT를 비교해 `evaluation_report.json` (섹션별 type_id / 필드·타입 키 / 도메인 키)
- 오픈 이슈:
  - TRM 본문에서 타입 정의·값 생성 규칙 자동 추출 미구현
  - 동일 타입 명칭의 동의어·별칭 병합 규칙 미정
- 다음 액션:
  - 타입 정의가 모이는 섹션(용어집, 데이터형 장) 탐지 및 엔티티 추출
  - `data_type_ref` 검증기(레지스트리 lookup)

## Technical Note
- `DataType`은 형식, `ValueDomain`은 허용값 집합이라는 의미를 엄격히 분리
- IP 전용 타입은 일반 SW 타입과 동일한 파이프라인으로 다루되 `category=ip_architecture`로 구분
- 정규화 실패 케이스는 원문과 함께 보존해 재분류 가능하도록 관리
- 스키마: `data_contracts/datatype_registry.schema.json`, `data_contracts/field_datatype_catalog.schema.json`
