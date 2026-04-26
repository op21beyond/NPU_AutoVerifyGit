# Automatic Ontology Extraction (Reference Guide)

이 폴더는 **다른 팀**이 NPU 아키텍처 문서로부터 자동으로 온톨로지를 추출 → 지식 그래프를 구성 → 그래프 DB에 적재하는 독립 파이프라인을 만들 때 참조하라고 둔 **문서 전용** 디렉터리다. 이 폴더에는 코드가 없다.

## 누구를 위한 문서인가
- 자동 온톨로지 + KG + 그래프 DB 파이프라인을 새로 구현할 팀.
- 본 저장소의 메인 워크플로(`src/stage*`)와는 **독립적**으로 실험한다.

## 무엇이 들어 있나
- [`workflow.md`](workflow.md) — 7단계 파이프라인, 단계별 프롬프트 템플릿, 결정 포인트, 위험 요소. **퓨샷 시드가 들어가는 위치는 `[FEW-SHOT INSERT POINT]`로 표시**.
- [`few_shot_seed.md`](few_shot_seed.md) — 요청자가 제공하는 퓨샷 시드. **partial / illustrative이며 정답표가 아님**을 강하게 명시.

## 무엇이 들어 있지 않나
- 구현 코드, 의존성 락파일, CI 설정 — 팀이 자기 환경(언어, LLM 제공자, 임베딩, 그래프 DB)에 맞춰 정한다.
- 특정 온톨로지 포맷(OWL, RDF, Protégé). 산출물은 plain JSON property-graph 형태로 가정한다.

## 한 줄 요약
> 시드 예시 5~7개를 단서로 LLM이 문서 전체에서 정규화된 엔터티·관계를 찾고, 임베딩+LLM 하이브리드로 인스턴스를 dedup해 그래프 DB에 적재한다.
