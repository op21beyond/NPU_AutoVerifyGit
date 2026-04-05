# Stage 5 - Mission Ontology and Constraint Typing

## Plan
- 목표: 미션 전체 엔티티(IP/ExecutionUnit/명령어/필드/데이터타입/값도메인/제약/메타)를 온톨로지로 구성하고, 제약 유형을 동적 분류
- 입력: `page_blocks`, `instruction_catalog`, `instruction_field_map`, `global_field_schema`, `field_alias_map`, `field_domain_catalog`
- 출력:
  - `mission_ontology_graph`
  - `constraint_registry`
  - `constraint_type_catalog`
  - `constraint_classification_report`
- 완료 기준:
  - `IP/ExecutionUnit/Instruction/Field/DataType/ValueDomain/Constraint/Metadata` 엔티티 연결 완료
  - 고정 타입 전제가 아닌 후보 수집/클러스터링 수행
  - `ConstraintType` L1/L2 매핑
  - 미분류 제약(`unclassified_constraint`) 관리

## Status
- 상태: Implemented (`field_domain_catalog` 기반 제약 행 + `instruction_catalog`·타입·필드 연결 온톨로지)
- 구현률: ~45%
- Ground truth 옵션:
  - `--ground-truth-as-output` + `--ground-truth PATH` — GT(`.json` 또는 `.txt/.lst/.list`)에서 `constraint_registry`·`mission_ontology_graph` 직접 기록
  - `--ground-truth`만 — `constraint_id` 집합 및 온톨로지 `nodes(id)` / `edges(from,rel,to)` 기준으로 `evaluation_report.json`
  - 예시 파일: `ground_truth_examples/stage5_ground_truth.txt`
    - 평가: `python -m src.stage5_constraint_ontology.main --ground-truth ground_truth_examples/stage5_ground_truth.txt`
    - 정답 직접 출력: `python -m src.stage5_constraint_ontology.main --ground-truth-as-output --ground-truth ground_truth_examples/stage5_ground_truth.txt`
  - 텍스트 GT는 `CONSTRAINT|...`, `NODE|...`, `EDGE|from|rel|to` 라인 기반이며 부분 항목만 작성 가능
  - `Instruction` 노드 id: `Instr:{opcode}` 또는 variation 있으면 **`Instr:{opcode}_{VAR}`** (파이프 구분자와 충돌 없음). `instruction_catalog`의 `variation` 반영
- 오픈 이슈:
  - 제약 후보 수집/클러스터링 미구현
  - 온톨로지 그래프는 seed 수준
- 다음 액션:
  - 제약 추출 rule set 및 retrieval 파이프라인 연동
  - `ConstraintType` 분류기와 미분류 큐 로직 구현

## Technical Note
- 온톨로지 핵심 관계:
  - `IP HAS_INSTRUCTION Instruction`
  - `Instruction EXECUTES_ON ExecutionUnit` (instruction_catalog의 `execution_unit` 반영)
  - `Instruction` 속성: `instruction_kind` (macro/micro/unknown), OPCODE (`opcode_raw`, `opcode_radix`, `opcode_value`)
  - `Instruction HAS_FIELD Field`
  - `Field HAS_DATATYPE DataType`
  - `Field HAS_DOMAIN ValueDomain`
  - `Constraint INSTANCE_OF ConstraintType`
  - `Constraint APPLIES_TO Instruction|Field|FieldSet`
  - `Entity HAS_METADATA Metadata`
- IP 메타 필수 속성:
  - `ip_name`, `ip_type`, `ip_version`, `ip_additional_info`
- 분류 실패를 삭제하지 않고 큐로 유지해야 정확도 개선 루프가 가능
- 규칙 기반 분류 우선, LLM API는 미분류/충돌 케이스에만 사용
