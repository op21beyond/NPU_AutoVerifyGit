# Workflow Guide — Automatic Ontology Extraction

## 가정 (Assumptions)

- **입력**: 영문 NPU 아키텍처 문서(PDF/Markdown), 수십~수백 페이지.
- **시드**: [`few_shot_seed.md`](few_shot_seed.md) — partial. 전체 온톨로지의 30–40% 정도라고 본다. 파이프라인은 시드를 **시작 힌트**로만 사용하고, 시드 밖의 타입을 적극 발견해야 한다.
- **출력**: property-graph JSON (엔터티 노드 + 타입 엣지 + 속성). 그래프 DB 종류는 무관.
- **LLM / 임베딩 / DB**: 팀이 결정. 본 가이드는 호출 횟수와 의미적 단계만 규정.

## 파이프라인 (7 steps)

```
① 청크 분할 (Python)
       ↓
② 청크별 스키마 후보 추출  ← LLM 호출 A (청크당 1회, 순차 + Running glossary)
       ↓
③ 스키마 합집합 + 정규화  ← Python 압축 → LLM 호출 B (1~K+1회, 토큰 크기에 따라 분기)
       ↓
④ 청크별 인스턴스 추출    ← LLM 호출 C (청크당 1회)
       ↓
⑤ 인스턴스 dedup           ← 임베딩 + LLM 호출 D (애매한 쌍만)
       ↓
⑥ 스키마 재조정 (선택)     ← LLM 호출 E (novel_* 발견 시 1회)
       ↓
⑦ 그래프 DB 적재 (Python)
```

각 단계의 중간 산출은 **반드시 JSON 파일로 저장**해 단계별로 검증 가능해야 한다.

---

### Step 1 — 청크 분할 (Python)

가능하면 의미 경계(섹션 제목, 표 단위)로, 어려우면 슬라이딩 윈도우(예: 4–8K 토큰, 10% 오버랩)로 분할.

산출: `chunks/{i}.json` `{chunk_id, source_page_range, text}`.

---

### Step 2 — 청크별 스키마 후보 추출 (LLM 호출 A, N회, **순차 + Running glossary**)

**실행 모드**: **순차 직렬**. 사용 LLM이 배치를 지원하지 않는다고 가정한다. 청크를 순서대로 처리하면서, 앞 청크들에서 발견한 타입의 **이름과 빈도만** 압축해 다음 호출에 prior로 전달한다 (running glossary).

**핵심 원칙**:
- 시드는 **partial**이라는 것을 모델이 분명히 인지하게 한다.
- glossary는 **soft preference** — 강제 아님. 같은 개념이면 재사용, 다른 개념이면 새 이름.
- glossary에는 **이름과 빈도만** 넣는다 (definition·evidence 제외) — 의미 추론을 prior에 위임하지 않게.

#### Running glossary 자료구조

매 호출 후 갱신해 다음 호출에 넘긴다.

```json
{
  "entity_names_seen": [
    {"name": "Instruction",    "freq": 7},
    {"name": "ExecutionUnit",  "freq": 5},
    {"name": "MemoryRegion",   "freq": 3}
  ],
  "relation_names_seen": [
    {"name": "EXECUTES_ON", "freq": 6},
    {"name": "HAS_FIELD",   "freq": 7}
  ]
}
```

갱신 규칙:
1. 호출 결과의 `entity_types[*].name` / `relation_types[*].name`을 추출.
2. 기존 glossary의 같은 이름은 `freq += 1`, 신규 이름은 `freq = 1`로 추가.
3. **상한 적용**: 빈도 내림차순으로 정렬 후 상위 N개만 유지 (권장: 엔터티 50, 관계 60). 빈도 1짜리 꼬리는 잘라내 토큰 폭증 방지.
4. 0번째 청크에서는 glossary가 비어 있는 상태로 시작.

#### 프롬프트 템플릿
```
SYSTEM:
당신은 NPU 아키텍처 문서의 한 청크에서 엔터티 타입과 관계 타입을 추출한다.

아래 시드 예시는 **이 도메인의 모든 타입이 아니라, 일부 대표 예시**다. 실제
NPU 스펙은 보통 엔터티 타입 15–30개, 관계 타입 20–40개를 갖는다. 시드의
5~7개는 그중 일부일 뿐이다.

또한 RUNNING GLOSSARY는 앞 청크들에서 이미 발견된 이름과 빈도다 (soft
preference). 의미가 같다면 같은 이름을 재사용해 일관성을 유지하라. 단,
본 청크의 개념이 분명히 다르다면 새 이름을 만들어라 — 끼워 맞추지 마라.

당신의 작업:
- 이 청크에서 등장하는 엔터티 타입·관계 타입을 제안한다.
- 청크의 개념이 시드 또는 glossary 항목과 일치하면 그 이름을 그대로 쓴다.
- 시드·glossary에 없는 개념은 **새 이름을 만든다**. 반드시
  "is_extension_of_seed": false 로 표시한다.
- 끼워 맞추지 마라. 본 청크의 개념이 다르면 새 타입을 만들어라.
- 명명 규칙: 엔터티는 PascalCase, 관계는 SCREAMING_SNAKE_CASE.

JSON만 반환:
{
  "entity_types": [
    {"name": "...", "definition": "...",
     "is_extension_of_seed": <bool>,
     "reused_from_glossary": <bool>,
     "evidence": "<문서 인용>"}
  ],
  "relation_types": [
    {"name": "...", "domain": "<엔터티 타입>", "range": "<엔터티 타입>",
     "definition": "...", "is_extension_of_seed": <bool>,
     "reused_from_glossary": <bool>,
     "evidence": "<문서 인용>"}
  ]
}

USER:
[FEW-SHOT INSERT POINT — partial seed]
{ few_shot_seed.md 의 entity_types + relation_types JSON 블록 with
  "is_seed": true, "is_partial": true, "expected_total_*_hint" 메타 }

[RUNNING GLOSSARY — soft preference, 이름·빈도만]
{ 앞 청크 누적 glossary JSON; 0번째 청크에서는 빈 객체 }

[CHUNK]
{chunk_text}
```

산출:
- `schema_candidates/{chunk_id}.json` — 매 호출의 원본 결과.
- `glossary_after/{chunk_id}.json` — 그 청크 처리 후의 누적 glossary 스냅샷 (감사용).

> ⚠️ **시드·glossary anchoring 회피 6요령** (전부 적용 권장)
> 1. 시드 JSON에 `"is_seed": true`, `"is_partial": true` 메타.
> 2. 프롬프트에서 "15–30 / 20–40" 같은 *기대 규모*를 명시.
> 3. `is_extension_of_seed` 필드로 새 타입을 의식적으로 만들게 강제.
> 4. `few_shot_seed.md`의 "의도적으로 빠진 항목" 섹션을 프롬프트에 함께 넣음.
> 5. "Do NOT force-fit" 부정 지시.
> 6. **Glossary는 이름·빈도만** 넘기고 "soft preference"로 명시. definition을 넣으면 모델이 의미를 prior에 위임해 새 발견이 줄어든다.

> 💡 **드물지만 필요한 경우의 가드**: glossary 상한(엔터티 50/관계 60)을 넘는 시점부터는 빈도 1짜리가 잘리므로, "최근에 한 번만 본 이름"이 잊혀진다. 다음 청크에서 같은 개념이 다시 등장하면 새 이름을 만들 가능성이 있고, 이는 Step 3 정규화가 흡수한다 (의도된 동작).

> 🚫 **하지 말 것**: glossary에 evidence 인용·definition·domain/range 정보를 함께 넣지 말 것. 호출당 토큰이 청크 수에 비례해 폭증하고, 모델이 prior에 의미 추론을 위임하기 시작한다.

---

### Step 3 — 스키마 합집합 + 정규화 (LLM 호출 B, 1~K+1회)

순진한 "raw 합집합 → 한 번에 LLM 호출"은 위험하다. 청크 N이 100을 넘으면 raw 페이로드가 컨텍스트 한도(200K 토큰)를 향해 빠르게 커진다. **Python에서 먼저 압축**한 뒤, 토큰 크기에 따라 단일/버킷/계층 호출로 분기한다.

#### 3-1. Python 압축 (LLM 호출 전, 항상 수행)

1. `schema_candidates/*.json` 전부 로드.
2. **이름 기준 exact dedup** (대소문자 무시 권장): 같은 이름은 한 행으로 합침.
3. 같은 이름의 정의가 여러 개면 **하나만** 보존 (가장 짧은 것 또는 첫 등장 것). 정의는 모델이 클러스터링 판단할 때만 쓰이고 출력엔 안 들어감.
4. **`evidence` 인용은 전부 폐기** — 가장 큰 토큰 소비처. Step 3는 evidence 없이도 동작한다.
5. 각 행에 **빈도(`freq`)** 첨부 — 모델이 어느 이름이 dominant인지 알게 함.

압축 결과:
```json
{
  "entity_types": [
    {"name": "Instruction",   "freq": 87, "definition": "..."},
    {"name": "compute_unit",  "freq": 3,  "definition": "..."},
    {"name": "ComputeUnit",   "freq": 41, "definition": "..."}
  ],
  "relation_types": [
    {"name": "EXECUTES_ON", "freq": 62, "domain": "Instruction", "range": "ExecutionUnit", "definition": "..."}
  ]
}
```

산출: `schema_union_compact.json` (디버깅·감사용).

#### 3-2. 토큰 추정 후 분기

```
estimated_tokens = count_tokens(schema_union_compact.json)

if estimated_tokens < 30_000:        # 잘 anchoring된 일반 케이스
    one_shot_normalize(...)
elif estimated_tokens < 100_000:     # 변형 많음 / 대형 문서
    bucketed_normalize(K=5~10, ...)
else:                                # 병리적 — 앵커링 무력화
    hierarchical_normalize(...)
```

토큰 카운트는 사용 LLM의 토크나이저(또는 보수적 추정 `chars / 3`)를 쓴다.

#### 3-3a. 단일 호출 정규화 (< 30K 토큰)

`schema_union_compact.json`을 그대로 LLM에 넣고 1회 호출.

```
SYSTEM:
당신은 NPU 문서의 여러 청크에서 독립적으로 추출된 엔터티/관계 타입 이름의
합집합(빈도·짧은 정의 포함)을 받는다. 청크마다 같은 개념을 다르게 부른
경우가 많다 (예: "ComputeUnit" vs "compute_unit" vs "ProcessingUnit").

규칙:
- 같은 의미의 이름들을 클러스터링한다. 빈도·정의를 단서로 활용하라.
- 클러스터당 canonical 이름 1개 선택 (엔터티 PascalCase, 관계
  SCREAMING_SNAKE_CASE). 가능하면 빈도가 높은 변형을 canonical로.
- 모든 입력 이름을 정확히 한 canonical에 매핑한다.
- 여기서 새 타입을 만들지 마라. 통합만 한다.
- 관계는 domain/range를 보존한다.

JSON만 반환:
{
  "entity_types": [{"canonical": "...", "aliases": [...], "definition": "..."}],
  "relation_types": [{"canonical": "...", "aliases": [...],
                       "domain": "...", "range": "...", "definition": "..."}],
  "merge_rationale": "<짧은 설명>"
}

USER:
{schema_union_compact.json 내용}
```

> **공통**: 아래 3-3b, 3-3c에 등장하는 `LLM_normalize(...)`는 **모두 3-3a의 동일 프롬프트**를 입력만 바꿔 호출하는 것이다. 별개의 프롬프트가 아니다.

#### 3-3b. 버킷 정규화 (30K ~ 100K 토큰)

이름들을 임베딩 → 코사인 클러스터링으로 K개 버킷에 분배 → 각 버킷 독립 정규화 → 마지막에 **버킷 canonical만 모아 한 번 더** 정규화 (cross-bucket 동의어 처리).

```
1. embed all names (entity·relation 각각 별도로)
2. cluster into K buckets (K=5~10, 균등 크기 목표; KMeans 등 단순 알고리즘으로 충분)
3. for each bucket b:
       bucket_result[b] = LLM_normalize(bucket_b)   # 3-3a 프롬프트
       # bucket_result[b] = {entity_types:[{canonical, aliases, definition}, ...],
       #                     relation_types:[...], merge_rationale:"..."}
4. final_input = union of all bucket_result[*]'s canonicals
                 (각 canonical을 새 정규화 입력 행으로 취급, freq는
                  그 canonical의 alias들의 freq 합으로 누적)
5. final_result = LLM_normalize(final_input)
6. alias 체인 평탄화 (per input name n):
       bucket = bucket_result[찾은 버킷]
       intermediate_canonical = bucket의 어느 cluster에 n이 매핑되었는지
       final_canonical = final_result에서 intermediate_canonical이 매핑된 곳
       schema.aliases[final_canonical] += [n, intermediate_canonical]
       (중복 제거; 중간 단계도 보존해 추적 가능하게)
```

호출 횟수: K + 1.

> 임베딩 모델은 Step 5에서 쓰는 것을 재사용. 클러스터링은 단순 KMeans로 충분.
>
> 평탄화 시 **중간 canonical을 aliases에 함께 포함**하는 이유: 디버깅·감사 시
> "이 이름은 어떤 버킷에서 어떤 중간 이름을 거쳐 최종 canonical이 됐는가"를 추적할 수 있다.
> 풀 체인은 `schema_normalize_log.json`에도 별도 보존.

#### 3-3c. 계층 합병 (> 100K 토큰, 병리적 경우)

페어와이즈 트리 머지로 깊이 log₂(M) 만큼 단계적으로 정규화한다.

```
buckets = embedding_split(names, max_size_each < 30K_tokens)
   # 임베딩 클러스터로 분할; 각 버킷이 단일 호출 안에 들어가도록 크기 제한.
   # M = len(buckets); 각 버킷은 {entity_types, relation_types, freq...} 형태.

level = 0
while len(buckets) > 1:
    new_buckets = []
    for pair in zip(buckets[0::2], buckets[1::2]):
        merged_input = union of pair
            # 각 버킷의 canonical을 입력 이름으로 취급, alias·freq는
            # 누적 합쳐서 새 정규화 입력 행으로 만든다.
        merged = LLM_normalize(merged_input)   # 3-3a 프롬프트 재사용
        new_buckets.append(merged)
    if len(buckets) % 2 == 1:
        new_buckets.append(buckets[-1])   # 홀수 개면 마지막은 그대로 다음 레벨로
    buckets = new_buckets
    level += 1

schema = buckets[0]
```

페어 선택은 **인덱스 순서대로** (단순). 임베딩 유사도 기반 페어링도 가능하지만 구현 복잡도만 늘고 품질 차이는 미미함 — 안 함.

종료 조건: 버킷이 1개로 줄 때까지.

Alias 체인 평탄화: 매 레벨마다 부모 canonical 안에 자식 canonical을 alias로 누적. 최종 `schema.json`의 각 canonical은 **모든 레벨의 중간 canonical + 원본 이름**을 aliases에 갖는다. 풀 체인은 `schema_normalize_log.json`에 레벨별 trace로 보존.

호출 횟수: ≈ M − 1, 깊이 log₂(M).

#### 산출

- `schema_union_compact.json` — 압축된 union (LLM에 보낸 페이로드).
- `schema.json` — 최종 canonical 스키마.
- `schema_normalize_log.json` — 분기 결정(단일/버킷/계층), 토큰 추정치, 버킷 구성·각 호출 결과(있으면) 등 감사 정보.

> ⚠️ **하지 말 것**:
> - raw `schema_candidates/*.json`을 그대로 합쳐 LLM에 넣지 말 것 (evidence 때문에 토큰 폭증).
> - 압축 단계에서 빈도(`freq`) 정보를 버리지 말 것 — 모델의 canonical 선택 품질이 떨어진다.
> - 토큰 추정 없이 단일 호출만 가정하지 말 것 — 청크 200개 이상 문서에서 무성하게 잘릴 수 있다.

---

### Step 4 — 청크별 인스턴스 추출 (LLM 호출 C, N회)

Step 3의 `schema.json`을 프롬프트에 넣고, 각 청크에서 인스턴스를 추출. **open-schema**: 스키마에 없는 명백한 개념은 `novel_*`로 보고.

```
SYSTEM:
아래 canonical 스키마에 따라 이 청크의 엔터티/관계 인스턴스를 추출한다.
스키마가 분명히 다루지 못하는 개념을 만나면 novel_entities / novel_relations
에 추가하고 새 타입 이름을 제안한다.

규약:
- "id"는 청크 안에서 안정적인 문자열 (예: "Instruction:CONV2D").
- "type"은 스키마의 canonical 이름 또는 novel_* 안의 새 이름.
- 모든 엔터티/관계에 "evidence" (문서 짧은 인용) 필수.

반환:
{
  "entities": [
    {"id": "...", "type": "<canonical>", "name": "...",
     "properties": {...}, "evidence": "..."}
  ],
  "relations": [
    {"from_id": "...", "type": "<canonical>", "to_id": "...",
     "properties": {...}, "evidence": "..."}
  ],
  "novel_entities": [...],
  "novel_relations": [...]
}
```

산출: `instances/{chunk_id}.json`.

---

### Step 5 — 인스턴스 dedup (임베딩 + LLM 하이브리드)

1. 모든 엔터티를 `name + type + 핵심 속성` 직렬화 후 임베딩.
2. ANN/코사인 유사도로 임계값 τ 이상 후보쌍 추출. **τ 기본 0.85, CLI 인자 `--dedup-threshold`로 노출**.
3. 후보쌍만 LLM에게 "이 둘이 같은 실체인가?" 질의.
4. canonical-id 매핑 구축 → 모든 relation의 `from_id`/`to_id` 재작성.
5. 모든 비교쌍·유사도 점수·LLM 판단·최종 결정을 `dedup_decisions.json`에 audit log로 남김.

> 1k 이상이면 FAISS/HNSW 사용. 페어와이즈 행렬은 O(n²)라 빠르게 깨진다.
> τ는 짧은 엔터티명에서 잘못 통합될 위험이 있으므로 audit log를 보고 조정한다.

산출: `entities_canonical.json`, `relations_canonical.json`, `dedup_decisions.json`.

---

### Step 6 — 스키마 재조정 (LLM 호출 E, 선택)

Step 4에서 `novel_*`가 비어 있지 않다면:
1. `canonical_schema ∪ novel_*`을 다시 Step 3 정규화 프롬프트에 넣어 재정규화.
2. 영향 받는 인스턴스 `type` 필드를 새 canonical로 갱신.

산출: `schema_v2.json`, `entities_canonical_v2.json`, `relations_canonical_v2.json`.

---

### Step 7 — 그래프 DB 적재 (Python)

- 엔터티: canonical id로 MERGE (중복 없이).
- 관계: 방향성·타입·속성 보존.
- 모든 노드/엣지에 `evidence`와 `source_chunk_id`를 속성으로 보존 — **추후 검증의 유일한 단서**다.

---

## 팀이 결정할 항목

| 항목 | 비고 |
|------|------|
| LLM 제공자 | Anthropic / OpenAI / 로컬 — 무관 |
| 임베딩 모델 | sentence-transformers, OpenAI 등 — 무관 |
| 그래프 DB | Neo4j, Kuzu, 그 외 — 무관 |
| 청크 크기·오버랩 | 4–8K 토큰 / 10% 오버랩 권장 |
| `--dedup-threshold` | 기본 0.85 |
| 프롬프트 언어 | 한/영 무관, 일관 유지 |

## 위험 요소 (체크리스트)

- [ ] **시드·glossary anchoring**: Step 2의 6요령 모두 적용했는가? 특히 glossary가 이름·빈도만 담고 있는가?
- [ ] **순차 carryover 진행**: Step 2가 청크 0번부터 N-1번까지 순서대로 호출되고, 매 호출 후 glossary가 갱신되어 다음 호출에 전달되는가?
- [ ] **Step 3 압축 적용**: raw schema_candidates를 그대로 LLM에 보내지 않고 Python 압축(exact dedup, evidence 폐기, freq 첨부)을 거쳤는가? 토큰 추정 후 단일/버킷/계층 분기를 선택했는가?
- [ ] **청크 누락**: 스키마 합집합 단계가 모든 청크 후보를 다 받았는가? (silent loss 주의)
- [ ] **τ 튜닝**: dedup audit log를 본 뒤 임계값을 데이터셋에 맞게 조정했는가?
- [ ] **evidence 손실 금지**: Step 7까지 모든 단계에서 verbatim evidence가 살아남는가?
- [ ] **Open-schema 누수**: Step 4의 `novel_*`가 비어 있지 않은데 Step 6를 건너뛰지 않았는가?

## 호출 횟수 추정

- 청크 N개일 때 LLM 호출 ≈ `N (스키마 후보, 순차) + 1~K+1 (정규화, 토큰 크기에 따라 단일/버킷/계층) + N (인스턴스) + k (dedup 확인) + 0~1 (재조정)`.
- 임베딩 호출 ≈ `엔터티 수`.
- **순차 처리 시간**: Step 2와 Step 4가 직렬이므로 총 LLM 시간은 `≈ 2N × 호출당 지연시간`. 예: 청크 100개 × 호출당 8초 ≈ 27분 (Step 2+4 합).
- Step 2 호출의 입력 토큰은 청크가 진행될수록 glossary 누적으로 미세 증가하지만, 상한(엔터티 50 + 관계 60 × 이름·빈도만)이 있어 호출당 100~300 토큰 수준에서 안정화된다.
