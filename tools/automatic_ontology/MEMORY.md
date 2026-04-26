# tools/automatic_ontology — Progress Log

이 폴더의 진행 사항을 타임스탬프 단위로 누적한다. 최신이 위. 새 작업·결정·문서 변경이 있을 때마다 한 엔트리를 추가한다.

엔트리 양식:
```
## YYYY-MM-DD HH:MM KST

요약 한 줄.

### (선택) 생성/변경된 파일
### (선택) 주요 결정
### (선택) 의도적 비포함 / 미해결
```

---

## 2026-04-26 22:32 KST

자동 온톨로지 추출 인계 가이드 초안 완성.

### 생성된 문서
- [README.md](README.md) — 폴더 목적·범위, 인계 대상, 한 줄 요약.
- [workflow.md](workflow.md) — 7단계 파이프라인, 단계별 프롬프트 템플릿, 결정 포인트, 위험 체크리스트.
- [few_shot_seed.md](few_shot_seed.md) — 요청자 제공 partial 시드 (엔터티 5종, 관계 7종) + 도메인 배경 + 의도적으로 뺀 항목 + 출력 grounding 예시.

### 주요 설계 결정
- **포맷 중립**: OWL/Protégé 가정 없이 plain JSON property-graph (노드 + 타입 엣지 + 속성).
- **Step 2 — 순차 + Running glossary**: 사용 LLM이 배치 미지원. 청크를 순서대로 처리하며 앞 청크들에서 본 (이름, 빈도)만 압축해 prior로 전달. glossary 상한 엔터티 50 / 관계 60 (빈도 내림차순 컷).
- **Step 3 — Python 압축 → 토큰 추정 분기**:
  - 압축: exact name dedup + evidence 폐기 + freq 첨부 → `schema_union_compact.json`.
  - < 30K 토큰: 단일 호출 (3-3a).
  - 30K~100K: 버킷 정규화, K+1회 (3-3b).
  - \> 100K: 계층 합병, ≈ M−1회, 깊이 log₂(M) (3-3c).
  - 세 분기의 `LLM_normalize`는 모두 3-3a의 동일 프롬프트 재사용.
- **시드·glossary anchoring 회피 6요령**: is_seed/is_partial 메타, 기대 규모 명시(15–30/20–40), is_extension_of_seed 강제, "의도적으로 뺀 항목" 섹션, "Do NOT force-fit" 부정 지시, glossary는 이름·빈도만.
- **Dedup 임계값**: τ 기본 0.85, CLI knob `--dedup-threshold`로 노출. 모든 비교쌍은 `dedup_decisions.json`에 audit log.
- **명명 규칙**: 엔터티 `PascalCase`, 관계 `SCREAMING_SNAKE_CASE`.
- **Open-schema**: Step 4에서 `novel_entities` / `novel_relations` 허용, 비어 있지 않으면 Step 6 재정규화 트리거.

### 의도적 비포함
- 구현 코드 (인계 받는 팀이 작성).
- 특정 LLM 제공자 / 임베딩 모델 / 그래프 DB 선택.
- 특정 온톨로지 포맷 (OWL, RDF, Protégé).
