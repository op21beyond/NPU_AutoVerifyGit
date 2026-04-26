# Vector DB / RAG 통합 체크리스트

## 구현 상태 (요약)

- **Stage1** `--build-rag-index`: OpenAI 임베딩 + **FAISS** `IndexFlatIP`, `artifacts/stage1_ingestion/rag_index/` (`rag_manifest.json`, `faiss.index`, `metadata.jsonl`, 페이지→블록 계층은 manifest `page_hierarchy`).
- **Stage2 / 4 / 4b / 4c / 5**: `--use-rag` + `--rag-index-dir`(선택) + `--rag-top-k` + `--rag-query`(선택) + `--rag-embedding-model` — LLM 호출 전 `narrow_page_blocks_with_optional_rag`로 블록 축소; `extraction_summary` / `stage5_report`에 `rag` 통계.
- **Stage5 (선택)** [LightRAG](https://github.com/hkuds/lightrag): `--use-lightrag` + `src/common/lightrag_resolve.py` — `lightrag-hku`로 블록 인덱싱 후 `aquery_data`로 축소; FAISS `--use-rag`와 동시 사용 불가. 통합 파이프라인은 `--use-rag`로 2~4c에 FAISS를 주면서 Stage5만 `--use-lightrag`로 줄 수 있음.
- **Stage5** 끝: **Kuzu** 오픈소스 임베디드 그래프 DB `mission_graph_kuzu/graph.kuzu` (`--skip-kuzu-graph-db`로 생략 가능).
- **도구**: `tools/rag_graph_chatbot/app.py` — FAISS + Kuzu + OpenAI 멀티턴 챗.
- **도구**: `tools/ontology_graph_viewer/app.py` — `mission_ontology_graph.json` Pyvis 시각화(앱 내 사용 안내).

Stage1 이후 `page_blocks`를 여러 단계에서 다시 직렬화해 LLM에 넣으면 **토큰·지연**이 커진다. 아래는 **현재 코드 기준**으로 어디를 바꾸면 되는지, 그리고 **단계적 도입**을 정리한 체크리스트다.

## 1. 현재 상태 (공통 직렬화)

| 항목 | 위치 |
|------|------|
| 직렬화 | `src/common/llm_page_blocks.py` — `serialize_page_blocks_for_prompt(page_blocks, max_total_chars=100_000)` |
| 동작 | 페이지 순으로 블록을 이어 붙이고, **총 문자 상한**에서 잘림(말미에 `...[truncated]` 가능) |

즉, LLM 호출부는 모두 **“필터된 `page_blocks` 전체 → 한 덩어리 문자열”** 패턴이다.

## 2. LLM이 `page_blocks`를 쓰는 스테이지·함수

| Stage | 모듈 | 함수 | 비고 |
|-------|------|------|------|
| 2 | `stage2_instruction_extraction/llm_openai.py` | `build_instruction_catalog_openai` | 명령 카탈로그 추출 |
| 4 | `stage4_domain_typing/llm_datatype_registry.py` | `build_datatype_registry_openai` | `datatype_registry` |
| 4b | `stage4b_field_datatype_catalog/llm_field_datatype.py` | `build_field_datatype_catalog_openai` | 필드–타입 매핑 |
| 4c | `stage4c_field_domain_catalog/llm_field_domain.py` | `build_field_domain_catalog_openai` | 값 도메인 |
| 5 | `stage5_constraint_ontology/llm_stage5.py` | `extract_constraint_candidates_openai` | 제약 후보 문장 |
| 5 | 동일 | `extract_ontology_values_openai` | 온톨로지 노드 값 바인딩 |

`normalize_constraint_categories_openai`는 **카테고리 문자열 배치** 위주라 `page_blocks` 직렬화가 아니라도 동작한다(별도 RAG 우선순위 낮음).

**Stage3**은 현재 LLM 경로 없음(휴리스틱 + 선택 치트시트). 나중에 Stage3에 LLM을 넣을 경우에도 **동일 RAG 파이프**를 재사용할 수 있다.

## 3. RAG로 바꿀 때의 “검색 질의” 후보

스테이지마다 프롬프트 목적이 다르므로, 검색 쿼리는 **고정 한 줄**보다 **구조화된 힌트**가 유리하다.

| Stage | 쿼리에 넣기 좋은 힌트 |
|-------|------------------------|
| 2 | (초기) 문서 전체 요약 키워드 제한적 → **섹션 제목/목차가 있으면** 그걸로 1차 축소; 없으면 **페이지 슬라이스 + 임베딩** 병행 |
| 4 | “data type”, “format”, “bitwidth”, 표 제목 등 **용어 후보** + Stage2 산출 `instruction_name` 목록 일부 |
| 4b | `instruction_field_map`의 `(instruction, field)` 쌍을 배치로 임베딩 쿼리 |
| 4c | 필드명 + “allowed values”, “range”, “enum” 등 |
| 5 | 이미 추출된 제약 후보/필드명 + 자연어 질의 |

**하이브리드**(메타 필터 + 벡터): `page`, `block_type`(table/text), `block_id`로 먼저 좁힌 뒤 벡터 상위 k — 표 블록 누락을 줄인다.

## 4. 구현 단계 (권장 순서)

아래 Phase A~D는 **초기 로드맵·추가 개선용**이다. **FAISS 인덱스 + 스테이지별 `--use-rag` + Kuzu 내보내기**는 이미 코드에 반영되어 있다(§구현 상태 요약). 체크박스는 향후 하이브리드 필터·토큰 통계 등을 넣을 때 참고하면 된다.

### Phase A — 설계 고정 (코드 변경 최소)

- [ ] **청크 단위**: `page_blocks` 1행 = 1문서 vs 블록 내부 문단 분할 — 표는 **블록 단위 유지** 권장.
- [ ] **아티팩트**: 예) `artifacts/stage1_ingestion/page_block_index_manifest.json`(해시, 임베딩 모델 id, 차원) + 벡터 저장소 경로/ID.
- [ ] **재현**: 동일 PDF + 동일 Stage1 출력이면 인덱스 재사용; 바뀌면 재임베딩.

### Phase B — 인덱스 빌더 (Stage1 직후)

- [ ] Stage1 산출 `page_blocks.jsonl` 읽기.
- [ ] 청크별 `text` + 메타(`page`, `block_id`, `block_type`, `bbox` 선택).
- [ ] 임베딩 API 호출(또는 로컬 모델) → Vector DB에 upsert.
- [ ] CLI 또는 `tools/` 스크립트로 분리해 **파이프라인 옵션**(`--build-vector-index`)에만 연결.

### Phase C — 공통 검색 API

- [ ] `retrieve_page_blocks_for_llm(query: str | StructuredQuery, k: int, filters: ...) -> List[Dict]`  
      반환은 **원본 `page_blocks` 행의 부분집합**(또는 동일 스키마).
- [ ] `serialize_page_blocks_for_prompt` **앞단**에서 호출하거나, `serialize_*`에 `mode=full|rag` 플래그 추가.

### Phase D — 스테이지별 연동 (토큰 절감 효과 큰 순서)

우선순위는 **호출당 입력이 긴 순**이 일반적이다.

- [ ] Stage5 `extract_constraint_candidates_openai` / `extract_ontology_values_openai`
- [ ] Stage4 / 4b / 4c
- [ ] Stage2 (전역 맥락 필요 → k 크게 잡거나 **2-hop**: 먼저 후보 페이지만 필터 후 RAG)

각 단계마다:

- [x] (구현됨) `--use-rag` 및 `--rag-index-dir` 등으로 인덱스 활성화.
- [ ] 폴백: 인덱스 없거나 검색 결과 0건이면 **현재 동작(전체 직렬화)** 유지.
- [ ] `stage5_report.json` / `extraction_summary.json` 등에 `rag_retrieval_stats`(k, 필터, 토큰 추정) 기록 권장.

## 5. 리스크·주의

- **재현율**: k가 작으면 스펙 문장 누락 → **k·윈도우(같은 페이지 이웃 블록 포함)** 튜닝 필요.
- **표/캡션 분리**: 헤더만 잡히고 데이터 행이 빠지면 실패 → **같은 page 인접 블록 병합** 규칙 검토.
- **비용**: LLM 토큰은 줄어도 **임베딩 비용·저장**이 추가됨.
- **온프레미스/정책**: Vector DB 제품(예: Chroma, Qdrant, LanceDB, pgvector)과 임베딩 모델 선택은 배포 환경에 맞출 것.

## 6. 관련 문서

- 상위 아키텍처·저장소 역할: [`implementation_plan.md`](implementation_plan.md) (Vector DB / RAG 언급 구간).
- 통합 파이프라인: [`integration_pipeline.md`](integration_pipeline.md).

이 문서는 **RAG·온톨로지 관련 구현 요약**과 **추가 개선 체크**를 겸한다. CLI·산출물 변경 시 `CHANGES.md`에 한 줄 남길 것.
