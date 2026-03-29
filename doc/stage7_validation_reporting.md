# Stage 7 - Validation and Reporting

## Plan
- 목표: 내부 일관성 검증, 누락/불확실 식별, 최종 CSV/Excel 및 감사 리포트 패키징
- 입력: `test_case_matrix`, `constraint_registry`, `source metadata`
- 출력:
  - `npu_testcase_table.csv` or `npu_testcase_table.xlsx`
  - `unresolved_report`
  - `coverage_report`
  - `audit_report`
- 완료 기준:
  - 타입/도메인/의존성 위반 탐지
  - 미분류 제약 및 미추출 항목 전수 보고

## Status
- 상태: Scaffolded
- 구현률: 25%
- 오픈 이슈:
  - 품질 게이트 계산 로직 미구현
  - unresolved/audit 상세 리포트 미구현
- 다음 액션:
  - Gate 계산기와 실패 조건(exit code) 구현
  - CSV/Excel 동시 출력 옵션 추가

## Technical Note
- 정확도와 추적성을 동일 우선순위로 관리
- 리포트는 사람이 재검증할 수 있도록 원문 근거 링크 중심으로 구성
