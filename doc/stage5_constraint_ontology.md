# Stage 5 - Mission Ontology and Constraint Typing

## Plan
- 목표: Stage4/4b/4c 산출과 `instruction_catalog`로 **미션 온톨로지**를 만들고, **제약(constraint)** 을 등록한다.
- 입력: `datatype_registry`(Stage4), `field_datatype_catalog`(Stage4b), `field_domain_catalog`(Stage4c), `instruction_catalog`, `page_blocks`(선택 LLM 경로)
- 출력:
  - `constraint_registry.jsonl` — `field_domain_catalog`에서 파생된 행 + (선택) **문서에서 LLM이 추출한 제약**
  - `constraint_pruning_index.json` — `constraint_type_catalog`의 **canonical 카테고리**와 레지스트리 행(`constraint_type_level1` 등)을 묶은 **Stage6 프루닝 연계용 요약**(실제 프루닝은 Stage6에서 단계적 구현)
  - `mission_ontology_graph.json` — IP / EU / Instruction / Field / DataType / Constraint 노드 및 엣지
  - (OpenAI 사용 시) `constraint_candidates.json`, `constraint_type_catalog.json` — 후보 문장·**카테고리 정규화** 결과
  - (OpenAI 사용 시) `ontology_value_bindings.json` — 온톨로지 노드에 대한 **값 추출** 바인딩
  - `stage5_report.json` — 집계·스킵 사유(`constraint_pruning_index_path` 포함)
  - `mission_graph_kuzu/graph.kuzu` — **Kuzu** 오픈소스 임베디드 그래프 DB(노드/엣지; `mission_ontology_graph.json`과 동일 내용). `--skip-kuzu-graph-db`로 생략 가능.

## Status
- 구현: `build_constraint_registry` + `build_mission_ontology_graph` + **`llm_stage5`** (제약 문장 추출 → 카테고리 정규화 → 값 추출).
- OpenAI: `OPENAI_API_KEY`가 있고 `--skip-llm-constraints` / `--skip-llm-values`를 주지 않으면 LLM 경로 실행.
- 페이지 범위: `--page-start` / `--page-end` — Stage1과 동일 의미로 `page_blocks` 필터.
- 선택: `--use-rag` 등 — LLM에 넣기 전 `page_blocks`를 Stage1 FAISS로 축소([`doc/rag_integration_checklist.md`](rag_integration_checklist.md)).

## CLI
```bash
python -m src.stage5_constraint_ontology.main
python -m src.stage5_constraint_ontology.main --page-start 1 --page-end 50
python -m src.stage5_constraint_ontology.main --skip-llm-constraints --skip-llm-values   # 도메인 파생 제약만
python -m src.stage5_constraint_ontology.main --use-rag --rag-top-k 48   # LLM 전 page_blocks FAISS 축소(Stage1 인덱스 필요)
python -m src.stage5_constraint_ontology.main --skip-kuzu-graph-db       # JSON 그래프만; Kuzu 파일 생략
```

## Ground truth
- `--ground-truth-as-output` + `ground_truth_examples/stage5_ground_truth.txt` 등 (기존과 동일).

## Technical Note
- **도메인 파생 제약 표현**: `field_domain_catalog` 한 줄당 한 제약 행. `allowed_value_form`이 `enum`이면 `FIELD IN (…)`, `range`이면 `lo <= FIELD <= hi`(점 범위·하이픈·16진 `0x..0x` 패턴 지원). `allowed_values_or_range`가 비어 있으면 의미 없는 기호 대신 **명시적 placeholder** 표현을 씀. 행에 `domain_constraint_meta`(구조화 메타)가 붙을 수 있음.
- **교차 필드·조건부 제약**(예: opcode에 따른 필드 값)은 도메인 한 줄로는 표현되지 않음 → LLM 경로(`extract_constraint_candidates_openai`) 또는 후속 규칙 엔진이 필요. 품질 확인용으로 `OPENAI_API_KEY`가 있을 때만 실행되는 스모크 테스트: `tests/test_stage5_llm_constraints_optional.py`.
- JSON 그래프 시각화: [`tools/ontology_graph_viewer`](../tools/ontology_graph_viewer/README.md) — `streamlit run tools/ontology_graph_viewer/app.py` (앱 내 사용 안내).
- 온톨로지 핵심 관계(계획): `IP HAS_INSTRUCTION`, `Instruction EXECUTES_ON` EU, `Instruction HAS_FIELD`, `Field HAS_DATATYPE`, 제약은 `Field` 또는 `Instruction` 또는 문서 전역(`Document` → `IP:sample`)에 `APPLIES_TO`.
- LLM 제약 행은 `constraint_type_level2`: `llm-document`.

### 제약 카테고리 정규화 (휴리스틱 아님)
- 1차 추출에서 나온 `constraint_category_candidate` 문자열들은 호출마다 표현이 달라질 수 있음(예: 값 범위 vs 허용 값).
- **2차 LLM 호출**만으로 동의어·유사 표현을 묶어 `canonical_categories` + `mapping` 생성(코드에서 의미 클러스터링·편집거리 사용 안 함).
- 같은 배치에 Stage4c `field_domain_catalog`의 `allowed_value_form`(예: `range`, `enum`)을 넣어, 도메인 메타와 추출 라벨을 한 번에 정규화한다.
- 모델이 어떤 입력 키를 빠뜨린 경우에만 키 보존용으로 동일 문자열 매핑을 채운다(의미 추론은 LLM에만 의존).
