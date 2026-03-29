# NPU Mission Definition

## 1) Mission Goal

Architecture PDF 문서에 정의된 모든 NPU 명령어를 분석하여, **허용 가능한 모든 필드 조합**을 단일 테이블로 정리한다.  
이 결과는 NPU 시뮬레이션 검증용 Test Case 생성에 사용하며, **Verilog 코드 생성은 범위에서 제외**한다.

## 2) Scope

- 포함:
  - 명령어 목록 추출
  - 명령어별 필드 구성 추출
  - 필드 데이터 타입, 허용값/범위, 제약조건 추출
  - 필드 간 의존성 제약 추출
  - 전체 unique 필드 집합 기반 단일 테스트 테이블 생성
- 제외:
  - RTL/Verilog 코드 생성
  - 하드웨어 동작 모델 구현

## 3) Input

- 주 입력:
  - 텍스트 기반 Architecture PDF (약 300페이지)
  - 표/수식/그림이 이미지로 삽입되어 있을 수 있음
  - Tagged PDF 여부 미확정
- 보조 입력(검증 옵션):
  - 명령어 필드 구성이 정리된 원본 엑셀
  - 원칙적으로 PDF 중심 처리, 엑셀은 교차검증 용도

## 4) Output

- 파일 형식:
  - CSV 또는 Excel
- 데이터 의미:
  - 한 행 = 하나의 Test Case
  - 열 = 전체 unique 필드 집합
  - 특정 명령어에서 사용되지 않는 필드 = Don't Care 값

## 5) Data Model Requirements

최종 테이블 및 중간 산출물은 아래 개체를 일관되게 표현해야 한다.

용어 정합성 원칙:
- `DataType`과 `ValueDomain`은 분리한다.
- `DataType`은 단순히 일반 프로그래밍 언어의 primitive만이 아니라, **해당 IP 아키텍처(TRM)에서 정의한 전용 타입**을 포함할 수 있다. 문서에서 등장하는 타입 명칭의 **전체 집합**을 먼저 수집하고(`datatype_registry`), 각 타입에 대해 의미·허용 범위·값 생성 방식을 정리한 뒤 필드와 연결한다.
- `ValueDomain`은 해당 타입 위에서의 **허용 값 집합/범위/생성 규칙의 필드별 인스턴스**(예: `0..15`, `{0,2,4}`, 특정 인코딩 하의 패턴)이다.
- 동일 `DataType`(같은 `type_id`)이라도 명령어/필드별 `ValueDomain`은 다를 수 있다.

- Instruction
  - `instruction_name`
  - `instruction_id` (있을 경우)
  - `opcode_raw`, `opcode_radix` (`hex` | `dec` | `unknown`), `opcode_value` (정규화 정수; 문서가 0x 또는 10진 등으로 표기 가능하므로 원문과 진법·값을 분리 저장)
  - `execution_unit` (명령이 수행되는 하드웨어 블록)
  - `execution_unit_id` (온톨로지 연결용 정규화 ID, 선택)
  - `instruction_kind` (`macro` | `micro` | `unknown` — 복합 vs 유닛 명령 구분)
  - `instruction_kind_confidence` (선택)
  - `ip_name`
  - `ip_type`
  - `ip_version`
  - `ip_additional_info`
  - `source_refs`
- Field
  - `field_name`
  - `bit_range` / `word_index` (있을 경우)
  - `data_type_raw` (표에 적힌 문자열, 선택)
  - `data_type_ref` (`datatype_registry.type_id` 참조 — primitive 또는 IP 전용 타입)
  - `allowed_value_form` (enum/range/bitmask/formula 등)
  - `allowed_values_or_range`
  - `default_or_dc`
  - `source_refs`
- DataTypeRegistry (`datatype_registry`)
  - `type_id`, `type_name_raw`, `category` (`software_primitive` | `ip_architecture` | `alias` | `unknown`)
  - `value_constraint_summary`, `value_generation_method` (아키텍처에서 정의한 범위·값 생성 규칙)
  - `source_refs`
- Constraint
  - `constraint_type` (문맥 기반 수집 후 온톨로지 분류)
  - `constraint_type_level1` (예: range/enum/conditional/dependency)
  - `constraint_type_level2` (예: mutual-exclusion/implication/reserved-value)
  - `expression` (기계 처리 가능한 표현)
  - `human_readable_rule`
  - `applies_to` (instruction/field/field-set)
  - `classification_rationale`
  - `source_refs`
- Metadata
  - `document_id`
  - `page_number`
  - `block_id`
  - `bbox`
  - `extraction_method`
  - `confidence_score`
  - `parser_version`
  - `timestamp`
- TestCaseRow
  - `instruction_name`
  - `all_unique_fields...`
  - `constraint_satisfaction_status`
  - `trace_id`

## 6) Key Characteristics and Challenges

- 명령어 필드는 문서 내 표(이미지 포함)와 비트/워드 표기 기반으로 제시됨
- 특정 필드값에 따라 다른 필드 구성이 달라지는 조건부 구조가 존재함
- 제약 설명이 문서 여러 위치에 분산되어 있고 고정 문단 패턴이 없음
- 일부 정보는 OCR/레이아웃 인식 실패 가능성이 존재함

## 7) Functional Requirements

1. 모든 NPU 명령어 리스트를 추출한다.
2. 모든 필드를 추출하고 unique 필드 이름 집합을 생성한다.
3. 명령어별 필드 구성(포함/미포함, 비트 위치, 타입)을 정리한다.
4. 필드별 허용값과 범위를 정규화한다.
5. 명령어별/필드별/필드 조합 제약을 추출한다.
6. 의존성 제약(예: `A=value`일 때 `B` 유효범위 변경)을 표현한다.
7. 가능한 조합을 생성하되, 제약 위반 조합은 제외하거나 별도 표식한다.
8. 누락/불확실/판독불가 항목을 추적 가능하게 기록한다.
9. 제약사항의 "종류"를 문맥에서 동적으로 수집하고, 제약 온톨로지로 분류한다.
10. 각 필드/명령어별로 적용되는 제약 종류 분포를 조회 가능하게 저장한다.
11. 온톨로지는 제약뿐 아니라 명령어/필드/데이터타입/값 도메인/메타정보를 포함한 총체 구조를 저장한다.
12. IP 식별 정보(`ip_name`, `ip_type`, `ip_version`, `ip_additional_info`)를 온톨로지와 산출 메타에 포함한다.
13. 각 명령어에 대해 실행 유닛(`execution_unit`)과 macro/micro 구분(`instruction_kind`)을 추출·저장한다(불명확 시 `unknown`).
14. 각 명령어의 고유 식별 OPCODE를 추출한다. 표기는 `0x`로 시작하는 16진수일 수도 있고 10진수일 수도 있으므로 `opcode_raw`·`opcode_radix`·`opcode_value`(정규화)로 구분·저장한다.
15. 문서에서 데이터 타입 **전체 집합**을 수집하고(`datatype_registry`), 각 타입의 값 범위·값 생성 방법을 파악한 뒤, 명령어 필드의 `data_type_ref`로 레지스트리와 연결한다.

## 8) Accuracy and Traceability Requirements

- 정확성 우선 원칙:
  - 추출량보다 정확한 의미 보존이 우선
- 근거 추적:
  - 모든 핵심 항목은 `source_refs`를 가져야 함
  - 최소 메타정보: 문서명, 페이지 번호, 블록 위치, 추출 방식(OCR/텍스트/표 인식), 신뢰도
- 제약 분류 추적:
  - 각 제약은 분류 근거(`classification_rationale`)와 분류 신뢰도 보유
  - 온톨로지 미매핑 제약은 `unclassified_constraint` 상태로 별도 관리
- 누락 가시화:
  - 미추출/불확실 항목을 별도 상태로 관리
  - 사람이 재검토할 수 있도록 원문 근거 링크 유지

## 9) Success Criteria

아래 조건을 만족하면 미션 완료로 본다.

- 단일 출력 테이블(CSV/Excel)에 모든 명령어 기반 Test Case가 구성됨
- 전체 unique 필드 집합이 컬럼으로 반영됨
- Don't Care 처리 규칙이 일관적으로 적용됨
- 주요 제약(필드 단독/필드 간/명령어별)이 명시적으로 반영됨
- 각 명령어/필드별 제약 종류가 온톨로지 레벨로 구분 가능함
- 각 항목의 근거 메타정보가 존재하여 사람이 검증 가능함
- 미추출/불확실 항목 목록이 별도 식별 가능함
- `datatype_registry`에 문서에서 식별 가능한 타입이 집계되고, 필드의 `data_type_ref`와 연결됨

