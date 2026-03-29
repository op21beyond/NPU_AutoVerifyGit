# Stage 6 - Combination Generation

## Plan
- 목표: 명령어별 필드 조합 공간을 만들고 제약 기반 프루닝으로 유효 조합만 생성
- 입력: **`global_field_schema`(Step 3b)**, `constraint_registry`, `field_domain_catalog` 등 (Step 6은 **조합 생성만**; 전역 필드 집합은 Step 3b에서 확정)
- 출력: `test_case_matrix` (instruction_name + all_unique_fields + constraint_satisfaction_status + trace_id)
- 완료 기준:
  - 미사용 필드 Don't Care 일관 적용
  - 제약 위반 조합 배제/표식 정책 적용

## Status
- 상태: Scaffolded
- 구현률: 20%
- 오픈 이슈:
  - 제약 전파 기반 프루닝 미구현
  - 조건부 필드 활성화 규칙 미구현
- 다음 액션:
  - global field schema 기반 행 생성 구현
  - 제약 만족 판정 엔진 연결

## Technical Note
- 완전탐색 대신 제약 전파/프루닝 기반 생성이 현실적
- 생성 결과에 항상 제약 만족 상태를 기록해 감사 가능성 확보
